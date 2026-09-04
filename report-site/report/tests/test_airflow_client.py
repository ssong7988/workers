"""Unit tests for the read-only Airflow REST client.

Mirrors `real-estate-finder/tests/test_api_client.py`'s style: mock
`urllib.request.urlopen` at the module level rather than standing up a real
server, since this client is deliberately stdlib-only.
"""

from __future__ import annotations

import io
import json
import unittest.mock
import urllib.error

from django.test import SimpleTestCase, override_settings

from report.airflow_client import fetch_status


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def json_response(payload: dict) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))


class NotConfiguredTests(SimpleTestCase):
    databases = set()

    @override_settings(AIRFLOW_API_URL="")
    def test_missing_url_says_not_configured(self) -> None:
        status = fetch_status()
        self.assertFalse(status.configured)
        self.assertFalse(status.reachable)
        self.assertIn("AIRFLOW_API_URL", status.error)

    @override_settings(
        AIRFLOW_API_URL="http://127.0.0.1:8080",
        AIRFLOW_USERNAME="",
        AIRFLOW_PASSWORD="",
        AIRFLOW_API_TOKEN="",
    )
    def test_missing_credentials_says_so(self) -> None:
        status = fetch_status()
        self.assertFalse(status.reachable)
        self.assertIn("계정", status.error)


@override_settings(
    AIRFLOW_API_URL="http://127.0.0.1:8080",
    AIRFLOW_USERNAME="admin",
    AIRFLOW_PASSWORD="admin",
    AIRFLOW_API_TOKEN="",
    AIRFLOW_TIMEOUT_SECONDS=5.0,
)
class FetchStatusTests(SimpleTestCase):
    databases = set()

    def test_success_parses_dags_and_runs(self) -> None:
        responses = [
            json_response({"access_token": "jwt-token"}),
            json_response(
                {
                    "dags": [
                        {
                            "dag_id": "scan",
                            "dag_display_name": "매물 수집",
                            "timetable_summary": "0 7,12,17 * * *",
                            "is_paused": False,
                            "next_dagrun_run_after": "2026-09-05T07:00:00+09:00",
                        }
                    ]
                }
            ),
            json_response(
                {
                    "dag_runs": [
                        {
                            "dag_id": "scan",
                            "dag_run_id": "scheduled__2026-09-04T07:00:00",
                            "state": "success",
                            "run_type": "scheduled",
                            "start_date": "2026-09-04T07:00:00+09:00",
                            "end_date": "2026-09-04T07:04:00+09:00",
                        },
                        {
                            "dag_id": "morning_digest",
                            "dag_run_id": "scheduled__2026-09-04T08:00:00",
                            "state": "failed",
                            "run_type": "scheduled",
                            "start_date": "2026-09-04T08:00:00+09:00",
                            "end_date": "2026-09-04T08:01:00+09:00",
                        },
                    ]
                }
            ),
        ]
        with unittest.mock.patch("urllib.request.urlopen", side_effect=responses) as urlopen:
            status = fetch_status()

        self.assertTrue(status.reachable)
        self.assertEqual(status.error, "")
        self.assertEqual(len(status.dags), 1)
        self.assertEqual(status.dags[0].dag_id, "scan")
        self.assertEqual(status.dags[0].description, "매물 수집")
        self.assertEqual(len(status.runs), 2)
        self.assertEqual(len(status.failed_runs), 1)
        self.assertEqual(status.failed_runs[0].dag_id, "morning_digest")

        token_request = urlopen.call_args_list[0].args[0]
        self.assertEqual(token_request.full_url, "http://127.0.0.1:8080/auth/token")
        dags_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(dags_request.get_header("Authorization"), "Bearer jwt-token")

    def test_static_token_skips_the_login_call(self) -> None:
        with override_settings(AIRFLOW_API_TOKEN="pre-issued"):
            responses = [
                json_response({"dags": []}),
                json_response({"dag_runs": []}),
            ]
            with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=responses
            ) as urlopen:
                status = fetch_status()

        self.assertTrue(status.reachable)
        self.assertEqual(urlopen.call_count, 2)
        first_request = urlopen.call_args_list[0].args[0]
        self.assertEqual(first_request.get_header("Authorization"), "Bearer pre-issued")

    def test_unreachable_host_reports_a_connection_error(self) -> None:
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            status = fetch_status()
        self.assertFalse(status.reachable)
        self.assertIn("연결하지 못했습니다", status.error)

    def test_unauthorized_reports_an_auth_error(self) -> None:
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://127.0.0.1:8080/auth/token", 401, "Unauthorized", None, None
            ),
        ):
            status = fetch_status()
        self.assertFalse(status.reachable)
        self.assertIn("HTTP 401", status.error)
