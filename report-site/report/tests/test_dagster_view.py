from datetime import datetime
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from properties.models import GlobalRule, Scan
from report.dagster_client import JOBS, DagsterStatus, Run


class DagsterViewTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create(timezone="Asia/Seoul")
        self.url = f"{settings.DAGSTER_SUMMARY_PATH}/"
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
            "report.views.fetch_dagster_status",
            return_value=DagsterStatus(error="DAGSTER_GRAPHQL_URL이 설정되지 않았습니다."),
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DAGSTER_GRAPHQL_URL")
        self.assertEqual(response["Cache-Control"], "no-store")
        # The static job list renders regardless of whether Dagster itself
        # answered - it's the whole point of not depending on a live query.
        self.assertContains(response, "네이버 부동산 매물 스캔")

    def test_staff_sees_every_registered_job(self) -> None:
        """Both jobs in definitions.py show up, scheduled or not.

        restart_report_site_job has no schedule, so an earlier version of the
        static summary simply omitted it and the screen claimed one job.
        """
        staff = get_user_model().objects.create_user(
            username="ops", password="pw", is_staff=True
        )
        self.client.force_login(staff)
        status = DagsterStatus(configured=True, reachable=True)
        with mock.patch("report.views.fetch_dagster_status", return_value=status):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "scan_job")
        self.assertContains(response, "pre_scan_health_job")
        self.assertContains(response, "hable_ready_job")
        self.assertContains(response, "stock_daily_job")
        self.assertContains(response, "morning_report_job")
        self.assertContains(response, "restart_report_site_job")
        self.assertContains(response, "수동 실행")
        self.assertContains(response, "네이버 부동산 관심단지")
        self.assertContains(response, "H-able [1285]")
        self.assertContains(response, "kakao-notifier")
        self.assertContains(response, "Yahoo Finance·Upbit")
        self.assertContains(response, "Dagster가 하는 일")
        self.assertContains(
            response,
            f'<div class="tile-value">{len(JOBS)}</div><div class="tile-label">등록된 잡</div>',
            html=False,
        )
        self.assertEqual(len(JOBS), 7)

    def test_staff_sees_runs_and_latest_scan(self) -> None:
        staff = get_user_model().objects.create_user(
            username="ops", password="pw", is_staff=True
        )
        self.client.force_login(staff)
        observed_at = timezone.make_aware(datetime(2026, 9, 4, 7, 0))
        Scan.objects.create(started_at=observed_at, finished_at=observed_at, success=True)

        status = DagsterStatus(
            base_url=f"http://127.0.0.1:3000{settings.DAGSTER_PATH_PREFIX}/graphql",
            configured=True,
            reachable=True,
            runs=[
                Run(
                    run_id="ce42589c-3c6a-4cbd-a558-0b789fc5fdcf",
                    job_name="scan_job",
                    status="SUCCESS",
                    start="2026-09-04T01:39:23+00:00",
                    end="2026-09-04T01:39:30+00:00",
                ),
                Run(
                    run_id="a1b2c3",
                    job_name="scan_job",
                    status="FAILURE",
                    start="2026-09-04T00:00:00+00:00",
                    end="2026-09-04T00:00:10+00:00",
                ),
            ],
        )
        with mock.patch("report.views.fetch_dagster_status", return_value=status):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ce42589c-3c6a-4cbd-a558-0b789fc5fdcf")
        self.assertContains(response, "scan_job")
        self.assertContains(response, "2026.09.04 07:00")
        self.assertContains(
            response,
            f'href="{settings.DAGSTER_PATH_PREFIX}/runs"',
        )
