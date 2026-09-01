from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from real_estate_finder.models import AppConfig, Listing, LowFloorRule, SearchCondition
from real_estate_finder.notifier import KakaoNotifier
from real_estate_finder.service import FinderService
from real_estate_finder.storage import FileStore


CONDITION = SearchCondition(
    id="weverfield",
    name="위버필드",
    complex_names=("위버필드",),
    search_url="https://new.land.naver.com/complexes/1",
    exclusive_area_m2=84,
    allowed_types=None,
    max_price_won=2_600_000_000,
    urgent_price_won=2_500_000_000,
)
CONFIG = AppConfig("sale", LowFloorRule(), (CONDITION,))


def make_listing(price: int) -> Listing:
    return Listing(
        condition_id="weverfield",
        listing_id="123",
        complex_name="과천 위버필드",
        type_name="84A",
        exclusive_area_m2=84.9,
        price_won=price,
        floor_text="10/30층",
        floor=10,
        direction="남향",
        description="",
        url="https://fin.land.naver.com/articles/123",
        observed_at="2026-09-02T09:00:00+09:00",
    )


class FakeCollector:
    def __init__(self, item: Listing) -> None:
        self.item = item

    def collect_all(self, _conditions):
        return {"weverfield": [self.item]}


class ServiceTests(unittest.TestCase):
    def test_first_urgent_and_further_drop_only(self) -> None:
        sent: list[str] = []
        notifier = KakaoNotifier(Path("."), sender=lambda message, _url: sent.append(message))
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            first = FinderService(CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier)
            result = first.scan()
            self.assertEqual(len(result.urgent), 1)
            self.assertEqual(len(sent), 1)

            same = FinderService(CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier)
            self.assertEqual(len(same.scan().urgent), 0)
            self.assertEqual(len(sent), 1)

            lower = FinderService(CONFIG, FakeCollector(make_listing(2_490_000_000)), store, notifier)
            self.assertEqual(len(lower.scan().urgent), 1)
            self.assertEqual(len(sent), 2)

    def test_smoke_does_not_consume_alert_history(self) -> None:
        sent: list[str] = []
        notifier = KakaoNotifier(Path("."), sender=lambda message, _url: sent.append(message))
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier)
            service.smoke_test()
            state = store.load_state()
            self.assertIsNone(state["listings"]["weverfield:123"]["last_urgent_alert_price_won"])
            self.assertEqual(len(sent), 2)


if __name__ == "__main__":
    unittest.main()
