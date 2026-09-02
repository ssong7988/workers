from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from real_estate_finder.config import load_config, validate_config
from real_estate_finder.collector import (
    AGENT_COUNT_RE,
    LIST_COUNT_RE,
    TRADE_COUNT_RE,
    NaverBrowserCollector,
    _area_option_wanted,
    _merge_article_rows,
    _parse_favorite_listing_text,
    _pick_representative_article,
)
from real_estate_finder.models import Listing, LowFloorRule, SearchCondition
from real_estate_finder.notifier import batch_listing_message
from real_estate_finder.parsing import (
    explain_condition,
    matches_condition,
    parse_floor,
    parse_price_won,
)
from real_estate_finder.storage import FileStore


RULE = LowFloorRule()
CONDITION = SearchCondition(
    id="test",
    name="위버필드 84",
    complex_names=("위버필드",),
    search_url="https://new.land.naver.com/complexes/1",
    exclusive_area_m2=84,
    allowed_types=None,
    max_price_won=2_600_000_000,
    urgent_price_won=2_500_000_000,
)


def listing(
    price: int,
    floor_text: str = "10/30층",
    type_name: str = "84A",
    area: float = 84.94,
) -> Listing:
    return Listing(
        condition_id="test",
        listing_id=f"{price}-{floor_text}",
        complex_name="과천 위버필드",
        type_name=type_name,
        exclusive_area_m2=area,
        price_won=price,
        floor_text=floor_text,
        floor=None,
        direction="남향",
        description="",
        url="https://fin.land.naver.com/articles/1",
        observed_at="2026-09-02T08:00:00+09:00",
    )


class PriceParsingTests(unittest.TestCase):
    def test_korean_prices(self) -> None:
        self.assertEqual(parse_price_won("25억"), 2_500_000_000)
        self.assertEqual(parse_price_won("24억 5,000"), 2_450_000_000)
        self.assertEqual(parse_price_won("255,000만원"), 2_550_000_000)

    def test_favorite_listing_card(self) -> None:
        parsed = _parse_favorite_listing_text(
            """래미안과천센트럴스위트 707동
            매매 24억 5,000
            아파트
            116A㎡ (전용84.94A)
            2/25층
            남동향
            확인매물 2026.09.01""",
            "2647012635",
            "래미안과천센트럴스위트",
            "/articles/2647012635",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price_won"], 2_450_000_000)
        self.assertEqual(parsed["exclusive_area_m2"], 84.94)
        self.assertEqual(parsed["type_name"], "84.94A")
        self.assertEqual(parsed["floor_text"], "2/25층")
        self.assertEqual(parsed["direction"], "남동향")


class FloorTests(unittest.TestCase):
    def test_low_floor_variants(self) -> None:
        for text in ("1층", "2/30층", "3층", "저/25층", "저층"):
            with self.subTest(text=text):
                self.assertTrue(parse_floor(text, RULE)[1])

    def test_normal_floor_variants(self) -> None:
        for text in ("4층", "중층", "고층", "10/30층"):
            with self.subTest(text=text):
                floor, low, known = parse_floor(text, RULE)
                self.assertTrue(known)
                self.assertFalse(low)

    def test_building_height_is_not_the_listing_floor(self) -> None:
        """"중/23층" is a middle floor of a 23-storey building, not floor 23."""
        for text in ("중/23층", "고/25층", "저/20층"):
            with self.subTest(text=text):
                floor, _low, known = parse_floor(text, RULE)
                self.assertTrue(known)
                self.assertIsNone(floor)

    def test_numbered_floor_ignores_building_height(self) -> None:
        self.assertEqual(parse_floor("9/23층", RULE)[0], 9)
        self.assertEqual(parse_floor("21/25층", RULE)[0], 21)

    def test_unknown_floor(self) -> None:
        self.assertEqual(parse_floor("정보없음", RULE), (None, False, False))


class FavoriteCountTests(unittest.TestCase):
    """Naver splits the number and its unit into separate elements."""

    def _count(self, text: str):
        match = NaverBrowserCollector.FAVORITE_COUNT_RE.search(text)
        return int(match.group(1)) if match else None

    def test_reads_count_across_layouts(self) -> None:
        for text, expected in (
            ("총 6개", 6),
            ("단지\n총 6\n개\n래미안", 6),  # what innerText actually returns
            ("총12개", 12),
            ("총  30  개", 30),
        ):
            with self.subTest(text=text):
                self.assertEqual(self._count(text), expected)

    def test_no_count_present(self) -> None:
        self.assertIsNone(self._count("최근조회\n래미안과천센트럴스위트"))


class RepresentativeArticleTests(unittest.TestCase):
    def test_picks_the_cheapest_of_a_bundle(self) -> None:
        listing_id, href = _pick_representative_article(
            [
                {"href": "/articles/2647101276", "text": "매매 25억"},
                {"href": "/articles/2646599402", "text": "매매 24억 5,000"},
                {"href": "/articles/2645262271", "text": "매매 26억"},
            ]
        )
        self.assertEqual(listing_id, "2646599402")
        self.assertEqual(href, "/articles/2646599402")

    def test_same_price_picks_the_newest_article(self) -> None:
        listing_id, href = _pick_representative_article(
            [
                {"href": "/articles/2645262271", "text": "매매 25억"},
                {"href": "/articles/2647101276", "text": "매매 25억"},
                {"href": "/articles/2646599402", "text": "매매 25억"},
            ]
        )
        self.assertEqual(listing_id, "2647101276")
        self.assertEqual(href, "/articles/2647101276")

    def test_single_link(self) -> None:
        self.assertEqual(
            _pick_representative_article(
                [{"href": "/articles/2647057443", "text": "매매 22억 5,000"}]
            ),
            ("2647057443", "/articles/2647057443"),
        )

    def test_unpriced_links_fall_back_to_newest(self) -> None:
        self.assertEqual(
            _pick_representative_article(
                [
                    {"href": "/articles/2647057443", "text": "매물 보러가기"},
                    {"href": "/articles/2647055564", "text": "매물 보러가기"},
                ]
            ),
            ("2647057443", "/articles/2647057443"),
        )

    def test_no_article_link(self) -> None:
        self.assertEqual(_pick_representative_article([]), ("", ""))
        self.assertEqual(
            _pick_representative_article(
                [{"href": "/complexes/104517?tab=article", "text": "매매 16억"}]
            ),
            ("", ""),
        )


class ScreenCountTests(unittest.TestCase):
    """The screen states how much there is to collect; both counts are used."""

    def _total(self, texts) -> int | None:
        total = None
        for text in texts:
            match = TRADE_COUNT_RE.match(text)
            if match:
                total = (total or 0) + int(match.group(2).replace(",", ""))
        return total

    def test_trade_tab_counts_add_up(self) -> None:
        # innerText collapsed onto one line, as _expected_card_count reads it.
        self.assertEqual(self._total(["매매 9", "전세 0", "월세 1", "단기 0"]), 10)
        self.assertEqual(self._total(["매매9", "전세 1,024"]), 1_033)

    def test_other_buttons_are_not_counted(self) -> None:
        self.assertIsNone(
            self._total(
                ["전체거래유형", "가격", "전체면적", "매매 15억 2,000", "단지정보"]
            )
        )

    def test_bundle_agent_count(self) -> None:
        match = AGENT_COUNT_RE.search(
            "광교푸르지오월드마크(주상복합) 101동\n매매 15억 2,000\n"
            "중개사 4곳에서 등록했어요\n매물목록 펼치기"
        )
        self.assertEqual(int(match.group(1)), 4)

    def test_standalone_card_has_no_agent_count(self) -> None:
        self.assertIsNone(
            AGENT_COUNT_RE.search("관심매물\n매매 17억 5,000\n저/48층남서향")
        )


class AreaOptionTests(unittest.TestCase):
    """Naver prints supply area with the exclusive area in parentheses."""

    def _wanted(self, text: str):
        return _area_option_wanted(text, 80, 86)

    def test_group_inside_the_range_is_kept(self) -> None:
        self.assertIs(self._wanted("115㎡ (84)1,011세대"), True)
        self.assertIs(self._wanted("116~118㎡ (84~85)320세대"), True)

    def test_group_outside_the_range_is_cleared(self) -> None:
        for text in ("59㎡ (35)62세대", "87~88㎡ (59)746세대", "145~146㎡ (110~111)113세대"):
            with self.subTest(text=text):
                self.assertIs(self._wanted(text), False)

    def test_rows_that_are_not_area_options(self) -> None:
        """전체면적 selects everything, so it must never be toggled here."""
        for text in ("전체면적2,128세대", "랭킹순", "가격순"):
            with self.subTest(text=text):
                self.assertIsNone(self._wanted(text))


class ListCountTests(unittest.TestCase):
    """The listing header counts what the screen filters left, so it decides
    when a complex has been read completely."""

    def _count(self, text: str):
        match = LIST_COUNT_RE.search(text)
        return int(match.group(1).replace(",", "")) if match else None

    def test_reads_the_header_count(self) -> None:
        # innerText, as _list_card_count reads it.
        self.assertEqual(self._count("매물\n83\n개\n도움말 보기"), 83)
        self.assertEqual(self._count("매물 83 개 도움말 보기 랭킹순"), 83)
        self.assertEqual(self._count("매물 1,024개"), 1_024)

    def test_ignores_the_agency_advertisement(self) -> None:
        """The ad above the list says "단지 보유 매물 16개"; that is not the count."""
        self.assertIsNone(self._count("최우수모범중개업소 안전중개 단지 보유 매물 16 개"))
        self.assertEqual(
            self._count("단지 보유 매물 16 개 매물 83 개 도움말 보기"), 83
        )

    def test_no_count_present(self) -> None:
        self.assertIsNone(self._count("매물이 없습니다"))


class MergeArticleRowsTests(unittest.TestCase):
    """A bundle read while it was still rendering must not stay half-read."""

    @staticmethod
    def _row(articles, text="카드"):
        return {
            "articles": [{"href": href, "text": row} for href, row in articles],
            "text": text,
        }

    def test_partial_capture_completes_on_the_next_pass(self) -> None:
        groups: list[dict] = []
        _merge_article_rows(
            groups,
            self._row(
                [("/articles/2647076004", "매매 16억"), ("/articles/2646624166", "매매 15억 5,000")],
                text="101동 매매 15억 2,000",
            ),
        )
        _merge_article_rows(
            groups,
            self._row(
                [
                    ("/articles/2647076004", "매매 16억"),
                    ("/articles/2646624166", "매매 15억 5,000"),
                    ("/articles/2643998292", "매매 15억 2,000"),
                    ("/articles/2643743247", "매매 15억 8,000"),
                ],
                text="101동 매매 15억 2,000 펼쳐진 전체 본문",
            ),
        )
        self.assertEqual(len(groups), 1)
        articles = list(groups[0]["articles"].values())
        self.assertEqual(len(articles), 4)
        # The cheapest listing only becomes reachable once the card is complete.
        self.assertEqual(_pick_representative_article(articles)[0], "2643998292")
        # The expanded card carries the fuller text; keep it.
        self.assertIn("펼쳐진", groups[0]["text"])

    def test_identical_looking_cards_stay_separate(self) -> None:
        """Two real listings print the same building, price, floor and aspect."""
        same = "101동 매매 17억 5,000 전용108.13A 저/48층 남서향"
        groups: list[dict] = []
        _merge_article_rows(groups, self._row([("/articles/2644394081", same)], text=same))
        _merge_article_rows(groups, self._row([("/articles/2642556613", same)], text=same))
        self.assertEqual(len(groups), 2)

    def test_partner_link_is_the_same_listing(self) -> None:
        groups: list[dict] = []
        _merge_article_rows(
            groups,
            self._row(
                [
                    ("/articles/2646568041", "매매 21억 5,000"),
                    ("/articles/2646568041/out-link-bridge?cpId=asil", "매물 보러가기"),
                ]
            ),
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["numbers"], {"2646568041"})
        self.assertEqual(
            _pick_representative_article(list(groups[0]["articles"].values()))[0],
            "2646568041",
        )

    def test_card_without_any_article_link_is_kept_once(self) -> None:
        groups: list[dict] = []
        for _ in range(3):
            _merge_article_rows(groups, self._row([], text="매매 22억 전용84.94A"))
        self.assertEqual(len(groups), 1)


class ExplainConditionTests(unittest.TestCase):
    """Exclusion reasons must stay in step with matches_condition."""

    def test_reason_matches_the_boolean(self) -> None:
        for item in (
            listing(2_400_000_000),
            listing(2_700_000_000),
            listing(2_400_000_000, area=59.9),
            listing(2_400_000_000, "미상"),
        ):
            with self.subTest(price=item.price_won, area=item.exclusive_area_m2):
                reason = explain_condition(item, CONDITION, RULE)
                self.assertEqual(reason is None, matches_condition(item, CONDITION, RULE))

    def test_passing_listing_has_no_reason(self) -> None:
        self.assertIsNone(explain_condition(listing(2_400_000_000), CONDITION, RULE))

    def test_area_reasons(self) -> None:
        self.assertIn("면적 미달", explain_condition(listing(2_400_000_000, area=59.9), CONDITION, RULE))
        self.assertIn("면적 초과", explain_condition(listing(2_400_000_000, area=118.9), CONDITION, RULE))

    def test_price_reason_names_the_low_floor_cap(self) -> None:
        reason = explain_condition(listing(2_550_000_000, "2/25층"), CONDITION, RULE)
        self.assertIn("가격 초과", reason)
        self.assertIn("저층기준", reason)

    def test_unknown_floor_reason(self) -> None:
        self.assertIn("층 해석 실패", explain_condition(listing(2_400_000_000, "미상"), CONDITION, RULE))


class FilteringTests(unittest.TestCase):
    def test_84_group_accepts_exclusive_area_83_through_86(self) -> None:
        for area in (83.0, 84.94, 86.0):
            with self.subTest(area=area):
                self.assertTrue(matches_condition(listing(2_500_000_000, area=area), CONDITION, RULE))
        self.assertFalse(matches_condition(listing(2_500_000_000, area=82.99), CONDITION, RULE))
        self.assertFalse(matches_condition(listing(2_500_000_000, area=86.01), CONDITION, RULE))

    def test_normal_and_low_floor_thresholds(self) -> None:
        normal = listing(2_600_000_000)
        self.assertTrue(matches_condition(normal, CONDITION, RULE))
        self.assertEqual(normal.effective_urgent_price_won, 2_500_000_000)

        low_pass = listing(2_500_000_000, "3층")
        self.assertTrue(matches_condition(low_pass, CONDITION, RULE))
        self.assertEqual(low_pass.effective_urgent_price_won, 2_400_000_000)

        low_fail = listing(2_500_010_000, "저층")
        self.assertFalse(matches_condition(low_fail, CONDITION, RULE))

    def test_unknown_floor_excluded(self) -> None:
        self.assertFalse(matches_condition(listing(2_000_000_000, "미상"), CONDITION, RULE))

    def test_batch_message_limit(self) -> None:
        items = [(listing(2_400_000_000 + index * 10_000), index % 2 == 0, index % 2 == 1) for index in range(30)]
        message = batch_listing_message(items)
        self.assertLessEqual(len(message), 200)
        self.assertIn("매물 알림 30건", message)


class StorageTests(unittest.TestCase):
    def test_atomic_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            state = {"listings": {"a": {"active": True}}, "last_successful_scan": "now"}
            store.save_state(state)
            self.assertEqual(store.load_state(), state)
            with store.run_lock():
                self.assertTrue(store.lock_path.exists())
            self.assertFalse(store.lock_path.exists())


class ConfigTests(unittest.TestCase):
    def test_project_config(self) -> None:
        path = Path(__file__).parents[1] / "config" / "searches.yaml"
        config = load_config(path)
        validate_config(config)
        self.assertEqual(len(config.searches), 6)
        worldmark = config.searches[-1]
        self.assertTrue(worldmark.notify_new)
        self.assertEqual(worldmark.exclusive_area_m2, 84)
        self.assertEqual(worldmark.exclusive_area_min_m2, 84)
        self.assertEqual(worldmark.exclusive_area_max_m2, 85.999)
        self.assertIsNone(worldmark.max_price_won)
        self.assertIsNone(worldmark.urgent_price_won)
        worldmark_84 = listing(3_000_000_000, area=84.91)
        worldmark_84.complex_name = "광교푸르지오월드마크(주상복합)"
        self.assertTrue(matches_condition(worldmark_84, worldmark, config.low_floor))
        worldmark_106 = listing(1_000_000_000, area=106.47)
        worldmark_106.complex_name = "광교푸르지오월드마크(주상복합)"
        self.assertFalse(matches_condition(worldmark_106, worldmark, config.low_floor))
        sur = config.searches[-3]
        eco = config.searches[-2]
        self.assertTrue(sur.apply_low_floor_discount)
        self.assertEqual(eco.max_price_won, 2_250_000_000)
        self.assertEqual(eco.urgent_price_won, 2_150_000_000)
        self.assertTrue(eco.apply_low_floor_discount)


if __name__ == "__main__":
    unittest.main()
