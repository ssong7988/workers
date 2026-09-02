"""Visible Edge browser collector for Naver Pay Real Estate result pages."""

from __future__ import annotations

import re
import hashlib
import time
from pathlib import Path
from urllib.parse import urljoin

from .models import Listing, SearchCondition, iso_now
from .parsing import normalize_type_name, parse_price_won


EDGE_LAUNCH_COMMAND = (
    '& "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" '
    "--remote-debugging-port=9222 "
    '--user-data-dir="$env:LOCALAPPDATA\\naver-land-edge"'
)


def _cdp_help(endpoint: str) -> str:
    """Explain how to start the browser this program attaches to.

    Saying only "make sure Edge is running with remote debugging" left the
    actual command undocumented, and every scan failed here.
    """
    return (
        f"디버깅 포트로 열린 Edge를 찾지 못했습니다: {endpoint}\n"
        "  Edge를 아래 명령으로 직접 실행한 뒤 다시 시도하세요.\n"
        f"    {EDGE_LAUNCH_COMMAND}\n"
        "  · --user-data-dir은 필수입니다. Chrome 136(Edge 동일)부터 기본 프로필에서는\n"
        "    --remote-debugging-port가 조용히 무시됩니다. 저장소 밖 경로를 쓰세요.\n"
        "  · 이 전용 프로필에서 네이버에 한 번 로그인하면 그대로 유지됩니다.\n"
        "    로그인은 browser-login으로 진행하세요."
    )


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
    FAVORITE_COUNT_RE = re.compile(r"총\s*(\d+)\s*개")
    COMPLEX_TAB_NAME = "단지"
    BETWEEN_COMPLEX_DELAY_MS = 8_000
    LOGIN_WAIT_SECONDS = 300
    # Runaway guard only; the saved-complex count comes from the screen.
    MAX_FAVORITE_COMPLEXES = 30
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
                    raise CollectionError(_cdp_help(self.cdp_endpoint)) from exc
                if not browser.contexts:
                    raise CollectionError("연결된 Edge에서 브라우저 컨텍스트를 찾지 못했습니다.")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                if self._is_logged_in(page):
                    print("연결된 Edge가 이미 네이버에 로그인돼 있습니다.")
                    return
                # This is the entry point: the user launches Edge themselves and
                # signs in there. Walk them through it rather than telling them
                # to re-run the very command they are already running.
                self._wait_for_login(page, url)
                self._verify_login(page)
                print("네이버 로그인을 확인했습니다. 이 Edge를 켜 둔 채로 조회를 실행하세요.")
                return
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel="msedge",
                headless=False,
                viewport={"width": 1440, "height": 1000},
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                if not self._is_logged_in(page):
                    self._wait_for_login(page, url)
                    self._verify_login(page)
            except Exception:
                context.close()
                raise
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
                    raise CollectionError(_cdp_help(self.cdp_endpoint)) from exc
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
                expected = self._open_favorites(page)
                complexes = self._favorite_complexes(page, expected)
                if len(complexes) != expected:
                    raise CollectionError(
                        f"관심단지 화면은 {expected}개라고 표시하는데 "
                        f"{len(complexes)}개만 읽었습니다. 화면을 확인하세요."
                    )

                collected = []
                for index, complex_info in enumerate(complexes):
                    if index:
                        page.wait_for_timeout(self.BETWEEN_COMPLEX_DELAY_MS)
                    collected.append(self._collect_favorite_complex(page, complex_info))

                return {"observed_at": iso_now(), "complexes": collected}
            finally:
                if not externally_managed:
                    context.close()

    def _open_favorites(self, page) -> int:
        """Open 관심부동산 → 단지 and return how many complexes are saved."""
        self._raise_if_blocked(page)
        links = page.get_by_role("link", name=self.FAVORITES_LINK_RE)
        link = self._first_visible(links)
        if link is None:
            raise CollectionError("부동산 화면에서 관심부동산 링크를 찾지 못했습니다.")
        link.click()
        page.wait_for_timeout(2_500)
        self._raise_if_blocked(page)
        if "관심부동산" not in page.locator("body").inner_text(timeout=10_000):
            raise CollectionError("관심부동산 화면으로 이동하지 못했습니다.")

        # Favorites opens on '최근조회' by default. The tabs are chips: a label
        # wrapping a hidden radio, so click the label as the user does.
        text = ""
        for attempt in range(3):
            if attempt:
                page.wait_for_timeout(1_500)
            chip = self._first_visible(
                page.get_by_text(self.COMPLEX_TAB_NAME, exact=True), min_size=8
            )
            if chip is None:
                continue
            chip.click()
            page.wait_for_timeout(1_500)
            self._raise_if_blocked(page)
            text = page.locator("body").inner_text(timeout=10_000)
            match = self.FAVORITE_COUNT_RE.search(text)
            if match:
                return int(match.group(1))

        snippet = " | ".join(line.strip() for line in text.splitlines() if line.strip())[:300]
        raise CollectionError(
            "관심부동산 단지 탭으로 전환하지 못했습니다. "
            f"'총 N개' 표시를 찾을 수 없습니다. 현재 화면: {snippet}"
        )

    def _favorite_complexes(self, page, limit: int | None = None) -> list[dict[str, str]]:
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
        # Follow whatever the screen reports; MAX_FAVORITE_COMPLEXES is only a
        # runaway guard, so adding or removing a favorite needs no code change.
        cap = min(limit or self.MAX_FAVORITE_COMPLEXES, self.MAX_FAVORITE_COMPLEXES)
        return complexes[:cap]

    def _collect_favorite_complex(self, page, complex_info: dict[str, str]) -> dict:
        # The favorites panel is read once to learn these addresses; going back
        # to it between complexes proved unreliable, because clicking 관심부동산
        # lands on a different panel depending on the page we came from. This is
        # the same public page the panel's own link opens, not a private
        # endpoint, and the heading check below confirms where we landed.
        page.goto(
            urljoin(self.HOME_URL, complex_info["href"]),
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        page.wait_for_timeout(2_500)
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

        # Naver virtualizes this list: scrolling first and expanding afterwards
        # leaves only the last few cards in the DOM. Capture each viewport before
        # moving on so bundled cards that disappear are not lost.
        rows: list[dict] = []
        stable_scrolls = 0
        previous_signature = ""
        for _ in range(80):
            rows.extend(self._expand_listing_groups(page))
            rows.extend(self._visible_listing_rows(page))
            signature = self._visible_listing_signature(page)
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(500)
            current_signature = self._visible_listing_signature(page)
            if current_signature == signature or current_signature == previous_signature:
                stable_scrolls += 1
            else:
                stable_scrolls = 0
            previous_signature = current_signature
            if stable_scrolls >= 3:
                break

        rows.extend(self._expand_listing_groups(page))
        rows.extend(self._visible_listing_rows(page))

        listings = []
        seen: set[str] = set()
        for row in rows:
            listing_id, href = _pick_representative_article(row["articles"])
            if not listing_id:
                fingerprint = f"{complex_info['complex_id']}|{row['text']}"
                listing_id = "card-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
                href = complex_info["href"]
            if listing_id in seen:
                continue
            seen.add(listing_id)
            parsed = _parse_favorite_listing_text(
                row["text"], listing_id, complex_info["name"], href
            )
            if parsed:
                listings.append(parsed)
            if len(listings) >= self.MAX_LISTINGS_PER_COMPLEX:
                break
        return {**complex_info, "listing_count": len(listings), "listings": listings}

    @staticmethod
    def _visible_listing_rows(page) -> list[dict]:
        """Capture standalone cards currently rendered in the virtual list."""
        return page.locator("body").evaluate(
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
                    if (!card || cards.has(card) || card.getClientRects().length === 0) continue;
                    // Expanded bundle rows were captured immediately after the
                    // click. Skip their collapsed/virtualized shells here.
                    if ([...card.querySelectorAll('button')].some(button =>
                        (button.textContent || '').includes('매물목록')
                    )) continue;
                    cards.add(card);
                    // After expanding a bundle, capture each article link with
                    // the text of its own row. Climb until the next parent would
                    // contain multiple article links; that keeps the individual
                    // price beside the correct href.
                    const byHref = new Map();
                    for (const anchor of card.querySelectorAll('a[href*="/articles/"]')) {
                        const href = anchor.getAttribute('href') || '';
                        if (!href) continue;
                        let item = anchor;
                        while (item.parentElement && item.parentElement !== card) {
                            const parent = item.parentElement;
                            if (parent.querySelectorAll('a[href*="/articles/"]').length > 1) break;
                            item = parent;
                        }
                        const text = (item.innerText || anchor.innerText || '').trim();
                        if (!byHref.has(href) || text.length > byHref.get(href).text.length) {
                            byHref.set(href, {href, text});
                        }
                    }
                    rows.push({
                        articles: [...byHref.values()],
                        text: (card.innerText || '').trim()
                    });
                }
                return rows;
            }"""
        )

    @staticmethod
    def _visible_listing_signature(page) -> str:
        """Return visible card text so a virtual list's real end can be detected."""
        return page.locator("body").evaluate(
            r"""body => [...body.querySelectorAll('li')]
                .filter(card => card.getClientRects().length > 0 && /전용\s*\d/.test(card.innerText || ''))
                .map(card => (card.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 180))
                .join('\n')"""
        )

    @staticmethod
    def _listing_root_count(page) -> int:
        """Count loaded card roots, including bundles that have no article link yet."""
        return page.locator("body").evaluate(
            """body => [...body.querySelectorAll('button, a')].filter(element =>
                (element.textContent || '').trim() === '매물목록 펼치기' ||
                (element.getAttribute('href') || '').includes('/articles/')
            ).length"""
        )

    def _expand_listing_groups(self, page) -> list[dict]:
        """Open bundles and capture their article rows before Naver virtualizes them."""
        rows: list[dict] = []
        for _ in range(self.MAX_LISTINGS_PER_COMPLEX):
            # Find the button, its owning card and invoke the click atomically.
            # React replaces this part of the DOM as bundles expand, so holding
            # a Locator across separate find/scroll/click calls races that render.
            card_handle = page.locator("body").evaluate_handle(
                r"""body => {
                    const button = [...body.querySelectorAll('button')].find(element =>
                        (element.textContent || '').trim() === '매물목록 펼치기' &&
                        element.getClientRects().length > 0
                    );
                    if (!button) return null;
                    let card = button.closest('li');
                    while (card && !/전용\s*\d/.test(card.innerText || '')) {
                        card = card.parentElement?.closest('li') || null;
                    }
                    if (!card) return null;
                    // Naver's sticky filter header can cover the button after
                    // scrolling. Calling the same visible control's handler
                    // avoids pointer interception by that fixed overlay.
                    button.click();
                    return card;
                }"""
            ).as_element()
            if card_handle is None:
                break
            for _ in range(32):
                if card_handle.query_selector('a[href*="/articles/"]') is not None:
                    break
                page.wait_for_timeout(250)
            else:
                summary = " ".join(
                    (card_handle.inner_text() or "").split()
                )[:160]
                raise CollectionError(
                    "매물목록을 펼쳤지만 개별 매물 링크가 나타나지 않았습니다: "
                    f"{summary}"
                )
            rows.append(
                card_handle.evaluate(
                    r"""card => {
                        const byHref = new Map();
                        for (const anchor of card.querySelectorAll('a[href*="/articles/"]')) {
                            const href = anchor.getAttribute('href') || '';
                            if (!href) continue;
                            let item = anchor;
                            while (item.parentElement && item.parentElement !== card) {
                                const parent = item.parentElement;
                                if (parent.querySelectorAll('a[href*="/articles/"]').length > 1) break;
                                item = parent;
                            }
                            const text = (item.innerText || anchor.innerText || '').trim();
                            if (!byHref.has(href) || text.length > byHref.get(href).text.length) {
                                byHref.set(href, {href, text});
                            }
                        }
                        return {
                            articles: [...byHref.values()],
                            text: (card.innerText || '').trim()
                        };
                    }"""
                )
            )
        remaining = page.locator("body").evaluate(
            """body => [...body.querySelectorAll('button')].some(element =>
                (element.textContent || '').trim() === '매물목록 펼치기' &&
                element.getClientRects().length > 0
            )"""
        )
        if remaining:
            raise CollectionError(
                "매물목록 펼치기가 비정상적으로 많이 반복되어 수집을 중단했습니다."
            )
        # The expanded agent rows are populated asynchronously after the click.
        page.wait_for_timeout(800)
        return rows

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

    def _is_logged_in(self, page) -> bool:
        page.goto(self.NAVER_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_500)
        return "로그아웃" in page.locator("body").inner_text(timeout=10_000)

    def _wait_for_login(self, page, url: str) -> None:
        """Open Naver's login form and wait for the user to finish signing in.

        Waiting on stdin would make this unusable wherever there is no terminal,
        so watch the page instead: Naver leaves nid.naver.com once the login
        succeeds. Polling the URL avoids navigating away from the form while the
        user is still filling it in.
        """
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        print(
            "브라우저에서 네이버 로그인을 완료하세요. "
            f"완료되면 자동으로 이어집니다 (최대 {self.LOGIN_WAIT_SECONDS // 60}분 대기)."
        )
        deadline = time.monotonic() + self.LOGIN_WAIT_SECONDS
        while time.monotonic() < deadline:
            page.wait_for_timeout(2_000)
            if "nid.naver.com" not in (page.url or ""):
                # Let Naver's own post-login redirect settle.
                page.wait_for_timeout(2_000)
                return
        raise CollectionError("로그인 대기 시간이 지났습니다. browser-login을 다시 실행하세요.")

    def _verify_login(self, page) -> None:
        if not self._is_logged_in(page):
            raise CollectionError(
                "네이버 로그인이 안 된 Edge입니다. browser-login을 실행해 로그인하세요."
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
    def _first_visible(locator, min_size: int = 0):
        """First on-screen match, optionally ignoring hairline elements.

        Naver ships screen-reader-only `span.blind` copies of its labels. They
        are 1x1 but still report as visible, so a plain is_visible() check can
        hand back an element that swallows the click.
        """
        for index in range(locator.count()):
            candidate = locator.nth(index)
            if not candidate.is_visible():
                continue
            if min_size:
                box = candidate.bounding_box()
                if not box or box["width"] < min_size or box["height"] < min_size:
                    continue
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


def _pick_representative_article(articles: list[dict[str, str]]) -> tuple[str, str]:
    """Choose which listing a card should link to.

    Naver bundles several agents' listings into a single card whose price is
    shown as a range. Choose the cheapest expanded individual listing; when
    prices tie, keep the newest article number because those numbers grow over
    time.

    Returns `(listing_id, href)`, both empty when the card links to no article.
    """
    candidates: list[tuple[int, int, str, str]] = []
    unpriced: list[tuple[int, str, str]] = []
    for article in articles:
        href = article.get("href", "")
        listing_id = _extract_listing_id(href)
        if not listing_id:
            continue
        article_number = int(listing_id)
        try:
            price = parse_price_won(_extract_price_text(article.get("text", "")))
        except ValueError:
            unpriced.append((article_number, listing_id, href))
            continue
        # Lowest price wins; the negative article number makes the newest ID
        # sort first when two individual listings have the same price.
        candidates.append((price, -article_number, listing_id, href))
    if candidates:
        _, _, listing_id, href = min(candidates)
        return listing_id, href
    if unpriced:
        _, listing_id, href = max(unpriced)
        return listing_id, href
    return "", ""


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
