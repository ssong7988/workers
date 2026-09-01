from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from real_estate_finder.config import load_config, validate_config
from real_estate_finder.models import Listing, LowFloorRule, SearchCondition
from real_estate_finder.notifier import listing_message
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


def listing(price: int, floor_text: str = "10/30층", type_name: str = "84A") -> Listing:
    return Listing(
        condition_id="test",
        listing_id=f"{price}-{floor_text}",
        complex_name="과천 위버필드",
        type_name=type_name,
        exclusive_area_m2=84.94,
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

    def test_unknown_floor(self) -> None:
        self.assertEqual(parse_floor("정보없음", RULE), (None, False, False))


class FilteringTests(unittest.TestCase):
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
        self.assertEqual(len(config.searches), 3)
        self.assertEqual(config.searches[-1].max_price_won, 2_600_000_000)
        self.assertEqual(config.searches[-1].urgent_price_won, 2_500_000_000)


if __name__ == "__main__":
    unittest.main()
