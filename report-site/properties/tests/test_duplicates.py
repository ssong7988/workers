"""같은 집이 두 건으로 올라온 경우.

네이버는 한 물건을 중개사별로 나눠 보여줄 때가 있다. 같은 단지·타입·층·가격이면
집은 하나이므로 리포트에서 두 줄로 세거나 카카오를 두 번 보내면 안 된다.

행 자체는 지우지 않는다 — 무엇이 왜 묶였는지 남아 있어야 한다. 접는 것은
화면과 전송 단계다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from properties.models import GlobalRule, Listing, SearchCondition
from properties.scanning import record_scan


class DuplicateListingTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create()
        self.condition = SearchCondition.objects.create(
            id="sample-84",
            name="샘플 84",
            complex_names=["샘플아파트"],
            exclusive_area_m2="84",
            max_price_won=2_600_000_000,
            urgent_price_won=2_500_000_000,
            notify_new=True,
        )
        self.started_at = timezone.make_aware(datetime(2026, 9, 3, 9, 0))

    def payload(self, listing_id: str, **overrides) -> dict:
        values = {
            "condition_id": self.condition.pk,
            "listing_id": listing_id,
            "complex_name": "과천 샘플아파트",
            "type_name": "84A",
            "exclusive_area_m2": 84.9,
            "price_won": 2_550_000_000,
            "floor_text": "10/30층",
            "floor": 10,
            "direction": "남향",
            "description": "",
            "url": f"https://fin.land.naver.com/articles/{listing_id}",
            "observed_at": self.started_at.isoformat(),
        }
        values.update(overrides)
        return values

    def record(self, payloads, minutes: int = 0):
        started = self.started_at + timedelta(minutes=minutes)
        return record_scan(
            started_at=started,
            finished_at=started + timedelta(minutes=1),
            observations=payloads,
            successful_conditions=[self.condition.pk],
        )

    def visible(self) -> list[Listing]:
        return list(Listing.objects.filter(active=True, duplicate_of__isnull=True))

    def test_two_agents_on_one_home_count_once(self) -> None:
        decision = self.record([self.payload("1"), self.payload("2")])

        # 둘 다 저장은 된다. 원본을 지우지 않는 것이 이 프로젝트의 규칙이다.
        self.assertEqual(Listing.objects.count(), 2)
        self.assertEqual(len(self.visible()), 1)
        self.assertEqual(decision.scan.matched_count, 1)
        self.assertEqual(len(decision.alerts), 1)

    def test_the_first_seen_listing_stays_the_primary(self) -> None:
        self.record([self.payload("1")])
        self.record([self.payload("1"), self.payload("2")], minutes=10)

        primary = Listing.objects.get(listing_id="1")
        twin = Listing.objects.get(listing_id="2")
        self.assertIsNone(primary.duplicate_of)
        self.assertEqual(twin.duplicate_of_id, primary.pk)

    def test_a_different_price_is_a_different_home(self) -> None:
        self.record([self.payload("1"), self.payload("2", price_won=2_400_000_000)])

        self.assertEqual(len(self.visible()), 2)

    def test_a_different_floor_is_a_different_home(self) -> None:
        self.record([self.payload("1"), self.payload("2", floor_text="11/30층", floor=11)])

        self.assertEqual(len(self.visible()), 2)

    def test_a_different_type_is_a_different_home(self) -> None:
        self.record([self.payload("1"), self.payload("2", type_name="84B")])

        self.assertEqual(len(self.visible()), 2)

    def test_different_buildings_are_different_homes(self) -> None:
        """101동 10층과 102동 10층은 같은 가격이어도 다른 집이다."""
        self.record(
            [
                self.payload("1", building="101동"),
                self.payload("2", building="102동"),
            ]
        )

        self.assertEqual(len(self.visible()), 2)

    def test_a_missing_building_does_not_bridge_two_buildings(self) -> None:
        """동이 없는 매물이 다리를 놓아 101동과 102동이 합쳐지면 안 된다."""
        self.record(
            [
                self.payload("1"),
                self.payload("2", building="101동"),
                self.payload("3", building="102동"),
            ]
        )

        self.assertEqual(len(self.visible()), 2)

    def test_a_missing_building_joins_the_primary(self) -> None:
        self.record([self.payload("1", building="101동"), self.payload("2")])

        self.assertEqual(len(self.visible()), 1)

    def test_the_survivor_is_promoted_when_the_primary_disappears(self) -> None:
        self.record([self.payload("1"), self.payload("2")])

        self.record([self.payload("2")], minutes=10)

        twin = Listing.objects.get(listing_id="2")
        self.assertIsNone(twin.duplicate_of)
        self.assertEqual(len(self.visible()), 1)

    def test_a_price_change_splits_a_pair(self) -> None:
        self.record([self.payload("1"), self.payload("2")])

        self.record(
            [self.payload("1"), self.payload("2", price_won=2_400_000_000)], minutes=10
        )

        twin = Listing.objects.get(listing_id="2")
        self.assertIsNone(twin.duplicate_of)
        self.assertEqual(len(self.visible()), 2)

    def test_one_urgent_alert_for_one_home(self) -> None:
        decision = self.record(
            [
                self.payload("1", price_won=2_400_000_000),
                self.payload("2", price_won=2_400_000_000),
            ]
        )

        self.assertEqual(decision.scan.urgent_count, 1)
        self.assertEqual(sum(alert.is_urgent for alert in decision.alerts), 1)


if __name__ == "__main__":
    pass
