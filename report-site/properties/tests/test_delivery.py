from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from properties.delivery import DeliveryError, DeliveryService
from properties.models import (
    GlobalRule,
    Listing,
    NotificationFailure,
    Observation,
    Scan,
    SearchCondition,
)
from properties.notifier import KakaoNotifier


@override_settings(
    REPORT_PUBLIC_URL="https://example.com/r/token/",
    REPORT_STATS_URL="https://example.com/r/token/stats/",
)
class DeliveryTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create()
        self.condition = SearchCondition.objects.create(
            id="sample",
            name="샘플",
            complex_names=["샘플"],
            region="과천",
        )
        observed = timezone.make_aware(datetime(2026, 9, 3, 9, 0))
        self.listing = Listing.objects.create(
            condition=self.condition,
            listing_id="123",
            complex_name="샘플아파트",
            type_name="84A",
            exclusive_area_m2=Decimal("84.900"),
            price_won=2_400_000_000,
            floor_text="10/30층",
            floor=10,
            direction="남향",
            url="https://fin.land.naver.com/articles/123",
            observed_at=observed,
            first_seen_at=observed,
            last_seen_at=observed,
            effective_urgent_price_won=2_500_000_000,
        )

    def notifier(self, calls: list, *, fail: bool = False) -> KakaoNotifier:
        def send_links(message, buttons):
            if fail:
                raise RuntimeError("send")
            calls.append(("links", message, buttons))

        def send_text(message, url):
            if fail:
                raise RuntimeError("send")
            calls.append(("text", message, url))

        return KakaoNotifier(sender=send_text, links_sender=send_links)

    @mock.patch("properties.delivery.is_live", return_value=True)
    def test_live_site_gets_one_message_with_both_buttons(self, _live) -> None:
        calls: list = []
        channel = DeliveryService(self.notifier(calls)).send_message(
            [(self.listing, True, False)]
        )
        self.assertEqual(channel, "링크 2개")
        kind, message, buttons = calls[0]
        self.assertEqual(kind, "links")
        self.assertEqual(
            buttons,
            [
                ("통계 보기", "https://example.com/r/token/stats/"),
                ("전체 매물 보기", "https://example.com/r/token/"),
            ],
        )
        self.assertIn("급매1", message)
        self.assertLessEqual(len(message), 200)

    @mock.patch("properties.delivery.is_live", return_value=True)
    def test_statistics_line_leads_the_message_when_there_is_history(self, _live) -> None:
        scan = Scan.objects.create(
            started_at=self.listing.observed_at, success=True
        )
        for index, price in enumerate((2_300_000_000, 2_400_000_000, 2_500_000_000)):
            Observation.objects.create(
                scan=scan,
                condition=self.condition,
                listing_id=str(index),
                complex_name="샘플아파트",
                exclusive_area_m2=Decimal("84.9"),
                price_won=price,
                observed_at=timezone.now(),
            )
        calls: list = []
        DeliveryService(self.notifier(calls)).send_message([(self.listing, True, False)])
        message = calls[0][1]
        self.assertTrue(message.startswith("📊"))
        self.assertIn("최저 23억", message)
        self.assertIn("최고 25억", message)
        # The headline shares the 200-character text template with the listings.
        self.assertLessEqual(len(message), 200)
        self.assertIn("매물 알림", message)

    @mock.patch("properties.delivery.is_live", return_value=True)
    def test_no_history_means_no_statistics_line(self, _live) -> None:
        calls: list = []
        DeliveryService(self.notifier(calls)).send_message([(self.listing, True, False)])
        self.assertFalse(calls[0][1].startswith("📊"))

    @mock.patch("properties.delivery.is_live", return_value=False)
    def test_stale_site_sends_text_without_the_buttons(self, _live) -> None:
        """A button that opens yesterday's numbers is worse than no button."""
        calls: list = []
        channel = DeliveryService(self.notifier(calls)).send_message(
            [(self.listing, True, False)]
        )
        self.assertEqual(channel, "텍스트")
        self.assertEqual(calls[0][0], "text")
        self.assertIn("급매1", calls[0][1])

    @mock.patch("properties.delivery.is_live", return_value=True)
    def test_send_failure_is_recorded_and_raised(self, _live) -> None:
        with self.assertRaises(DeliveryError):
            DeliveryService(self.notifier([], fail=True)).send_message(
                [(self.listing, True, False)]
            )
        failure = NotificationFailure.objects.get()
        self.assertIn("send", failure.error)
        self.assertEqual(failure.link_url, "https://example.com/r/token/")

    @mock.patch("properties.delivery.is_live", return_value=True)
    def test_digest_sends_the_active_listings(self, _live) -> None:
        calls: list = []
        result = DeliveryService(self.notifier(calls)).send_digest()
        self.assertIn("링크 2개", result)
        self.assertIn("매물 1건", result)

    def test_digest_without_listings_says_so(self) -> None:
        Listing.objects.all().delete()
        calls: list = []
        result = DeliveryService(self.notifier(calls)).send_digest()
        self.assertIn("0건", result)
        self.assertEqual(calls[0][0], "text")

    def test_send_alert_prefixes_and_truncates(self) -> None:
        calls: list = []
        result = DeliveryService(self.notifier(calls)).send_alert("x" * 250)
        self.assertIn("오류 알림", result)
        self.assertEqual(calls[0][0], "text")
        message = calls[0][1]
        self.assertTrue(message.startswith("⚠️ "))
        self.assertLessEqual(len(message), 200)

    def test_send_alert_failure_is_recorded_and_raised(self) -> None:
        with self.assertRaises(DeliveryError):
            DeliveryService(self.notifier([], fail=True)).send_alert("문제 발생")
        failure = NotificationFailure.objects.get()
        self.assertIn("send", failure.error)
