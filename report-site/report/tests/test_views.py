from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.test import Client, TestCase
from django.utils import timezone

from properties.models import GlobalRule, Listing, Scan, SearchCondition


class ReportViewTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create(timezone="Asia/Seoul")
        self.condition = SearchCondition.objects.create(
            id="cond-a",
            name="테스트단지",
            complex_names=["테스트단지"],
            exclusive_area_m2=Decimal("84"),
            max_price_won=2_600_000_000,
            urgent_price_won=2_500_000_000,
        )
        self.client = Client()
        self.url = f"/r/{settings.REPORT_PATH_TOKEN}/"
        self.observed_at = timezone.make_aware(datetime(2026, 9, 3, 8, 0))

    def listing(self, listing_id: str, price_won: int, **overrides) -> Listing:
        values = {
            "condition": self.condition,
            "listing_id": listing_id,
            "complex_name": "과천 테스트단지",
            "type_name": "84A",
            "exclusive_area_m2": Decimal("84.900"),
            "price_won": price_won,
            "floor_text": "10/30층",
            "floor": 10,
            "direction": "남향",
            "description": "",
            "url": f"https://fin.land.naver.com/articles/{listing_id}",
            "observed_at": self.observed_at,
            "is_low_floor": False,
            "effective_max_price_won": 2_600_000_000,
            "effective_urgent_price_won": 2_500_000_000,
            "first_seen_at": self.observed_at,
            "last_seen_at": self.observed_at,
            "active": True,
        }
        values.update(overrides)
        return Listing.objects.create(**values)

    def test_valid_token_renders_active_database_listings_only(self) -> None:
        self.listing("1", 2_400_000_000, building="101동")
        self.listing("2", 2_550_000_000)
        self.listing("3", 2_400_000_000, active=False)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('data-observed-at="2026-09-03T08:00:00+09:00"', html)
        self.assertEqual(response.context["total"], 2)
        self.assertEqual(len(response.context["urgent"]), 1)
        self.assertContains(response, "26억 이하 · 전용 83~86㎡")
        self.assertContains(response, "101동 · 전용 84.9㎡")
        self.assertContains(response, "전용 84.9㎡")
        self.assertNotIn("fin.land.naver.com/articles/3", html)

    def test_non_article_and_non_numeric_listings_stay_out_of_report(self) -> None:
        self.listing("card-hash", 2_400_000_000)
        self.listing(
            "123", 2_400_000_000, url="https://new.land.naver.com/complexes/1"
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["total"], 0)
        self.assertContains(response, "활성 매물이 없습니다")

    def test_cache_control_is_no_store(self) -> None:
        self.listing("1", 2_550_000_000)
        response = self.client.get(self.url)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_wrong_token_is_404(self) -> None:
        response = self.client.get("/r/not-the-real-token/")
        self.assertEqual(response.status_code, 404)

    def test_root_path_is_404(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 404)

    def test_empty_database_renders_empty_state_not_500(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "활성 매물이 없습니다")
        self.assertContains(response, 'data-observed-at=""', html=False)

    def test_observed_at_falls_back_to_latest_successful_condition_scan(self) -> None:
        earlier = self.observed_at - timedelta(days=1)
        Scan.objects.create(
            started_at=earlier,
            finished_at=earlier + timedelta(minutes=1),
            successful_conditions=[self.condition.pk],
        )
        failed = self.observed_at
        Scan.objects.create(
            started_at=failed,
            finished_at=failed + timedelta(minutes=1),
            successful_conditions=[],
            failed_conditions={self.condition.pk: "수집 실패"},
        )
        response = self.client.get(self.url)
        self.assertContains(
            response,
            'data-observed-at="2026-09-02T08:01:00+09:00"',
            html=False,
        )

    def test_disabled_condition_is_hidden_even_when_listing_is_active(self) -> None:
        self.listing("1", 2_400_000_000)
        self.condition.enabled = False
        self.condition.save(update_fields=("enabled",))
        response = self.client.get(self.url)
        self.assertEqual(response.context["total"], 0)
