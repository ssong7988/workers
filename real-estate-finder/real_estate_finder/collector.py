"""Visible Edge browser collector for Naver Pay Real Estate result pages."""

from __future__ import annotations

import re
import hashlib
import time
from pathlib import Path
from urllib.parse import urljoin

from .models import Listing, SearchCondition, iso_now
from .parsing import normalize_type_name, parse_price_won


class CollectionError(RuntimeError):
    pass


class NaverBrowserCollector:
    """Collect visible listing cards without private endpoints or challenge bypasses."""

    HOME_URL = "https://fin.land.naver.com/"
    NAVER_HOME_URL = "https://www.naver.com/"
    LOGIN_URL = (
        "https://nid.naver.com/nidlogin.login?url="
        "https%3A%2F%2Fland.naver.com%2F"
    )
    BEFORE_TYPING_DELAY_MS = 5_000
    BEFORE_SEARCH_DELAY_MS = 15_000
    CARD_SELECTORS = ("li.item", ".item_inner", "[class*='item_inner']")
    ARTICLE_LINK_SELECTOR = "a[href*='/articles/'], a[href*='articleNo=']"
    FAVORITES_LINK_RE = re.compile(r"^관심부동산(?:\s+현재 위치)?$")
    FAVORITE_ARTICLE_HREF_RE = re.compile(r"^/complexes/(\d+)\?tab=article$")
    BETWEEN_COMPLEX_DELAY_MS = 8_000
    MAX_FAVORITE_COMPLEXES = 6
    MAX_LISTINGS_PER_COMPLEX = 120
    WORLD_MARK_COMPLEX_IDS = {"104517"}

    def __init__(
        self,
        profile_dir: Path,
        headed: bool = True,
        cdp_endpoint: str | None = None,
    ) -> None:
        self.profile_dir = profile_dir
        self.headed = headed
        self.cdp_endpoint = cdp_endpoint

    def open_login(self, url: str = LOGIN_URL) -> None:
        sync_playwright = _load_playwright()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            if self.cdp_endpoint:
                try:
                    browser = playwright.chromium.connect_over_cdp(self.cdp_endpoint)
                except Exception as exc:
                    raise CollectionError(
                        "현재 Edge에 연결할 수 없습니다. Edge가 원격 디버깅 포트와 함께 "
                        f"실행 중인지 확인하세요: {self.cdp_endpoint}"
                    ) from exc
                if not browser.contexts:
                    raise CollectionError("연결된 Edge에서 브라우저 컨텍스트를 찾지 못했습니다.")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                self._verify_login(page)
                return
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel="msedge",
                headless=False,
                viewport={"width": 1440, "height": 1000},
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(self.NAVER_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_500)
            if "로그아웃" in page.locator("body").inner_text(timeout=10_000):
                context.close()
                return
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            input("브라우저에서 네이버 로그인을 완료한 뒤 Enter를 누르세요: ")
            # The login page may still be completing its own redirect when the
            # user confirms. Let that navigation settle before opening home.
            page.wait_for_timeout(2_000)
            for attempt in range(3):
                try:
                    page.goto(
                        self.NAVER_HOME_URL,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    break
                except Exception:
                    if attempt == 2:
                        context.close()
                        raise
                    page.wait_for_timeout(1_500)
            page.wait_for_timeout(2_000)
            if "로그아웃" not in page.locator("body").inner_text():
                context.close()
                raise CollectionError(
                    "네이버 로그인 상태를 확인하지 못했습니다. browser-login을 다시 실행하세요."
                )
            # Closing a persistent context flushes the authenticated browser profile
            # to disk. Later scheduled runs reuse this exact profile directory.
            context.close()

    def collect_all(self, conditions: list[SearchCondition]) -> dict[str, list[Listing]]:
        snapshot = self.collect_favorites_snapshot()
        results: dict[str, list[Listing]] = {condition.id: [] for condition in conditions}
        for condition in conditions:
            for complex_info in snapshot["complexes"]:
                compact_name = complex_info["name"].replace(" ", "")
                if not any(
                    alias.replace(" ", "") in compact_name for alias in condition.complex_names
                ):
                    continue
                for raw in complex_info["listings"]:
                    results[condition.id].append(
                        Listing(
                            condition_id=condition.id,
                            listing_id=raw["listing_id"],
                            complex_name=raw["complex_name"],
                            type_name=raw["type_name"],
                            exclusive_area_m2=raw["exclusive_area_m2"],
                            price_won=raw["price_won"],
                            floor_text=raw["floor_text"],
                            floor=None,
                            direction=raw["direction"],
                            description=raw["description"],
                            url=raw["url"],
                            observed_at=raw["observed_at"],
                        )
                    )
        return results

    def collect_favorites_snapshot(self) -> dict:
        """Collect the six visible favorite complexes through the signed-in UI.

        The flow deliberately starts at Naver, clicks the public Real Estate and
        Favorites controls, and never calls an undocumented endpoint.  It uses a
        fixed, conservative pause between complexes and stops on login/challenge
        pages instead of attempting to work around them.
        """
        sync_playwright = _load_playwright()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            externally_managed = bool(self.cdp_endpoint)
            if externally_managed:
                try:
                    browser = playwright.chromium.connect_over_cdp(self.cdp_endpoint)
                except Exception as exc:
                    raise CollectionError(
                        f"실행 중인 Edge에 연결하지 못했습니다: {self.cdp_endpoint}"
                    ) from exc
                if not browser.contexts:
                    raise CollectionError("연결된 Edge에서 브라우저 컨텍스트를 찾지 못했습니다.")
                context = browser.contexts[0]
            else:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    channel="msedge",
                    headless=not self.headed,
                    viewport={"width": 1440, "height": 1000},
                )

            page = context.pages[0] if context.pages else context.new_page()
            try:
                self._verify_login(page)
                self._open_land_from_naver_home(page)
                self._open_favorites(page)
                complexes = self._favorite_complexes(page)
                if len(complexes) != self.MAX_FAVORITE_COMPLEXES:
                    raise CollectionError(
                        f"관심단지 {self.MAX_FAVORITE_COMPLEXES}개를 예상했지만 "
                        f"{len(complexes)}개를 찾았습니다. 화면을 확인하세요."
                    )

                collected = []
                for index, complex_info in enumerate(complexes):
                    if index:
                        page.wait_for_timeout(self.BETWEEN_COMPLEX_DELAY_MS)
                    collected.append(self._collect_favorite_complex(page, complex_info))
                    if index < len(complexes) - 1:
                        self._open_favorites(page)

                return {"observed_at": iso_now(), "complexes": collected}
            finally:
                if not externally_managed:
                    context.close()

    def _open_favorites(self, page) -> None:
        self._raise_if_blocked(page)
        links = page.get_by_role("link", name=self.FAVORITES_LINK_RE)
        link = self._first_visible(links)
        if link is None:
            raise CollectionError("부동산 화면에서 관심부동산 링크를 찾지 못했습니다.")
        link.click()
        page.wait_for_timeout(1_500)
        self._raise_if_blocked(page)
        if "관심부동산" not in page.locator("body").inner_text(timeout=10_000):
            raise CollectionError("관심부동산 화면으로 이동하지 못했습니다.")

        # Favorites opens on '최근조회' by default. Click the visible '단지'
        # label just as the user does; clicking the hidden radio itself is less
        # reliable on the current SPA.
        complex_labels = page.get_by_text("단지", exact=True)
        complex_label = self._first_visible(complex_labels)
        if complex_label is None:
            raise CollectionError("관심부동산에서 단지 탭을 찾지 못했습니다.")
        complex_label.click()
        page.wait_for_timeout(1_200)
        self._raise_if_blocked(page)
        if "총 6개" not in page.locator("body").inner_text(timeout=10_000):
            raise CollectionError("관심부동산 단지 탭에서 총 6개 표시를 확인하지 못했습니다.")

    def _favorite_complexes(self, page) -> list[dict[str, str]]:
        rows = page.locator("a").evaluate_all(
            """els => els.map(a => ({
                href: a.getAttribute('href') || '',
                text: (a.textContent || '').trim(),
                card: (a.closest('li')?.innerText || '').trim()
            }))"""
        )
        complexes: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in rows:
            match = self.FAVORITE_ARTICLE_HREF_RE.match(row["href"])
            if not match or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            card_lines = [line.strip() for line in row["card"].splitlines() if line.strip()]
            name = card_lines[1] if len(card_lines) > 1 and card_lines[0] == "아파트" else ""
            complexes.append(
                {"complex_id": match.group(1), "name": name, "href": row["href"]}
            )
        return complexes[: self.MAX_FAVORITE_COMPLEXES]

    def _collect_favorite_complex(self, page, complex_info: dict[str, str]) -> dict:
        href = complex_info["href"]
        link = page.locator(f'a[href="{href}"]').first
        if link.count() == 0 or not link.is_visible():
            raise CollectionError(f"{complex_info['name']}: 매물보기 링크를 찾지 못했습니다.")
        link.click()
        page.wait_for_timeout(2_000)
        self._raise_if_blocked(page)

        heading = page.get_by_role("heading", name=complex_info["name"], exact=True)
        if heading.count() == 0:
            raise CollectionError(f"{complex_info['name']}: 단지 매물 화면 이동을 확인하지 못했습니다.")

        # Worldmark is limited more tightly to exclusive 84~85㎡. The other
        # configured 84 groups retain the user's broader 83~86㎡ UI selection.
        if complex_info["complex_id"] in self.WORLD_MARK_COMPLEX_IDS:
            self._select_similar_exclusive_area(page, minimum=84, maximum=85.999)
        else:
            self._select_similar_exclusive_area(page, minimum=83, maximum=86)

        for _ in range(20):
            before = page.locator(self.ARTICLE_LINK_SELECTOR).count()
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(500)
            after = page.locator(self.ARTICLE_LINK_SELECTOR).count()
            if after == before:
                break

        rows = page.locator("body").evaluate(
            r"""els => {
                const cards = new Set();
                const rows = [];
                const roots = [
                    ...document.querySelectorAll('button'),
                    ...document.querySelectorAll('a[href*="/articles/"]')
                ].filter(e =>
                    (e.textContent || '').trim() === '매물목록 펼치기' ||
                    (e.getAttribute('href') || '').includes('/articles/')
                );
                for (const root of roots) {
                    let card = root.closest('li');
                    while (card && !/전용\s*\d/.test(card.innerText || '')) {
                        card = card.parentElement?.closest('li') || null;
                    }
                    if (!card || cards.has(card)) continue;
                    cards.add(card);
                    const representative = card.querySelector('a[href*="/articles/"]');
                    rows.push({
                        href: representative?.getAttribute('href') || '',
                        text: (card.innerText || '').trim()
                    });
                }
                return rows;
            }"""
        )
        listings = []
        seen: set[str] = set()
        for row in rows:
            listing_id = _extract_listing_id(row["href"])
            if not listing_id:
                fingerprint = f"{complex_info['complex_id']}|{row['text']}"
                listing_id = "card-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
            if listing_id in seen:
                continue
            seen.add(listing_id)
            parsed = _parse_favorite_listing_text(
                row["text"], listing_id, complex_info["name"], row["href"]
            )
            if parsed:
                listings.append(parsed)
            if len(listings) >= self.MAX_LISTINGS_PER_COMPLEX:
                break
        return {**complex_info, "listing_count": len(listings), "listings": listings}

    def _select_similar_exclusive_area(self, page, minimum: float, maximum: float) -> None:
        area_button = page.get_by_role("button", name="전체면적", exact=True)
        button = self._first_visible(area_button)
        if button is None:
            raise CollectionError("매물 화면에서 전체면적 필터를 찾지 못했습니다.")
        button.click()
        page.wait_for_timeout(300)

        group_button = page.locator("button").filter(
            has_text=re.compile(r"^유사면적 묶기$")
        )
        grouping = self._first_visible(group_button)
        if grouping is None:
            raise CollectionError("면적 필터에서 유사면적 묶기를 찾지 못했습니다.")
        group_class = grouping.get_attribute("class") or ""
        if "checked" not in group_class:
            grouping.click()
            page.wait_for_timeout(300)

        all_labels = page.locator("label").filter(has_text=re.compile(r"^전체면적"))
        all_label = self._first_visible(all_labels)
        if all_label is None:
            raise CollectionError("면적 필터에서 전체면적 선택 항목을 찾지 못했습니다.")
        if "is-checked" in (all_label.get_attribute("class") or ""):
            all_label.click()
            page.wait_for_timeout(300)

        selected = 0
        labels = page.locator("label")
        for index in range(labels.count()):
            label = labels.nth(index)
            if not label.is_visible():
                continue
            text = label.inner_text(timeout=3_000).strip()
            match = re.search(r"\((\d+(?:\.\d+)?)\)", text)
            target = bool(match) and minimum <= float(match.group(1)) <= maximum
            checked = "is-checked" in (label.get_attribute("class") or "")
            if checked != target:
                label.click()
                page.wait_for_timeout(250)
            if target:
                selected += 1
                if "is-checked" not in (label.get_attribute("class") or ""):
                    raise CollectionError(f"전용면적 {text} 선택을 확인하지 못했습니다.")
        if not selected:
            raise CollectionError(
                f"괄호 안 전용면적 {minimum:g}~{maximum:g}㎡ 항목을 찾지 못했습니다."
            )
        page.wait_for_timeout(700)

    @staticmethod
    def _raise_if_blocked(page) -> None:
        text = page.locator("body").inner_text(timeout=10_000)
        lowered = text.lower()
        if "captcha" in lowered or "자동입력 방지" in text or "비정상적인 접근" in text:
            raise CollectionError("CAPTCHA 또는 접근 제한이 감지되어 수집을 중단했습니다.")
        if "로그인" in text and "로그아웃" not in text and "내정보 보기" not in text:
            raise CollectionError("네이버 로그인 상태가 만료되어 수집을 중단했습니다.")

    def _verify_login(self, page) -> None:
        page.goto(self.NAVER_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_500)
        if "로그아웃" not in page.locator("body").inner_text():
            raise CollectionError(
                "저장된 네이버 로그인이 만료됐습니다. browser-login을 다시 실행하세요."
            )

    def _collect_condition(self, page, condition: SearchCondition) -> list[Listing]:
        try:
            self._navigate_with_visible_ui(page, condition)
        except Exception as exc:
            if isinstance(exc, CollectionError):
                raise
            raise CollectionError(f"화면 검색 실패: {exc}") from exc

        body_text = page.locator("body").inner_text(timeout=10_000)
        lowered = body_text.lower()
        if "captcha" in lowered or "자동입력 방지" in body_text or "비정상적인 접근" in body_text:
            raise CollectionError("CAPTCHA 또는 접근 제한이 감지되었습니다.")
        if "로그인" in body_text and "로그아웃" not in body_text and "매물" not in body_text:
            raise CollectionError("네이버 로그인 상태를 확인하세요.")

        card_selector = self._first_existing_selector(page, self.CARD_SELECTORS)
        if not card_selector:
            raise CollectionError("매물 카드 DOM을 찾지 못했습니다. 사이트 구조를 확인하세요.")

        stable_rounds = 0
        previous_count = -1
        for _ in range(40):
            count = page.locator(card_selector).count()
            if count == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous_count = count
            if stable_rounds >= 3:
                break
            page.locator(card_selector).last.scroll_into_view_if_needed(timeout=5_000)
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(800)

        observed_at = iso_now()
        listings: dict[str, Listing] = {}
        cards = page.locator(card_selector)
        for index in range(cards.count()):
            card = cards.nth(index)
            try:
                listing = self._parse_card(card, condition, observed_at)
            except (ValueError, TimeoutError):
                continue
            if listing:
                listings[listing.listing_id] = listing
        if not listings and cards.count() > 0:
            raise CollectionError("매물 카드는 찾았지만 필수 정보를 파싱하지 못했습니다.")
        return list(listings.values())

    def _navigate_with_visible_ui(self, page, condition: SearchCondition) -> None:
        """Open the public home and use its visible search controls.

        This deliberately does not navigate to a stored listing URL, call a private
        endpoint, alter browser fingerprints, or bypass an access challenge.
        """
        self._open_land_from_naver_home(page)
        page.wait_for_timeout(2_000)
        search = page.locator("#queryInputHeader")
        if search.count() == 0 or not search.first.is_visible():
            raise CollectionError("부동산 홈 검색창을 찾지 못했습니다.")

        query = condition.complex_names[0]
        search.first.click()
        search.first.fill("")
        page.wait_for_timeout(self.BEFORE_TYPING_DELAY_MS)
        search.first.press_sequentially(query, delay=80)
        page.wait_for_timeout(self.BEFORE_SEARCH_DELAY_MS)

        candidates = page.get_by_text(query, exact=False)
        clicked = False
        for index in range(min(candidates.count(), 10)):
            candidate = candidates.nth(index)
            if candidate.is_visible() and candidate.evaluate(
                "e => Boolean(e.closest('a, button, [role=option]'))"
            ):
                candidate.click()
                clicked = True
                break
        if not clicked:
            # The legacy public search has no visible submit button; Enter invokes
            # the same UI handler as a person completing the search field.
            search.first.press("Enter")

        page.wait_for_timeout(5_000)
        if page.url.endswith("/404") or "페이지를 찾을 수 없습니다" in page.locator("body").inner_text():
            raise CollectionError(
                "네이버 화면 검색 결과가 404로 이동했습니다. 현재 서비스 전환 상태를 확인하세요."
            )

    def _open_land_from_naver_home(self, page) -> None:
        """Open Naver first, then enter Real Estate through a visible UI click."""
        page.goto(self.NAVER_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)

        land_links = page.locator(
            'a[href*="land.naver.com"], a[href*="new.land.naver.com"], '
            'a[href*="fin.land.naver.com"]'
        )
        land_link = self._first_visible(land_links)

        if land_link is None:
            more_controls = page.get_by_text(
                re.compile(r"서비스\s*(더보기|전체보기)|더보기")
            )
            more_control = self._first_visible(more_controls)
            if more_control is not None:
                more_control.click()
                page.wait_for_timeout(1_000)
                land_link = self._first_visible(land_links)

        if land_link is None:
            raise CollectionError("네이버 홈에서 부동산 링크를 찾지 못했습니다.")

        # Keep navigation in this tab so the same persistent browser session is
        # reused by every configured search.
        land_link.evaluate("e => e.removeAttribute('target')")
        land_link.click()
        page.wait_for_load_state("domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)
        if "land.naver.com" not in page.url:
            raise CollectionError("네이버 홈의 부동산 링크 클릭 후 이동을 확인하지 못했습니다.")

    @staticmethod
    def _first_visible(locator):
        for index in range(locator.count()):
            candidate = locator.nth(index)
            if candidate.is_visible():
                return candidate
        return None

    @staticmethod
    def _first_existing_selector(page, selectors: tuple[str, ...]) -> str | None:
        for selector in selectors:
            if page.locator(selector).count() > 0:
                return selector
        return None

    def _parse_card(self, card, condition: SearchCondition, observed_at: str) -> Listing | None:
        text = card.inner_text(timeout=5_000).strip()
        if not text:
            return None
        href = ""
        link = card.locator(self.ARTICLE_LINK_SELECTOR)
        if link.count():
            href = link.first.get_attribute("href") or ""
        raw_html = card.inner_html(timeout=5_000)
        listing_id = _extract_listing_id(href + " " + raw_html)
        if not listing_id:
            return None

        price_text = _extract_price_text(text)
        area = _extract_area(text)
        floor_text = _extract_floor_text(text)
        type_name = normalize_type_name(_extract_type_text(text, area))
        complex_name = _extract_complex_name(text, condition)
        direction = _extract_direction(text)
        url = urljoin(self.HOME_URL, href) if href else self.HOME_URL
        return Listing(
            condition_id=condition.id,
            listing_id=listing_id,
            complex_name=complex_name,
            type_name=type_name,
            exclusive_area_m2=area,
            price_won=parse_price_won(price_text),
            floor_text=floor_text,
            floor=None,
            direction=direction,
            description=" ".join(text.splitlines())[:300],
            url=url,
            observed_at=observed_at,
        )


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("playwright가 없습니다. requirements.txt를 설치하세요.") from exc
    return sync_playwright


def _extract_listing_id(text: str) -> str:
    patterns = (r"/articles/(\d+)", r"articleNo[=\"':]+(\d+)", r"data-article-no=[\"'](\d+)")
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _extract_price_text(text: str) -> str:
    match = re.search(r"(?:매매\s*)?(\d+(?:\.\d+)?억(?:\s*\d[\d,]*)?|\d[\d,]{5,})", text)
    if not match:
        raise ValueError("가격 없음")
    return match.group(1)


def _extract_area(text: str) -> float:
    patterns = (r"전용\s*(\d+(?:\.\d+)?)", r"(?:^|\s)(\d{2,3}(?:\.\d+)?)\s*[A-Z]?㎡")
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if match:
            return float(match.group(1))
    raise ValueError("전용면적 없음")


def _extract_floor_text(text: str) -> str:
    match = re.search(r"(?:저층|중층|고층|저|중|고|\d{1,3})\s*(?:/\s*\d{1,3})?\s*층?", text)
    if not match:
        raise ValueError("층수 없음")
    return match.group(0).strip()


def _extract_type_text(text: str, area: float) -> str:
    match = re.search(r"(?:전용)?\s*84(?:\.\d+)?\s*([A-Z])?", text, re.IGNORECASE)
    return f"84{(match.group(1) or '').upper()}" if match else str(area)


def _extract_complex_name(text: str, condition: SearchCondition) -> str:
    compact = text.replace(" ", "")
    for alias in condition.complex_names:
        if alias.replace(" ", "") in compact:
            return alias
    return condition.complex_names[0]


def _extract_direction(text: str) -> str:
    match = re.search(r"(남동향|남서향|북동향|북서향|남향|북향|동향|서향)", text)
    return match.group(1) if match else "미상"


def _parse_favorite_listing_text(
    text: str,
    listing_id: str,
    complex_name: str,
    href: str,
) -> dict | None:
    """Parse the text shown on one public favorite-complex listing card."""
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    price_match = re.search(r"매매\s+(\d+(?:\.\d+)?억(?:\s*\d[\d,]*)?)", normalized)
    area_match = re.search(r"전용\s*(\d+(?:\.\d+)?)\s*([A-Z])?", normalized, re.IGNORECASE)
    floor_match = re.search(r"(?:저|중|고|\d{1,3})\s*/\s*\d{1,3}층|(?:저층|중층|고층|\d{1,3}층)", normalized)
    if not price_match or not area_match or not floor_match:
        return None
    direction = _extract_direction(normalized)
    building_match = re.search(re.escape(complex_name) + r"\s+([^\n]+동)", normalized)
    confirmed_match = re.search(r"확인매물\s*(\d{4}\.\d{2}\.\d{2})", normalized)
    area = float(area_match.group(1))
    suffix = (area_match.group(2) or "").upper()
    return {
        "listing_id": listing_id,
        "complex_name": complex_name,
        "building": building_match.group(1) if building_match else "",
        "trade_type": "매매",
        "price_text": price_match.group(1),
        "price_won": parse_price_won(price_match.group(1)),
        "exclusive_area_m2": area,
        "type_name": f"{int(area) if area.is_integer() else area:g}{suffix}",
        "floor_text": floor_match.group(0),
        "direction": direction,
        "confirmed_date": confirmed_match.group(1) if confirmed_match else "",
        "description": " ".join(normalized.splitlines())[:500],
        "url": urljoin(NaverBrowserCollector.HOME_URL, href),
        "observed_at": iso_now(),
    }
