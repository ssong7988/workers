from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from properties.models import GlobalRule, Listing, Observation, SearchCondition
from properties.scanning import record_scan


class RecordScanTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create()
        self.condition = SearchCondition.objects.create(
            id="sample-84",
            name="샘플 84",
            complex_names=["샘플아파트"],
            exclusive_area_m2="84",
            max_price_won=2_600_000_000,
            urgent_price_won=2_500_000_000,
        )
        self.started_at = timezone.make_aware(datetime(2026, 9, 3, 9, 0))

    def payload(self, **overrides) -> dict:
        values = {
            "condition_id": self.condition.pk,
            "listing_id": "123",
            "complex_name": "과천 샘플아파트",
            "type_name": "84A",
            "exclusive_area_m2": 84.9,
            "price_won": 2_500_000_000,
            "floor_text": "10/30층",
            "floor": 10,
            "direction": "남향",
            "description": "",
            "url": "https://fin.land.naver.com/articles/123",
            "observed_at": self.started_at.isoformat(),
        }
        values.update(overrides)
        return values

    def record(self, payloads, **overrides):
        values = {
            "started_at": self.started_at,
            "finished_at": self.started_at + timedelta(minutes=1),
            "observations": payloads,
            "successful_conditions": [self.condition.pk],
        }
        values.update(overrides)
        return record_scan(**values)

    def test_records_all_observations_and_only_upserts_matches(self) -> None:
        decision = self.record(
            [self.payload(), self.payload(listing_id="excluded", price_won=2_700_000_000)]
        )
        self.assertEqual(Observation.objects.count(), 2)
        excluded = Observation.objects.get(listing_id="excluded")
        self.assertIn("가격 초과", excluded.exclusion_reason)
        self.assertEqual(Listing.objects.count(), 1)
        self.assertEqual(decision.scan.collected_count, 2)
        self.assertEqual(decision.scan.matched_count, 1)
        self.assertEqual(decision.scan.excluded_count, 1)

    def test_building_carries_from_observation_to_listing(self) -> None:
        self.record([self.payload(building="101동")])
        self.assertEqual(Observation.objects.get().building, "101동")
        self.assertEqual(Listing.objects.get().building, "101동")

    def test_first_urgent_same_price_and_lower_price_alert_policy(self) -> None:
        first = self.record([self.payload()])
        self.assertEqual(len(first.alerts), 1)
        listing = Listing.objects.get()
        first_seen = listing.first_seen_at
        self.assertEqual(listing.last_urgent_alert_price_won, 2_500_000_000)

        self.started_at += timedelta(hours=1)
        repeat = self.record([self.payload(observed_at=self.started_at.isoformat())])
        self.assertEqual(repeat.alerts, ())
        listing.refresh_from_db()
        self.assertEqual(listing.first_seen_at, first_seen)
        self.assertIn("이미", repeat.scan.notification)

        self.started_at += timedelta(hours=1)
        lower = self.record(
            [self.payload(price_won=2_490_000_000, observed_at=self.started_at.isoformat())]
        )
        self.assertEqual(len(lower.alerts), 1)
        listing.refresh_from_db()
        self.assertEqual(listing.last_urgent_alert_price_won, 2_490_000_000)

    def test_smoke_does_not_consume_alert_history(self) -> None:
        decision = self.record([self.payload()], notify_urgent=False, smoke=True)
        self.assertEqual(decision.alerts, ())
        self.assertIsNone(Listing.objects.get().last_urgent_alert_price_won)
        self.assertIn("smoke", decision.scan.notification)

    def test_notify_new_without_urgent_threshold(self) -> None:
        self.condition.urgent_price_won = None
        self.condition.max_price_won = None
        self.condition.notify_new = True
        self.condition.save()
        decision = self.record([self.payload(price_won=3_000_000_000)])
        self.assertEqual(len(decision.alerts), 1)
        self.assertFalse(decision.alerts[0].is_urgent)
        self.assertTrue(decision.alerts[0].is_new)

    def test_only_successful_conditions_deactivate_missing_listings(self) -> None:
        self.record([self.payload()])
        self.started_at += timedelta(hours=1)
        self.record([self.payload(price_won=2_700_000_000)])
        listing = Listing.objects.get()
        self.assertFalse(listing.active)
        self.assertIn(
            "가격 초과",
            Observation.objects.order_by("-scan__started_at").first().exclusion_reason,
        )

        listing.active = True
        listing.save(update_fields=("active",))
        other_start = self.started_at + timedelta(hours=1)
        record_scan(
            started_at=other_start,
            finished_at=other_start + timedelta(minutes=1),
            observations=[],
            successful_conditions=[],
            failed_conditions={self.condition.pk: "수집 실패"},
        )
        listing.refresh_from_db()
        self.assertTrue(listing.active)

    def test_invalid_payload_rolls_back_the_whole_scan(self) -> None:
        with self.assertRaises(ValueError):
            self.record(
                [self.payload(), self.payload(listing_id="bad", observed_at="invalid")]
            )
        self.assertEqual(Observation.objects.count(), 0)
        self.assertEqual(Listing.objects.count(), 0)
