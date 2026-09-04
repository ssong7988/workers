"""Read what Dagster has been doing, for the operations screen.

Dagster runs natively on this Windows machine (`dagster_project/`, its own
venv) - no WSL, no interop layer, unlike the parked `airflow/dags/` plan (see
.agent/PROJECT_STATE.md, "막힌 지점"). This module goes the other way: Django
asks it what ran and how it went. Read-only - nothing here launches, retries,
or terminates a run. A schedule startable from a public-ish web page is a
schedule startable by anyone who reaches that page.

Only the well-documented `runsOrError` GraphQL query is used, and every field
name and value shape here (including `status` being uppercase, e.g.
"SUCCESS"/"FAILURE", and timestamps being float epoch seconds) was confirmed
against a real `dagster dev` instance while writing this, not assumed from
docs - see PROJECT_STATE.md for how. Dagster's own docs say the GraphQL
schema "is still evolving and is subject to breaking changes... primarily
for internal use by the Dagster webserver", so the job/schedule listing -
which would need a much more fragile, undocumented query shape - is not
attempted here; JOBS below is a short static list instead, kept in sync by
hand with `dagster_project/definitions.py`.

stdlib `urllib` on purpose, matching `report/airflow_client.py` and
`real-estate-finder/api_client.py`: the project has no HTTP dependency and
this needs one request.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from django.conf import settings

DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RUNS = 20

# Mirrors dagster_project/definitions.py's three jobs/schedules. Not read
# from Dagster itself (see module docstring) - update this by hand if a
# schedule there changes.
JOBS = (
    {"name": "site_watchdog_job", "description": "리포트 서버 생존 확인/기동", "cron": "매시 정각"},
    {"name": "scan_job", "description": "매물 수집", "cron": "7시·12시·17시"},
    {"name": "morning_digest_job", "description": "아침 리포트 발송", "cron": "8시"},
)


@dataclass(frozen=True)
class Run:
    run_id: str
    job_name: str
    status: str
    start: str
    end: str


@dataclass(frozen=True)
class DagsterStatus:
    """Everything the screen needs, including why it has nothing to show."""

    base_url: str = ""
    configured: bool = False
    reachable: bool = False
    error: str = ""
    runs: list[Run] = field(default_factory=list)

    @property
    def failed_runs(self) -> list[Run]:
        return [run for run in self.runs if run.status == "FAILURE"]


def _text(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _iso(epoch_seconds: Any) -> str:
    """Dagster's GraphQL timestamps are float epoch seconds, not ISO strings."""
    if epoch_seconds in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


RUNS_QUERY = """
query RecentRuns($limit: Int!) {
  runsOrError(limit: $limit) {
    __typename
    ... on Runs {
      results {
        runId
        jobName
        status
        startTime
        endTime
      }
    }
    ... on PythonError {
      message
    }
  }
}
"""


def fetch_status() -> DagsterStatus:
    """Ask Dagster for recent runs, or explain why we cannot."""
    base_url = getattr(settings, "DAGSTER_GRAPHQL_URL", "").strip()
    if not base_url:
        return DagsterStatus(
            error=(
                "DAGSTER_GRAPHQL_URL이 설정되지 않았습니다. "
                "report-site/.env에 Dagster 웹서버 주소를 추가하세요."
            )
        )
    timeout = float(
        getattr(settings, "DAGSTER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    )

    body = json.dumps(
        {"query": RUNS_QUERY, "variables": {"limit": MAX_RUNS}}
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        return DagsterStatus(
            base_url=base_url,
            configured=True,
            error=(
                f"Dagster에 연결하지 못했습니다 ({error.reason}). "
                "dagster_project\\run-dagster.bat이 실행 중인지 확인하세요."
            ),
        )
    except (TimeoutError, OSError, ValueError) as error:
        return DagsterStatus(
            base_url=base_url,
            configured=True,
            error=f"Dagster 응답을 읽지 못했습니다: {error}",
        )

    if payload.get("errors"):
        return DagsterStatus(
            base_url=base_url,
            configured=True,
            error=f"Dagster가 요청을 거부했습니다: {payload['errors']}",
        )

    runs_or_error = payload.get("data", {}).get("runsOrError", {})
    if runs_or_error.get("__typename") != "Runs":
        message = runs_or_error.get("message", "알 수 없는 오류")
        return DagsterStatus(
            base_url=base_url, configured=True, error=f"Dagster 오류: {message}"
        )

    runs = [
        Run(
            run_id=_text(item, "runId"),
            job_name=_text(item, "jobName"),
            status=_text(item, "status"),
            start=_iso(item.get("startTime")),
            end=_iso(item.get("endTime")),
        )
        for item in runs_or_error.get("results", [])
    ]
    return DagsterStatus(base_url=base_url, configured=True, reachable=True, runs=runs)
