from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from properties.delivery import DeliveryError, DeliveryService
from properties.models import GlobalRule, Listing, NotificationFailure, SearchCondition
from properties.notifier import KakaoNotifier


@override_settings(REPORT_PUBLIC_URL="https://example.com/r/token/")
class DeliveryTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create()
        condition = SearchCondition.objects.create(
            id="sample",
            name="샘플",
            complex_names=["샘플"],
        )
        observed = timezone.make_aware(datetime(2026, 9, 3, 9, 0))
        self.listing = Listing.objects.create(
            condition=condition,
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

    @mock.patch("properties.delivery.is_live", return_value=True)
    @mock.patch(
        "properties.delivery.build_card_image",
        return_value=(Path("card.png"), 1080, 1200),
    )
    def test_image_card_uses_report_link_when_current(self, _build, _live) -> None:
        calls = []
        notifier = KakaoNotifier(image_sender=lambda *args: calls.append(args))
        channel = DeliveryService(notifier).send_card(
            [(self.listing, True, False)], heading="오늘의 매물"
        )
        self.assertEqual(channel, "카드 이미지")
        self.assertEqual(calls[0][3], "https://example.com/r/token/")

    @mock.patch("properties.delivery.is_live", return_value=False)
    @mock.patch("properties.delivery.build_card_image", side_effect=RuntimeError("render"))
    def test_image_failure_falls_back_to_one_text(self, _build, _live) -> None:
        sent = []
        notifier = KakaoNotifier(sender=lambda message, url: sent.append((message, url)))
        channel = DeliveryService(notifier).send_card(
            [(self.listing, True, False)], heading="오늘의 매물"
        )
        self.assertEqual(channel, "텍스트 폴백")
        self.assertEqual(len(sent), 1)
        self.assertIn("급매1", sent[0][0])

    @mock.patch("properties.delivery.is_live", return_value=False)
    @mock.patch("properties.delivery.build_card_image", side_effect=RuntimeError("render"))
    def test_total_failure_is_recorded_and_raised(self, _build, _live) -> None:
        notifier = KakaoNotifier(sender=lambda *_: (_ for _ in ()).throw(RuntimeError("send")))
        with self.assertRaises(DeliveryError):
            DeliveryService(notifier).send_card(
                [(self.listing, True, False)], heading="오늘의 매물"
            )
        failure = NotificationFailure.objects.get()
        self.assertIn("send", failure.error)
        self.assertEqual(failure.link_url, "https://example.com/r/token/")
