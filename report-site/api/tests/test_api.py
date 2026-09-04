from datetime import datetime, timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from properties.models import GlobalRule, Listing, Observation, Scan, SearchCondition


@override_settings(FINDER_API_TOKEN="test-api-token")
class ApiTests(TestCase):
    def setUp(self) -> None:
        self.client = Client(enforce_csrf_checks=True)
        self.auth = {"HTTP_AUTHORIZATION": "Bearer test-api-token"}
        GlobalRule.objects.create()
        self.condition = SearchCondition.objects.create(
            id="sample-84",
            name="샘플 84",
            complex_names=["샘플아파트"],
            search_url="https://new.land.naver.com/complexes/1",
            exclusive_area_m2="84",
            max_price_won=2_600_000_000,
            urgent_price_won=2_500_000_000,
        )
        SearchCondition.objects.create(
            id="disabled",
            name="미사용 조건",
            complex_names=["미사용"],
            enabled=False,
        )
        self.started_at = timezone.make_aware(datetime(2026, 9, 3, 10, 0))

    def scan_payload(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": (self.started_at + timedelta(minutes=1)).isoformat(),
            "successful_conditions": [self.condition.pk],
            "failed_conditions": {},
            "notify_urgent": False,
            "observations": [
                {
                    "condition_id": self.condition.pk,
                    "listing_id": "123",
                    "complex_name": "과천 샘플아파트",
                    "type_name": "84A",
                    "exclusive_area_m2": 84.9,
                    "price_won": 2_500_000_000,
                    "floor_text": "10/30층",
                    "direction": "남향",
                    "description": "",
                    "url": "https://fin.land.naver.com/articles/123",
                    "observed_at": self.started_at.isoformat(),
                }
            ],
        }

    def test_every_endpoint_requires_the_bearer_token(self) -> None:
        for method, path in (
            ("get", "/api/health/"),
            ("get", "/api/conditions/"),
            ("post", "/api/scans/"),
            ("post", "/api/digest/"),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def test_health_checks_the_database(self) -> None:
        response = self.client.get("/api/health/", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_conditions_returns_only_enabled_database_configuration(self) -> None:
        response = self.client.get("/api/conditions/", **self.auth)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["global_rule"]["trade_type"], "sale")
        self.assertEqual(payload["global_rule"]["low_floor_numeric_floors"], [1, 2, 3])
        self.assertEqual([item["id"] for item in payload["conditions"]], ["sample-84"])
        self.assertEqual(payload["conditions"][0]["exclusive_area_m2"], 84.0)

    def test_scan_records_state_without_requiring_csrf(self) -> None:
        response = self.client.post(
            "/api/scans/",
            self.scan_payload(),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["scan"]["success"])
        self.assertEqual(payload["scan"]["collected_count"], 1)
        self.assertEqual(payload["scan"]["matched_count"], 1)
        self.assertEqual(payload["scan"]["urgent_count"], 1)
        self.assertEqual(payload["alerts"], [])
        self.assertEqual(Scan.objects.count(), 1)
        self.assertEqual(Observation.objects.count(), 1)
        self.assertEqual(Listing.objects.count(), 1)
        self.assertIsNone(Listing.objects.get().last_urgent_alert_price_won)

    def test_scan_rejects_invalid_json_without_writing(self) -> None:
        response = self.client.post(
            "/api/scans/",
            "not-json",
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_request")
        self.assertEqual(Scan.objects.count(), 0)

    def test_scan_rejects_overlapping_success_and_failure(self) -> None:
        payload = self.scan_payload()
        payload["failed_conditions"] = {self.condition.pk: "수집 실패"}
        response = self.client.post(
            "/api/scans/", payload, content_type="application/json", **self.auth
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("겹칠 수 없습니다", response.json()["error"])
        self.assertEqual(Scan.objects.count(), 0)

    @mock.patch("api.views.DeliveryService")
    def test_scan_sends_urgent_after_state_is_committed(self, delivery_class) -> None:
        payload = self.scan_payload()
        payload["notify_urgent"] = True
        response = self.client.post(
            "/api/scans/", payload, content_type="application/json", **self.auth
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["alerts"]), 1)
        decision = delivery_class.return_value.send_scan_alerts.call_args.args[0]
        self.assertIsNotNone(decision.scan.pk)
        self.assertTrue(decision.alerts[0].is_urgent)
        self.assertTrue(decision.alerts[0].is_new)
        self.assertEqual(Observation.objects.count(), 1)
        self.assertEqual(Listing.objects.get().last_urgent_alert_price_won, 2_500_000_000)

    @mock.patch("api.views.DeliveryService")
    def test_digest_sends_database_report(self, delivery_class) -> None:
        delivery_class.return_value.send_digest.return_value = (
            "카카오 전송 완료(링크 2개): 매물 1건"
        )
        response = self.client.post(
            "/api/digest/", {}, content_type="application/json", **self.auth
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("전송 완료", response.json()["notification"])

    def test_wrong_method_returns_json_405(self) -> None:
        response = self.client.get("/api/scans/", **self.auth)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")
