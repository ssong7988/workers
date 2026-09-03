from datetime import datetime
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone

from properties.card import render_card_html
from properties.models import Listing, SearchCondition
from properties.notifier import card_caption, card_heading


def make_listing(index: int, price: int, complex_name: str = "과천위버필드") -> Listing:
    observed = timezone.make_aware(datetime(2026, 9, 3, 9, 0))
    return Listing(
        condition=SearchCondition(id="weverfield", name="위버필드"),
        listing_id=str(index),
        complex_name=complex_name,
        type_name="84A",
        exclusive_area_m2=Decimal("84.900"),
        price_won=price,
        floor_text=f"{index}/30층",
        floor=index,
        direction="남향",
        description="",
        url=f"https://fin.land.naver.com/articles/{index}",
        observed_at=observed,
        first_seen_at=observed,
        last_seen_at=observed,
        effective_max_price_won=2_600_000_000,
        effective_urgent_price_won=2_500_000_000,
    )


class CardTests(SimpleTestCase):
    databases = set()

    def render(self, items, max_rows=40) -> str:
        return render_card_html(
            items,
            heading="오늘의 매물",
            generated_at="2026.09.03 09:00",
            report_url="https://example.invalid/report",
            max_rows=max_rows,
        )

    def test_card_escapes_groups_badges_and_decimal_area(self) -> None:
        items = [
            (make_listing(1, 2_400_000_000, '<script>alert("x")</script>'), True, False),
            (make_listing(2, 2_450_000_000), False, True),
            (make_listing(3, 2_460_000_000), False, False),
        ]
        html = self.render(items)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('<span class="badge urgent">급매</span>', html)
        self.assertIn('<span class="badge new">신규</span>', html)
        self.assertIn("전용 84.9㎡", html)
        self.assertIn("확인 매물", html)

    def test_card_summarizes_only_rows_beyond_limit(self) -> None:
        items = [
            (make_listing(index, 2_400_000_000), False, False)
            for index in range(1, 46)
        ]
        self.assertIn("외 5건", self.render(items))
        self.assertNotIn("외 ", self.render(items[:20]))

    def test_card_is_self_contained(self) -> None:
        html = self.render([(make_listing(1, 2_400_000_000), False, False)])
        for marker in ('src="http', "@import", "<script"):
            self.assertNotIn(marker, html)

    def test_heading_and_caption_keep_counts_and_limits(self) -> None:
        items = [
            (make_listing(index, 2_400_000_000 + index, f"긴단지{index}"), True, True)
            for index in range(1, 41)
        ]
        self.assertIn("급매 40", card_heading(items))
        self.assertIn("신규 40", card_heading(items))
        self.assertLessEqual(len(card_heading(items)), 180)
        self.assertLessEqual(len(card_caption(items)), 180)
