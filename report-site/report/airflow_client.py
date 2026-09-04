"""Read what Airflow has been doing, for the operations screen.

Airflow cannot run on Windows, so it lives in WSL2 and drives this machine
through interop (see `.agent/PROJECT_STATE.md`). This module goes the other
way: Django asks Airflow what it ran and how it went. It is deliberately
read-only - nothing here triggers, pauses, or clears a DAG. A schedule that
can be started from a public-ish web page is a schedule that can be started by
anyone who reaches that page.

stdlib `urllib` on purpose, matching `real-estate-finder/api_client.py`: the
project has no HTTP dependency and this needs two requests.

Field names are read defensively. Airflow renamed several DAG-run fields
between 2.x and 3.x, and the instance this talks to is not pinned yet, so a
missing key shows as "-" instead of raising and taking the page down.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

# The page is opened by a person waiting for it. A wedged Airflow should say so
# quickly rather than hold a worker thread.
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RUNS = 20


@dataclass(frozen=True)
class DagRun:
    dag_id: str
    run_id: str
    state: str
    run_type: str
    start: str
    end: str


@dataclass(frozen=True)
class Dag:
    dag_id: str
    description: str
    schedule: str
    paused: bool
    next_run: str


@dataclass(frozen=True)
class AirflowStatus:
    """Everything the screen needs, including why it has nothing to show."""

    base_url: str = ""
    configured: bool = False
    reachable: bool = False
    error: str = ""
    dags: list[Dag] = field(default_factory=list)
    runs: list[DagRun] = field(default_factory=list)

    @property
    def failed_runs(self) -> list[DagRun]:
        return [run for run in self.runs if run.state == "failed"]


def _text(payload: dict[str, Any], *names: str) -> str:
    """First present, non-empty value among `names`, as a string."""
    for name in names:
        value = payload.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _open(request: urllib.request.Request, timeout: float) -> Any:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _token(base_url: str, username: str, password: str, timeout: float) -> str:
    """Trade username/password for a JWT, the Airflow 3 simple auth manager way."""
    request = urllib.request.Request(
        f"{base_url}/auth/token",
        data=json.dumps({"username": username, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    payload = _open(request, timeout)
    token = _text(payload, "access_token", "token")
    if not token:
        raise RuntimeError("Airflow가 토큰을 돌려주지 않았습니다.")
    return token


def _get(base_url: str, path: str, token: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    return _open(request, timeout)


def _parse_dags(payload: dict[str, Any]) -> list[Dag]:
    dags = []
    for item in payload.get("dags", []):
        dags.append(
            Dag(
                dag_id=_text(item, "dag_id"),
                description=_text(item, "dag_display_name", "description"),
                # 3.x calls this timetable_summary; 2.x had schedule_interval.
                schedule=_text(item, "timetable_summary", "schedule_interval"),
                paused=bool(item.get("is_paused")),
                next_run=_text(
                    item, "next_dagrun_run_after", "next_dagrun", "next_dagrun_logical_date"
                ),
            )
        )
    return sorted(dags, key=lambda dag: dag.dag_id)


def _parse_runs(payload: dict[str, Any]) -> list[DagRun]:
    runs = []
    for item in payload.get("dag_runs", []):
        runs.append(
            DagRun(
                dag_id=_text(item, "dag_id"),
                run_id=_text(item, "dag_run_id", "run_id"),
                state=_text(item, "state"),
                run_type=_text(item, "run_type"),
                start=_text(item, "start_date"),
                end=_text(item, "end_date"),
            )
        )
    return runs


def fetch_status() -> AirflowStatus:
    """Ask Airflow for its DAGs and recent runs, or explain why we cannot."""
    base_url = getattr(settings, "AIRFLOW_API_URL", "").rstrip("/")
    if not base_url:
        return AirflowStatus(
            error=(
                "AIRFLOW_API_URL이 설정되지 않았습니다. "
                "report-site/.env에 Airflow 주소와 계정을 추가하세요."
            )
        )

    username = getattr(settings, "AIRFLOW_USERNAME", "")
    password = getattr(settings, "AIRFLOW_PASSWORD", "")
    static_token = getattr(settings, "AIRFLOW_API_TOKEN", "")
    timeout = float(
        getattr(settings, "AIRFLOW_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    )
    if not static_token and not (username and password):
        return AirflowStatus(
            base_url=base_url,
            error=(
                "Airflow 계정이 없습니다. AIRFLOW_USERNAME/AIRFLOW_PASSWORD 또는 "
                "AIRFLOW_API_TOKEN을 report-site/.env에 추가하세요."
            ),
        )

    try:
        token = static_token or _token(base_url, username, password, timeout)
        dags = _parse_dags(_get(base_url, "/api/v2/dags?limit=100", token, timeout))
        query = urllib.parse.urlencode(
            {"limit": MAX_RUNS, "order_by": "-start_date"}
        )
        # `~` is Airflow's "every DAG" wildcard for the dagRuns listing.
        runs = _parse_runs(
            _get(base_url, f"/api/v2/dags/~/dagRuns?{query}", token, timeout)
        )
    except urllib.error.HTTPError as error:
        detail = "인증에 실패했습니다." if error.code in (401, 403) else str(error.reason)
        return AirflowStatus(
            base_url=base_url,
            configured=True,
            error=f"Airflow가 요청을 거부했습니다 (HTTP {error.code}). {detail}",
        )
    except urllib.error.URLError as error:
        return AirflowStatus(
            base_url=base_url,
            configured=True,
            error=(
                f"Airflow에 연결하지 못했습니다 ({error.reason}). "
                "WSL이 실행 중인지, Airflow 웹서버가 떠 있는지 확인하세요."
            ),
        )
    except (TimeoutError, OSError, ValueError, RuntimeError) as error:
        return AirflowStatus(
            base_url=base_url,
            configured=True,
            error=f"Airflow 응답을 읽지 못했습니다: {error}",
        )

    return AirflowStatus(
        base_url=base_url,
        configured=True,
        reachable=True,
        dags=dags,
        runs=runs,
    )
