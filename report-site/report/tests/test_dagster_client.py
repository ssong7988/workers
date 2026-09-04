"""Unit tests for the read-only Dagster GraphQL client.

Mirrors `report/tests/test_airflow_client.py`'s style: mock
`urllib.request.urlopen` at the module level rather than standing up a real
webserver, since this client is deliberately stdlib-only. Every response
shape asserted here was confirmed against a real `dagster dev` instance
while writing `dagster_client.py` (see .agent/PROJECT_STATE.md) - these
fixtures are not guesses.
"""

from __future__ import annotations

import io
import json
import unittest.mock
import urllib.error

from django.test import SimpleTestCase, override_settings

from report.dagster_client import fetch_status


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def json_response(payload: dict) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))


class NotConfiguredTests(SimpleTestCase):
    databases = set()

    @override_settings(DAGSTER_GRAPHQL_URL="")
    def test_missing_url_says_not_configured(self) -> None:
        status = fetch_status()
        self.assertFalse(status.configured)
        self.assertFalse(status.reachable)
        self.assertIn("DAGSTER_GRAPHQL_URL", status.error)


@override_settings(
    DAGSTER_GRAPHQL_URL="http://127.0.0.1:3000/test-token/common/dagster/console/graphql",
    DAGSTER_TIMEOUT_SECONDS=5.0,
)
class FetchStatusTests(SimpleTestCase):
    databases = set()

    def test_success_parses_runs(self) -> None:
        response = json_response(
            {
                "data": {
                    "runsOrError": {
                        "__typename": "Runs",
                        "results": [
                            {
                                "runId": "ce42589c-3c6a-4cbd-a558-0b789fc5fdcf",
                                "jobName": "scan_job",
                                "status": "SUCCESS",
                                "startTime": 1788485963.618406,
                                "endTime": 1788485970.147663,
                            },
                            {
                                "runId": "a1b2c3",
                                "jobName": "scan_job",
                                "status": "FAILURE",
                                "startTime": 1788485000.0,
                                "endTime": 1788485010.0,
                            },
                        ],
                    }
                }
            }
        )
        with unittest.mock.patch(
            "urllib.request.urlopen", return_value=response
        ) as urlopen:
            status = fetch_status()

        self.assertTrue(status.reachable)
        self.assertEqual(status.error, "")
        self.assertEqual(len(status.runs), 2)
        self.assertEqual(status.runs[0].status, "SUCCESS")
        self.assertEqual(len(status.failed_runs), 1)
        self.assertEqual(status.failed_runs[0].job_name, "scan_job")
        # Epoch seconds convert to an ISO string, not pass through raw.
        self.assertTrue(status.runs[0].start.startswith("2026-"))

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:3000/test-token/common/dagster/console/graphql",
        )
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_empty_run_list(self) -> None:
        response = json_response(
            {"data": {"runsOrError": {"__typename": "Runs", "results": []}}}
        )
        with unittest.mock.patch("urllib.request.urlopen", return_value=response):
            status = fetch_status()
        self.assertTrue(status.reachable)
        self.assertEqual(status.runs, [])
        self.assertEqual(status.failed_runs, [])

    def test_graphql_python_error_is_surfaced(self) -> None:
        response = json_response(
            {
                "data": {
                    "runsOrError": {
                        "__typename": "PythonError",
                        "message": "boom",
                    }
                }
            }
        )
        with unittest.mock.patch("urllib.request.urlopen", return_value=response):
            status = fetch_status()
        self.assertFalse(status.reachable)
        self.assertIn("boom", status.error)

    def test_unreachable_host_reports_a_connection_error(self) -> None:
        with unittest.mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            status = fetch_status()
        self.assertFalse(status.reachable)
        self.assertIn("연결하지 못했습니다", status.error)

    def test_malformed_json_does_not_raise(self) -> None:
        with unittest.mock.patch(
            "urllib.request.urlopen", return_value=FakeResponse(b"not json")
        ):
            status = fetch_status()
        self.assertFalse(status.reachable)
        self.assertIn("응답을 읽지 못했습니다", status.error)
