from __future__ import annotations

import unittest

from real_estate_finder.card import render_card_html
from real_estate_finder.models import Listing
from real_estate_finder.notifier import card_caption, card_heading


REPORT_URL = "https://example.invalid/report"


def make_listing(index: int, price: int, complex_name: str = "과천위버필드") -> Listing:
    return Listing(
        condition_id="weverfield",
        listing_id=str(index),
        complex_name=complex_name,
        type_name="84A",
        exclusive_area_m2=84.9,
        price_won=price,
        floor_text=f"{index}/30층",
        floor=index,
        direction="남향",
        description="",
        url=f"https://fin.land.naver.com/articles/{index}",
        observed_at="2026-09-02T09:00:00+09:00",
        effective_max_price_won=2_600_000_000,
        effective_urgent_price_won=2_500_000_000,
    )


def render(items) -> str:
    return render_card_html(
        items,
        heading="오늘의 매물 알림",
        generated_at="2026.09.02 10:00",
        report_url=REPORT_URL,
    )


class CardHtmlTests(unittest.TestCase):
    def test_every_listing_survives(self) -> None:
        """The whole point of the card: nothing gets dropped to fit a limit."""
        items = [
            (make_listing(index, 2_400_000_000 + index * 1_000_000), False, False)
            for index in range(1, 21)
        ]
        html = render(items)
        for listing, _, _ in items:
            self.assertIn(f"{listing.floor}/30층", html)
        self.assertNotIn("외 ", html)

    def test_overflow_is_summarised(self) -> None:
        items = [
            (make_listing(index, 2_400_000_000), False, False) for index in range(1, 46)
        ]
        html = render_card_html(
            items,
            heading="오늘의 매물 알림",
            generated_at="2026.09.02 10:00",
            report_url=REPORT_URL,
            max_rows=40,
        )
        self.assertIn("외 5건", html)

    def test_scraped_text_is_escaped(self) -> None:
        listing = make_listing(1, 2_400_000_000, complex_name='<script>alert("x")</script>')
        html = render([(listing, False, False)])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_urgent_and_new_are_marked(self) -> None:
        items = [
            (make_listing(1, 2_400_000_000), True, False),
            (make_listing(2, 2_450_000_000), False, True),
            (make_listing(3, 2_460_000_000), False, False),
        ]
        html = render(items)
        self.assertIn('<span class="badge urgent">급매</span>', html)
        self.assertIn('<span class="badge new">신규</span>', html)
        self.assertIn('<div class="n">3</div><div class="k">확인 매물</div>', html)

    def test_grouped_by_complex(self) -> None:
        items = [
            (make_listing(1, 2_400_000_000, "과천위버필드"), False, False),
            (make_listing(2, 2_410_000_000, "래미안슈르"), False, False),
            (make_listing(3, 2_420_000_000, "과천위버필드"), False, False),
        ]
        html = render(items)
        self.assertIn("과천위버필드", html)
        self.assertIn("래미안슈르", html)
        self.assertIn("2건", html)  # 위버필드 grouped together
        self.assertIn("1건", html)

    def test_card_is_self_contained(self) -> None:
        """No external fonts, images or scripts — it must render offline."""
        html = render([(make_listing(1, 2_400_000_000), False, False)])
        for marker in ('src="http', "@import", "<script"):
            self.assertNotIn(marker, html)
        # The report URL appears as footer text only, never as a fetched resource.
        self.assertNotIn(f'href="{REPORT_URL}"', html)


class CaptionTests(unittest.TestCase):
    def test_heading_and_caption_fit_feed_limits(self) -> None:
        items = [
            (make_listing(index, 2_400_000_000 + index, f"아주긴단지이름{index}"), True, True)
            for index in range(1, 41)
        ]
        self.assertLessEqual(len(card_heading(items)), 180)
        self.assertLessEqual(len(card_caption(items)), 180)

    def test_heading_counts(self) -> None:
        items = [
            (make_listing(1, 2_400_000_000), True, False),
            (make_listing(2, 2_450_000_000), False, True),
        ]
        heading = card_heading(items)
        self.assertIn("2건", heading)
        self.assertIn("급매 1", heading)
        self.assertIn("신규 1", heading)

    def test_caption_reports_cheapest_and_scope(self) -> None:
        items = [
            (make_listing(1, 2_500_000_000, "과천위버필드"), False, False),
            (make_listing(2, 2_100_000_000, "래미안슈르"), False, False),
        ]
        caption = card_caption(items)
        self.assertIn("21억", caption)
        self.assertIn("외 1단지", caption)

    def test_empty_caption(self) -> None:
        self.assertEqual(card_caption([]), "")


if __name__ == "__main__":
    unittest.main()
