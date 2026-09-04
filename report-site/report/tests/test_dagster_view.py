from datetime import datetime
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from properties.models import GlobalRule, Scan
from report.dagster_client import DagsterStatus, Run


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
        self.assertContains(response, "매물 수집")

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
                    job_name="property_pipeline_job",
                    status="SUCCESS",
                    start="2026-09-04T01:39:23+00:00",
                    end="2026-09-04T01:39:30+00:00",
                ),
                Run(
                    run_id="a1b2c3",
                    job_name="property_pipeline_job",
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
        self.assertContains(response, "property_pipeline_job")
        self.assertContains(response, "2026.09.04 07:00")
        self.assertContains(
            response,
            f'href="{settings.DAGSTER_PATH_PREFIX}/runs"',
        )
