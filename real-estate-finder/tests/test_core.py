from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from real_estate_finder.config import load_config, validate_config
from real_estate_finder.collector import (
    NaverBrowserCollector,
    _parse_favorite_listing_text,
    _pick_representative_article,
)
from real_estate_finder.models import Listing, LowFloorRule, SearchCondition
from real_estate_finder.notifier import batch_listing_message, listing_message
from real_estate_finder.parsing import matches_condition, parse_floor, parse_price_won
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
    def test_picks_the_newest_of_a_bundle(self) -> None:
        listing_id, href = _pick_representative_article(
            ["/articles/2645262271", "/articles/2647101276", "/articles/2646599402"]
        )
        self.assertEqual(listing_id, "2647101276")
        self.assertEqual(href, "/articles/2647101276")

    def test_single_link(self) -> None:
        self.assertEqual(
            _pick_representative_article(["/articles/2647057443"]),
            ("2647057443", "/articles/2647057443"),
        )

    def test_no_article_link(self) -> None:
        self.assertEqual(_pick_representative_article([]), ("", ""))
        self.assertEqual(_pick_representative_article(["/complexes/104517?tab=article"]), ("", ""))


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

    def test_message_limit(self) -> None:
        item = listing(2_400_000_000, "3층")
        self.assertTrue(matches_condition(item, CONDITION, RULE))
        self.assertLessEqual(len(listing_message(item, urgent=True)), 200)

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
