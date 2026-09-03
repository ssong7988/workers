from __future__ import annotations

import unittest

from real_estate_finder.models import AppConfig, Listing, LowFloorRule, SearchCondition
from real_estate_finder.report import build_report_payload


CONDITION_A = SearchCondition(
    id="weverfield",
    name="위버필드",
    complex_names=("위버필드",),
    search_url="",
    exclusive_area_m2=84,
    allowed_types=None,
    max_price_won=2_600_000_000,
    urgent_price_won=2_500_000_000,
)
CONDITION_B = SearchCondition(
    id="worldmark",
    name="월드마크",
    complex_names=("월드마크",),
    search_url="",
    exclusive_area_m2=None,
    allowed_types=None,
    max_price_won=None,
    urgent_price_won=None,
)
CONFIG = AppConfig("sale", LowFloorRule(), (CONDITION_A, CONDITION_B))


def make_listing(
    *,
    condition_id: str = "weverfield",
    listing_id: str = "123",
    price_won: int = 2_550_000_000,
    url: str | None = None,
    urgent_price_won: int | None = 2_500_000_000,
) -> Listing:
    return Listing(
        condition_id=condition_id,
        listing_id=listing_id,
        complex_name="과천 위버필드",
        type_name="84A",
        exclusive_area_m2=84.9,
        price_won=price_won,
        floor_text="10/30층",
        floor=10,
        direction="남향",
        description="",
        url=url or f"https://fin.land.naver.com/articles/{listing_id}",
        observed_at="2026-09-02T09:00:00+09:00",
        effective_urgent_price_won=urgent_price_won,
    )


class BuildReportPayloadTests(unittest.TestCase):
    def test_only_direct_article_urls_are_included(self) -> None:
        article = make_listing(listing_id="111")
        complex_home = make_listing(
            listing_id="222", url="https://fin.land.naver.com/complexes/999"
        )
        non_numeric = make_listing(
            listing_id="A1", url="https://fin.land.naver.com/articles/A1"
        )
        payload = build_report_payload(
            [article, complex_home, non_numeric], CONFIG, observed_at="2026-09-02T09:00:00+09:00"
        )
        urls = [item["url"] for item in payload["complexes"][0]["listings"]]
        self.assertEqual(urls, [article.url])

    def test_groups_follow_config_order_and_skip_empty_conditions(self) -> None:
        weverfield = make_listing(condition_id="weverfield", listing_id="1")
        payload = build_report_payload(
            [weverfield], CONFIG, observed_at="2026-09-02T09:00:00+09:00"
        )
        # CONDITION_B (worldmark) has no listings and is omitted, not emitted empty.
        self.assertEqual([c["name"] for c in payload["complexes"]], ["과천 위버필드"])

    def test_listings_sort_by_price_then_newest_id_on_ties(self) -> None:
        cheap = make_listing(listing_id="1", price_won=2_400_000_000)
        expensive = make_listing(listing_id="2", price_won=2_500_000_000)
        tie_older = make_listing(listing_id="10", price_won=2_450_000_000)
        tie_newer = make_listing(listing_id="20", price_won=2_450_000_000)
        payload = build_report_payload(
            [expensive, tie_older, cheap, tie_newer],
            CONFIG,
            observed_at="2026-09-02T09:00:00+09:00",
        )
        prices = [item["price"] for item in payload["complexes"][0]["listings"]]
        self.assertEqual(prices, ["24억", "24억 5,000", "24억 5,000", "25억"])
        # Same price: the listing with the larger (newer) id sorts first.
        ordered_ids = [item["url"].rsplit("/", 1)[-1] for item in payload["complexes"][0]["listings"]]
        self.assertEqual(ordered_ids[1:3], ["20", "10"])

    def test_urgent_flag_matches_effective_threshold(self) -> None:
        urgent = make_listing(listing_id="1", price_won=2_400_000_000, urgent_price_won=2_500_000_000)
        not_urgent = make_listing(listing_id="2", price_won=2_550_000_000, urgent_price_won=2_500_000_000)
        no_threshold = make_listing(listing_id="3", price_won=1, urgent_price_won=None)
        payload = build_report_payload(
            [urgent, not_urgent, no_threshold], CONFIG, observed_at="2026-09-02T09:00:00+09:00"
        )
        flags = {item["url"].rsplit("/", 1)[-1]: item["urgent"] for item in payload["complexes"][0]["listings"]}
        self.assertEqual(flags, {"1": True, "2": False, "3": False})

    def test_observed_at_is_passed_through(self) -> None:
        payload = build_report_payload([], CONFIG, observed_at="2026-09-02T09:00:00+09:00")
        self.assertEqual(payload["observedAt"], "2026-09-02T09:00:00+09:00")
        self.assertEqual(payload["complexes"], [])


if __name__ == "__main__":
    unittest.main()
