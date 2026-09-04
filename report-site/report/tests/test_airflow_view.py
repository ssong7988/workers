from datetime import datetime
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from properties.models import GlobalRule, Scan
from report.airflow_client import AirflowStatus, Dag, DagRun


class AirflowViewTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create(timezone="Asia/Seoul")
        self.url = f"/{settings.ROUTE_PREFIX}airflow/"
        self.client = Client()

    def test_anonymous_visitor_is_redirected_to_admin_login(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("admin", response["Location"])

    def test_non_staff_user_is_redirected(self) -> None:
        get_user_model().objects.create_user(username="reader", password="pw")
        self.client.login(username="reader", password="pw")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_staff_sees_not_configured_message(self) -> None:
        staff = get_user_model().objects.create_user(
            username="ops", password="pw", is_staff=True
        )
        self.client.force_login(staff)
        with mock.patch(
            "report.views.fetch_airflow_status",
            return_value=AirflowStatus(error="AIRFLOW_API_URL이 설정되지 않았습니다."),
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AIRFLOW_API_URL")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_staff_sees_dags_and_runs_and_latest_scan(self) -> None:
        staff = get_user_model().objects.create_user(
            username="ops", password="pw", is_staff=True
        )
        self.client.force_login(staff)
        observed_at = timezone.make_aware(datetime(2026, 9, 4, 7, 0))
        Scan.objects.create(started_at=observed_at, finished_at=observed_at, success=True)

        status = AirflowStatus(
            base_url="http://127.0.0.1:8080",
            configured=True,
            reachable=True,
            dags=[
                Dag(
                    dag_id="scan",
                    description="매물 수집",
                    schedule="0 7,12,17 * * *",
                    paused=False,
                    next_run="2026-09-05T07:00:00+09:00",
                )
            ],
            runs=[
                DagRun(
                    dag_id="scan",
                    run_id="scheduled__2026-09-04T07:00:00",
                    state="success",
                    run_type="scheduled",
                    start="2026-09-04T07:00:00+09:00",
                    end="2026-09-04T07:04:00+09:00",
                ),
                DagRun(
                    dag_id="morning_digest",
                    run_id="scheduled__2026-09-04T08:00:00",
                    state="failed",
                    run_type="scheduled",
                    start="2026-09-04T08:00:00+09:00",
                    end="2026-09-04T08:01:00+09:00",
                ),
            ],
        )
        with mock.patch("report.views.fetch_airflow_status", return_value=status):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "매물 수집")
        self.assertContains(response, "scheduled__2026-09-04T08:00:00")
        self.assertContains(response, "2026.09.04 07:00")
