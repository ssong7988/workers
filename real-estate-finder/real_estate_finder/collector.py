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


# Naver states, on the screen itself, how much there is to collect: a bundled
# card says how many agents registered the same unit, and the complex header
# counts the cards per trade type. Both are used to prove nothing was skipped.
AGENT_COUNT_RE = re.compile(r"중개사\s*(\d+)\s*곳")
TRADE_COUNT_RE = re.compile(r"^(매매|전세|월세|단기)\s*([\d,]+)$")
# The listing pane's own header, which counts what the current filters left.
# The lookbehind keeps the agency advertisement's "단지 보유 매물 16개" out.
LIST_COUNT_RE = re.compile(r"(?<!보유 )매물\s*([\d,]+)\s*개")

# Shared browser-side helpers. Naver hashes its CSS module class names per
# build, so use the stable list element and fall back to climbing from the
# controls that every card carries.
_CARD_HELPERS_JS = r"""
    const hasArea = node => /전용\s*\d/.test(node.innerText || '');
    const collectCards = () => {
        const list = document.querySelector('ul[class*="ComplexArticleTab"]');
        if (list) {
            return [...list.children].filter(item => item.tagName === 'LI' && hasArea(item));
        }
        const found = new Set();
        for (const root of document.querySelectorAll('button, a[href*="/articles/"]')) {
            if (!(root.textContent || '').includes('매물목록') &&
                !(root.getAttribute('href') || '').includes('/articles/')) continue;
            let card = root.closest('li');
            while (card && !hasArea(card)) card = card.parentElement?.closest('li') || null;
            if (card) found.add(card);
        }
        return [...found];
    };
    const cardArticles = card => {
        const byHref = new Map();
        for (const anchor of card.querySelectorAll('a[href*="/articles/"]')) {
            const href = anchor.getAttribute('href') || '';
            if (!href) continue;
            // Climb until the next parent would hold a second article link, so
            // each row's own price stays beside its own href.
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
        return [...byHref.values()];
    };
"""


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
    # Runaway guards only; the screen's own counts decide when a scan is done.
    MAX_LISTINGS_PER_COMPLEX = 300
    MAX_SCROLL_ROUNDS = 120
    # Narrow the screen before collecting. 86 rather than 85 because
    # explain_condition() passes 84-1 ~ 84+2 for every configured 84 type, and a
    # tighter screen filter would drop those listings before Python ever saw them.
    TRADE_TYPE = "매매"
    SCREEN_AREA_MIN_M2 = 80
    SCREEN_AREA_MAX_M2 = 86
    MAX_AREA_OPTIONS = 40
    TRADE_TYPE_NAMES = ("매매", "전세", "월세", "단기임대", "단기")
    ALL_TRADE_TYPES_LABEL = "전체거래유형"
    # Every trade type starts checked; narrowing to sales means unchecking
    # the others rather than selecting 매매.
    TRADE_OPTIONS_TO_CLEAR = ("전세", "월세", "단기임대")

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

        expected = self._apply_screen_filters(page)
        groups = self._collect_complex_cards(page, expected)
        if len(groups) < expected:
            # A card can still be missed when the list grows underneath the
            # scroll position while a bundle expands. One more pass from the top
            # merges into the same groups, so nothing already read is lost.
            groups = self._collect_complex_cards(page, expected, groups)
        if len(groups) < expected:
            raise CollectionError(
                f"{complex_info['name']}: 화면은 매물 {expected}건인데 "
                f"{len(groups)}건만 읽었습니다."
            )

        listings = []
        for group in groups:
            articles = list(group["articles"].values())
            listing_id, href = _pick_representative_article(articles)
            if not listing_id:
                fingerprint = f"{complex_info['complex_id']}|{group['text']}"
                listing_id = "card-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
                href = complex_info["href"]
            parsed = _parse_favorite_listing_text(
                group["text"], listing_id, complex_info["name"], href
            )
            if parsed:
                listings.append(parsed)
        # card_count covers every trade type; listing_count only the sale cards
        # _parse_favorite_listing_text keeps, so the two differ by design.
        return {
            **complex_info,
            "expected_count": expected,
            "card_count": len(groups),
            "listing_count": len(listings),
            "listings": listings,
        }

    def _collect_complex_cards(
        self, page, expected: int, groups: list[dict] | None = None
    ) -> list[dict]:
        """Read the listing pane from top to bottom, expanding bundles on the way.

        Every card is re-read on every pass and merged by article number, so a
        bundle captured while it was still rendering gets completed later
        instead of being lost.
        """
        groups = groups if groups is not None else []
        self._scroll_listing_to_top(page)
        stable = 0
        seen_height = -1
        seen_count = -1
        for _ in range(self.MAX_SCROLL_ROUNDS):
            for row in self._expand_listing_groups(page):
                _merge_article_rows(groups, row)
            for row in self._visible_listing_rows(page):
                _merge_article_rows(groups, row)
            if len(groups) >= expected and self._listing_scroll_state(page)["at_bottom"]:
                return groups
            state = self._scroll_listing_view(page)
            page.wait_for_timeout(700)
            # Reaching the bottom is not the end: this list appends more cards
            # there, and the old 1.5s stall check gave up before they arrived.
            grew = state["height"] > seen_height or len(groups) > seen_count
            seen_height = max(seen_height, state["height"])
            seen_count = max(seen_count, len(groups))
            if state["at_bottom"] and not state["moved"] and not grew:
                stable += 1
            else:
                stable = 0
            if stable >= 3:
                break
        return groups

    def _apply_screen_filters(self, page) -> int:
        """Narrow the screen to sale listings of the wanted area, and report how
        many cards that leaves.

        Collecting the unfiltered complex was correct but meant working through
        every trade type and every area, around 83 cards per complex. These are
        the filters a person would click, and the list header then states the
        count the scan has to account for.
        """
        # A popover left open by an earlier complex would swallow these clicks.
        self._close_filter_popover(page, self._area_filter_chip(page))
        self._close_filter_popover(page, self._trade_filter_chip(page))
        # Naver's single-page app remembers an area selection across complexes,
        # so clear it before choosing again.
        self._reset_exclusive_area_filter(page)
        tabs = self._trade_tab_counts(page)
        self._select_trade_type(page, tabs)
        self._select_similar_exclusive_area(
            page, self.SCREEN_AREA_MIN_M2, self.SCREEN_AREA_MAX_M2
        )

        expected = self._settled_list_card_count(page)
        sale = tabs.get(self.TRADE_TYPE, 0)
        if expected > sale:
            raise CollectionError(
                f"매매 {sale}건보다 많은 {expected}건이 목록에 남았습니다. "
                "거래유형·면적 필터가 적용되지 않았습니다."
            )
        return expected

    def _select_trade_type(self, page, tabs: dict[str, int]) -> None:
        """Set the trade-type filter to sales only."""
        chip = self._trade_filter_chip(page)
        if chip is None:
            raise CollectionError("매물 화면에서 거래유형 필터를 찾지 못했습니다.")
        self._open_filter_popover(page, chip, "거래유형")

        for name in self.TRADE_OPTIONS_TO_CLEAR:
            option = self._filter_option(page, name)
            if option is not None and self._filter_label_checked(option):
                option.click()
                page.wait_for_timeout(250)
        option = self._filter_option(page, self.TRADE_TYPE)
        if option is None:
            raise CollectionError(
                f"거래유형 필터에서 {self.TRADE_TYPE} 항목을 찾지 못했습니다."
            )
        if not self._filter_label_checked(option):
            option.click()
            page.wait_for_timeout(400)

        # Leaving this popover open makes later scrolling move the menu rather
        # than the listing list, and the list only refreshes once it closes.
        self._close_filter_popover(page, self._trade_filter_chip(page))

        # The header count is what the rest of the scan is measured against, so
        # do not move on until it actually shows the sale-only list.
        sale = tabs.get(self.TRADE_TYPE, 0)
        self._wait_for_list_card_count(page, sale, f"거래유형 {self.TRADE_TYPE}")

    def _trade_filter_chip(self, page):
        """The trade-type filter chip.

        Its label is whatever is selected, so it reads 전체거래유형, or 매매, or
        a list such as "전세, 월세". Match on that shape rather than on a fixed
        set of names.
        """

        def matches(label: str) -> bool:
            if label == self.ALL_TRADE_TYPES_LABEL:
                return True
            parts = [part.strip() for part in label.split(",") if part.strip()]
            return bool(parts) and all(part in self.TRADE_TYPE_NAMES for part in parts)

        return self._filter_chip(page, matches)

    def _area_filter_chip(self, page):
        """The exclusive-area chip; its label becomes the selection once made."""
        return self._filter_chip(
            page, lambda label: "면적" in label or "㎡" in label
        )

    def _open_filter_popover(self, page, chip, what: str) -> None:
        """Click a filter chip and wait for its options to render.

        A fixed pause here was not enough: the options arrive a moment later,
        and another popover may still be closing over them.
        """
        for _ in range(3):
            if self._filter_popover_open(page):
                return
            chip.click()
            for _ in range(10):
                page.wait_for_timeout(300)
                if self._filter_popover_open(page):
                    return
        raise CollectionError(f"{what} 필터 팝오버가 열리지 않았습니다.")

    def _filter_popover_open(self, page) -> bool:
        return (
            self._first_visible(
                page.locator('label[class*="CheckboxLayer"]'), min_size=8
            )
            is not None
        )

    def _close_filter_popover(self, page, chip) -> None:
        """Close an open filter popover.

        This matters twice over: an open popover swallows the scrolling meant
        for the listing list, and the results only refresh once it closes.
        """
        if chip is not None and self._filter_popover_open(page):
            chip.click()
            page.wait_for_timeout(500)

    def _wait_for_list_card_count(self, page, expected: int, what: str) -> None:
        """Wait for the header to show the count a filter should have produced.

        Sampling for a steady value instead would settle on the pre-filter
        count whenever the refresh is slower than the sampling window.
        """
        count = -1
        for _ in range(22):
            count = self._list_card_count(page)
            if count == expected:
                return
            page.wait_for_timeout(700)
        raise CollectionError(
            f"{what} 필터 후 목록이 {expected}건으로 갱신되지 않았습니다 (현재 {count}건)."
        )

    @staticmethod
    def _filter_chip(page, matches):
        """One of the filter chips above the listing list.

        These chips expose no accessible name a role lookup can match -- their
        text lives in a nested span -- so they are located by that rendered
        text. The 매매65 summary tab is excluded by the chip class: it carries
        its count, while the chip does not.
        """
        chips = page.locator('button[class*="ChipsItem"]')
        for index in range(chips.count()):
            chip = chips.nth(index)
            if not chip.is_visible():
                continue
            if matches((chip.inner_text() or "").strip()):
                return chip
        return None

    def _filter_option(self, page, name: str):
        """One option inside an open filter popover.

        Naver builds these as a label wrapping a hidden control, but falls back
        to plain buttons in places; skip the chip that opened the popover, which
        carries the same text once it is the current selection.
        """
        pattern = re.compile(rf"^{re.escape(name)}$")
        for selector in ('label[class*="CheckboxLayer"]', "label"):
            option = self._first_visible(
                page.locator(selector).filter(has_text=pattern), min_size=8
            )
            if option is not None:
                return option
        buttons = page.locator("button").filter(has_text=pattern)
        for index in range(buttons.count()):
            candidate = buttons.nth(index)
            if not candidate.is_visible():
                continue
            if candidate.get_attribute("aria-expanded") is not None:
                continue
            box = candidate.bounding_box()
            if not box or box["width"] < 8 or box["height"] < 8:
                continue
            return candidate
        return None

    def _select_similar_exclusive_area(self, page, minimum: float, maximum: float) -> None:
        """Leave only the area groups whose exclusive area is in range.

        "전체면적" means every group is checked, so narrowing is a matter of
        unchecking the ones outside the range -- selecting the ones inside it
        changes nothing, which is why an earlier version applied no filter at
        all while reporting success.
        """
        button = self._area_filter_chip(page)
        if button is None:
            raise CollectionError("매물 화면에서 전체면적 필터를 찾지 못했습니다.")
        self._open_filter_popover(page, button, "전용면적")

        # Not every complex offers similar-area grouping; when it is there,
        # turn it on so one click covers a whole 평형.
        grouping = self._first_visible(
            page.locator("button").filter(has_text=re.compile(r"^유사면적 묶기$"))
        )
        if grouping is not None and "checked" not in (grouping.get_attribute("class") or ""):
            grouping.click()
            page.wait_for_timeout(300)

        # Clicking rerenders the popover, so re-read it every round and fix the
        # first option that is in the wrong state. The loop ends only when every
        # option already matches the range, which is the verification.
        wanted_seen = False
        for _ in range(3 * self.MAX_AREA_OPTIONS):
            options = page.locator('label[class*="CheckboxLayer"]')
            wrong = None
            wanted_seen = False
            for index in range(options.count()):
                option = options.nth(index)
                if not option.is_visible():
                    continue
                text = " ".join((option.inner_text() or "").split())
                wanted = _area_option_wanted(text, minimum, maximum)
                if wanted is None:
                    continue
                wanted_seen = wanted_seen or wanted
                if self._filter_label_checked(option) != wanted:
                    wrong = option
                    break
            if wrong is None:
                break
            wrong.click()
            page.wait_for_timeout(300)
        else:
            raise CollectionError("전용면적 필터 선택이 끝나지 않았습니다.")
        if not wanted_seen:
            raise CollectionError(
                f"괄호 안 전용면적 {minimum:g}~{maximum:g}㎡ 항목을 찾지 못했습니다."
            )

        # This is a multi-select popover; close it so later scrolling reaches
        # the listing list and the results refresh.
        self._close_filter_popover(page, button)

    @staticmethod
    def _list_card_count(page) -> int:
        """Read the listing pane's own count for the filters now applied."""
        text = page.evaluate(
            r"""() => {
                const title = document.querySelector(
                    '[class*="ArticleListWrapper"][class*="title"]');
                const pane = document.querySelector('#complex_detail');
                return ((title || pane || document.body).innerText || '')
                    .replace(/\s+/g, ' ').trim();
            }"""
        )
        match = LIST_COUNT_RE.search(text)
        if not match:
            raise CollectionError(
                f"매물 목록 헤더에서 '매물 N개' 표시를 찾지 못했습니다: {text[:120]}"
            )
        return int(match.group(1).replace(",", ""))

    def _settled_list_card_count(self, page) -> int:
        """Wait for that count to stop moving; the list refreshes asynchronously."""
        previous = -1
        stable = 0
        for _ in range(22):
            count = self._list_card_count(page)
            stable = stable + 1 if count == previous else 0
            if stable >= 2:
                return count
            previous = count
            page.wait_for_timeout(700)
        return previous

    @staticmethod
    def _trade_tab_counts(page) -> dict[str, int]:
        """The complex's own card count per trade type, kept as a cross-check.

        These tabs count cards rather than articles: a unit several agents
        registered is bundled into one card and counted once.
        """
        texts = page.evaluate(
            r"""() => {
                const pane = document.querySelector('#complex_detail') || document.body;
                return [...pane.querySelectorAll('button')]
                    .filter(button => button.getClientRects().length > 0)
                    .map(button => (button.innerText || '').replace(/\s+/g, ' ').trim());
            }"""
        )
        counts: dict[str, int] = {}
        for text in texts:
            match = TRADE_COUNT_RE.match(text)
            if match:
                counts[match.group(1)] = int(match.group(2).replace(",", ""))
        if not counts:
            raise CollectionError(
                "단지 화면에서 매매·전세·월세·단기 매물 개수를 읽지 못했습니다."
            )
        return counts

    @staticmethod
    def _visible_listing_rows(page) -> list[dict]:
        """Capture every rendered card, expanded bundles included.

        Expanded cards used to be skipped here because their rows had been
        captured once, at the moment of the click. That made a capture taken
        before the bundle finished rendering permanent, which is how listings
        went missing. They are read again on every pass and merged instead.
        """
        return page.evaluate(
            "() => {"
            + _CARD_HELPERS_JS
            + """
            return collectCards()
                .filter(card => card.getClientRects().length > 0)
                .map(card => ({
                    articles: cardArticles(card),
                    text: (card.innerText || '').trim()
                }));
            }"""
        )

    @staticmethod
    def _scroll_listing_to_top(page) -> None:
        page.evaluate(
            """() => {
                const pane = document.querySelector('#complex_detail');
                if (!pane) {
                    window.scrollTo(0, 0);
                    return;
                }
                pane.scrollTop = 0;
                pane.dispatchEvent(new Event('scroll', {bubbles: true}));
            }"""
        )
        page.wait_for_timeout(700)

    @staticmethod
    def _listing_scroll_state(page) -> dict:
        return page.evaluate(
            """() => {
                const pane = document.querySelector('#complex_detail');
                if (!pane) {
                    return {
                        at_bottom: window.scrollY + window.innerHeight
                            >= document.body.scrollHeight - 4,
                        height: document.body.scrollHeight
                    };
                }
                return {
                    at_bottom: pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 4,
                    height: pane.scrollHeight
                };
            }"""
        )

    @staticmethod
    def _scroll_listing_view(page) -> dict:
        """Advance the listing pane and report whether the list is exhausted.

        Scrolls the pane itself rather than whichever element happens to sit
        under the mouse, and overlaps each step so a card taller than one step
        cannot fall between two viewports.
        """
        return page.evaluate(
            """() => {
                const pane = document.querySelector('#complex_detail');
                if (!pane || pane.scrollHeight <= pane.clientHeight + 20) {
                    const before = window.scrollY;
                    window.scrollBy(0, Math.max(400, Math.floor(window.innerHeight * 0.6)));
                    return {
                        moved: window.scrollY > before,
                        at_bottom: window.scrollY + window.innerHeight
                            >= document.body.scrollHeight - 4,
                        height: document.body.scrollHeight
                    };
                }
                const before = pane.scrollTop;
                pane.scrollTop = Math.min(
                    pane.scrollHeight - pane.clientHeight,
                    before + Math.max(400, Math.floor(pane.clientHeight * 0.6))
                );
                pane.dispatchEvent(new Event('scroll', {bubbles: true}));
                return {
                    moved: pane.scrollTop > before,
                    at_bottom: pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 4,
                    height: pane.scrollHeight
                };
            }"""
        )

    def _expand_listing_groups(self, page) -> list[dict]:
        """Open bundles and capture their rows only once every row has rendered."""
        rows: list[dict] = []
        for _ in range(self.MAX_LISTINGS_PER_COMPLEX):
            # Find the button, its owning card and invoke the click atomically.
            # React replaces this part of the DOM as bundles expand, so holding
            # a Locator across separate find/scroll/click calls races that render.
            card_handle = page.evaluate_handle(
                "() => {"
                + _CARD_HELPERS_JS
                + """
                const card = collectCards().find(item =>
                    [...item.querySelectorAll('button')].some(button =>
                        (button.textContent || '').trim() === '매물목록 펼치기' &&
                        button.getClientRects().length > 0));
                if (!card) return null;
                const button = [...card.querySelectorAll('button')].find(item =>
                    (item.textContent || '').trim() === '매물목록 펼치기');
                // Naver's sticky filter header can cover the button after
                // scrolling. Calling the same visible control's handler avoids
                // pointer interception by that fixed overlay.
                button.click();
                return card;
                }"""
            ).as_element()
            if card_handle is None:
                break
            rows.append(
                {
                    "articles": self._settled_bundle_articles(page, card_handle),
                    "text": (card_handle.inner_text() or "").strip(),
                }
            )
        remaining = page.evaluate(
            """() => [...document.querySelectorAll('button')].some(element =>
                (element.textContent || '').trim() === '매물목록 펼치기' &&
                element.getClientRects().length > 0)"""
        )
        if remaining:
            raise CollectionError(
                "매물목록 펼치기가 비정상적으로 많이 반복되어 수집을 중단했습니다."
            )
        return rows

    @staticmethod
    def _settled_bundle_articles(page, card_handle) -> list[dict]:
        """Wait until an expanded bundle has rendered all of its agent rows.

        Returning as soon as the first /articles/ link appeared was the main
        source of missing listings: a bundle renders its rows one after another.
        The card says how many agents registered the unit, so wait for exactly
        that many distinct article numbers rather than for a fixed delay.

        Counting anchors would not do: a partner row adds a second link, such as
        /articles/2646568041/out-link-bridge, to an article already counted.
        """
        match = AGENT_COUNT_RE.search(card_handle.inner_text() or "")
        expected = int(match.group(1)) if match else None
        stable = 0
        count = 0
        articles: list[dict] = []
        for _ in range(32):
            articles = card_handle.evaluate(
                "card => {" + _CARD_HELPERS_JS + " return cardArticles(card);}"
            )
            numbers = {_extract_listing_id(article["href"]) for article in articles}
            numbers.discard("")
            if expected is not None:
                if len(numbers) >= expected:
                    return articles
            else:
                # No agent count on this card: settle on an unchanging row count.
                stable = stable + 1 if numbers and len(numbers) == count else 0
                if stable >= 3:
                    return articles
            count = len(numbers)
            page.wait_for_timeout(250)
        summary = " ".join((card_handle.inner_text() or "").split())[:160]
        raise CollectionError(
            f"매물목록을 펼쳤지만 매물 {expected}건 중 {count}건만 나타났습니다: {summary}"
        )

    def _reset_exclusive_area_filter(self, page) -> None:
        """Reset Naver's SPA-persisted area selection to the unfiltered list."""
        button = self._area_filter_chip(page)
        if button is None:
            raise CollectionError("매물 화면에서 전체면적 필터를 찾지 못했습니다.")
        self._open_filter_popover(page, button, "전용면적")
        all_label = self._first_visible(
            page.locator("label").filter(has_text=re.compile(r"^전체면적"))
        )
        if all_label is None:
            raise CollectionError("면적 필터에서 전체면적 선택 항목을 찾지 못했습니다.")
        if not self._filter_label_checked(all_label):
            all_label.click()
            page.wait_for_timeout(500)
        self._close_filter_popover(page, button)
        page.wait_for_timeout(900)

    @staticmethod
    def _filter_label_checked(label) -> bool:
        """Read the real form control state; Naver no longer always marks labels."""
        control = label.locator("input")
        if control.count():
            return control.first.is_checked()
        classes = label.get_attribute("class") or ""
        return "is-checked" in classes or label.get_attribute("aria-checked") == "true"

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


def _area_option_wanted(text: str, minimum: float, maximum: float) -> bool | None:
    """Whether one area option belongs in range, or None when it is not one.

    Naver labels these as supply area with the exclusive area in parentheses,
    e.g. "115㎡ (84)1,011세대", and groups several sizes as "145~146㎡ (110~111)".
    A group counts as wanted when any of its exclusive areas is in range.
    """
    if text.startswith("전체면적"):
        return None
    match = re.search(r"\(([\d.~\s]+)\)", text)
    if not match:
        return None
    areas = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", match.group(1))]
    if not areas:
        return None
    return any(minimum <= area <= maximum for area in areas)


def _merge_article_rows(groups: list[dict], row: dict) -> None:
    """Fold one captured card into the cards collected so far.

    The same card is read on every scroll pass, and an expanded bundle may have
    been captured before all of its rows rendered. Article numbers are unique
    across Naver, so two captures sharing one describe the same card; the union
    keeps the cheapest listing findable even when a pass saw only part of the
    bundle. Cards are not keyed by their text: two different listings can print
    exactly the same building, price, area, floor and direction.
    """
    numbers = {_extract_listing_id(article.get("href", "")) for article in row["articles"]}
    numbers.discard("")
    if not numbers:
        # A card with no article link at all; its text is all we can key on.
        if any(not group["numbers"] and group["text"] == row["text"] for group in groups):
            return
        groups.append({"numbers": set(), "articles": {}, "text": row["text"]})
        return

    matched = [group for group in groups if group["numbers"] & numbers]
    if not matched:
        target = {"numbers": set(), "articles": {}, "text": ""}
        groups.append(target)
    else:
        target = matched[0]
        for other in matched[1:]:
            target["numbers"] |= other["numbers"]
            target["articles"].update(other["articles"])
            if len(other["text"]) > len(target["text"]):
                target["text"] = other["text"]
            groups.remove(other)

    target["numbers"] |= numbers
    for article in row["articles"]:
        current = target["articles"].get(article["href"])
        if current is None or len(article["text"]) > len(current["text"]):
            target["articles"][article["href"]] = article
    # An expanded card carries more text than its collapsed shell.
    if len(row["text"]) > len(target["text"]):
        target["text"] = row["text"]


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
