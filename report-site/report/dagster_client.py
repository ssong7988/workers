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
attempted here; JOBS below is a short static summary instead, kept in sync
by hand with `dagster_project/definitions.py`.

That hand-sync is a real cost, not a footnote: `restart_report_site_job`
existed in definitions.py for a while before this summary learned about it,
so the screen claimed one registered job when there were two. Adding or
renaming a job or schedule in definitions.py means editing JOBS in the same
change - as the 2026-09-04 move to asset jobs did, which renamed every
scheduled job at once.

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

# Mirrors every job in dagster_project/definitions.py's `defs`, with the
# schedules pointed at it. Not read from Dagster itself (see module docstring).
# A job with no schedule still belongs here - it is launched by hand from the
# Dagster UI, and the operator needs to know it exists.
#
# scan_job and morning_report_job are asset jobs over the chain
# naver_listings -> morning_report; the lineage lives in the asset graph, not
# here. server_check_job, pre_scan_health_job, hable_ready_job, and
# restart_report_site_job are plain op jobs.
JOBS = (
    {
        "name": "server_check_job",
        "title": "리포트 서버 확인",
        "category": "공통",
        "purpose": "웹 리포트가 요청을 받을 수 있는지 확인하고, 꺼져 있으면 다시 띄웁니다.",
        "method": (
            "수집기의 check-api 명령으로 Django와 PostgreSQL 연결을 함께 확인합니다. "
            "응답이 없으면 ensure-site.ps1이 Waitress 웹 서버를 백그라운드로 시작하고 "
            "정상 응답이 올 때까지 확인합니다. 데이터 수집이나 메시지 발송은 하지 않습니다."
        ),
        "steps": (
            "Bearer 인증이 포함된 /api/health/ 요청으로 Django·DB 상태 확인",
            "실패하면 127.0.0.1:8000의 report-site 프로세스 기동",
            "웹 서버가 정상 응답하면 완료",
        ),
        "result": "웹 리포트 서버 실행 상태",
        # 매시 점검이 pre_scan_health_job으로 넘어가 스케줄이 없다. 서버만 빠르게
        # 확인하고 싶을 때 UI에서 직접 돌린다.
        "schedules": (
            {"description": "서버 확인", "cron": "수동 실행 (Dagster UI)"},
        ),
    },
    {
        "name": "pre_scan_health_job",
        "title": "수집 전 사전 점검",
        "category": "공통",
        "purpose": "다음 부동산·금융자산 수집이 로그인 문제로 시작부터 실패하지 않게 준비합니다.",
        "method": (
            "먼저 리포트 서버를 확인한 뒤, Edge의 디버깅 연결(CDP 9222)에 붙어 "
            "네이버 로그인 상태를 검사하고 필요하면 저장된 환경 설정으로 다시 로그인합니다. "
            "동시에 H-able [1285] 조회를 한 번 눌러 세션을 유지하되, 사용자가 PC를 "
            "쓰는 중이면 방해를 줄이기 위해 건너뛸 수 있습니다."
        ),
        "steps": (
            "report-site와 PostgreSQL 상태 확인 및 필요 시 복구",
            "Edge 임시 탭에서 네이버 로그인 확인·자동 재로그인",
            "H-able [1285] 조회로 세션 유지 (실패해도 잡은 계속 진행)",
        ),
        "result": "다음 자동 수집에 필요한 서버·로그인 준비 상태",
        "schedules": (
            {"description": "아침 수집 전 집중 점검", "cron": "매일 06:00"},
            {
                "description": "수집·발송 전용 시간이 아닌 정각 점검",
                "cron": "00~05, 09~11, 13~16, 18~23시 정각",
            },
        ),
    },
    {
        "name": "hable_ready_job",
        "title": "H-able 수집 준비 확인",
        "category": "금융자산",
        "purpose": "금융자산 수집 30분 전에 H-able을 실제로 사용할 수 있는지 확인해 대응 시간을 확보합니다.",
        "method": (
            "관리자 권한 작업 스케줄러를 통해 hable-status를 실행하고 H-able [1285] "
            "총자산현황 조회가 가능한지 확인합니다. 프로그램 종료, 로그아웃, 계좌 비밀번호 "
            "요구, 화면 차단이 발견되면 잡을 실패시켜 카카오톡으로 알립니다. 자료는 저장하지 않습니다."
        ),
        "steps": (
            "관리자 권한으로 H-able 창과 로그인 상태 확인",
            "[1285] 총자산현황 조회 가능 여부 검사",
            "준비되지 않았으면 1분 뒤 재시도 후 카카오 경고",
        ),
        "result": "18:30 수집 가능 여부 또는 조치가 필요한 오류",
        "schedules": (
            {"description": "금융자산 수집 30분 전", "cron": "평일 18:00"},
        ),
    },
    {
        "name": "stock_daily_job",
        "title": "금융자산 일일 수집",
        "category": "금융자산",
        "purpose": "KB증권 계좌와 직접 입력 자산을 하루 기준으로 모아 비중·성과 화면을 갱신합니다.",
        "method": (
            "관리자 권한으로 H-able 화면을 조작해 [1285] 잔고, [0112] 최근 7일 거래내역, "
            "[0354] 최근 1년 계좌별 성과를 읽어 Django API로 보냅니다. 이어서 Yahoo Finance와 "
            "Upbit의 공개 일봉을 갱신하고, admin에 입력한 코인 등의 수량에 당일 시세를 붙입니다. "
            "이 잡은 화면 데이터만 갱신하며 금융자산 카카오 요약은 자동 발송하지 않습니다."
        ),
        "steps": (
            "H-able [1285]에서 5개 계좌 잔고·보유종목 수집",
            "[0112] 최근 거래와 [0354] 1년 계좌 성과 수집",
            "Django API를 거쳐 PostgreSQL에 멱등 저장",
            "Yahoo Finance·Upbit 일봉과 직접 입력 자산의 당일 평가액 갱신",
        ),
        "result": "금융자산 비중·리밸런싱 및 수익률·MDD 화면의 최신 데이터",
        "schedules": (
            {"description": "장 마감 후 H-able 수집 → 외부 시세 연동", "cron": "평일 18:30"},
        ),
    },
    {
        "name": "scan_job",
        "title": "네이버 부동산 매물 스캔",
        "category": "부동산",
        "purpose": "네이버 관심단지의 현재 매물을 읽어 조건 충족·급매·신규 여부를 갱신합니다.",
        "method": (
            "리포트 서버를 먼저 확인한 다음, Windows Edge의 로그인 세션(CDP 9222)에 "
            "연결해 네이버 부동산 관심단지를 순회합니다. 화면에서 읽은 매물 원본을 Django의 "
            "/api/scans/로 보내면 Django가 PostgreSQL에 저장하고 가격·면적·층·타입 조건을 판정합니다. "
            "새 급매 또는 신규 알림 대상이 있으면 이 저장 과정에서 카카오톡을 보냅니다."
        ),
        "steps": (
            "report-site 및 PostgreSQL 상태 확인",
            "로그인된 Edge로 네이버 부동산 관심단지와 매물 화면 수집",
            "수집 원본 전량을 /api/scans/로 전달",
            "Django가 조건 판정·현재 매물 갱신·필요한 카카오 알림 처리",
        ),
        "result": "부동산 매물·관측 이력과 급매/신규 알림 결과",
        "schedules": (
            {"description": "서버 확인 → 네이버 관심단지 수집", "cron": "매일 07:00·12:00·17:00"},
        ),
    },
    {
        "name": "morning_report_job",
        "title": "아침 부동산 리포트 발송",
        "category": "부동산",
        "purpose": "아침 최신 매물 전체를 한 번 점검한 뒤 카카오톡 요약과 웹 링크를 발송합니다.",
        "method": (
            "PostgreSQL에서 당일 07:00 이후 성공한 스캔을 찾습니다. 없으면 scan_job과 같은 "
            "네이버 수집을 다시 실행합니다. 이후 Django의 send_digest가 활성 매물을 DB에서 읽고, "
            "kakao-notifier를 통해 텍스트 메시지를 보냅니다. 공개 웹이 같은 최신 데이터를 "
            "서빙할 때만 매물 리포트·가격 통계 버튼을 붙입니다."
        ),
        "steps": (
            "report-site와 당일 07:00 이후 성공 스캔 확인",
            "최신 스캔이 없을 때만 네이버 부동산 재수집",
            "Django send_digest가 PostgreSQL의 활성 매물 전체를 요약",
            "카카오 API로 텍스트와 매물 리포트·가격 통계 버튼 발송",
        ),
        "result": "당일 최신 부동산 카카오 리포트와 발송 근거 메타데이터",
        "schedules": (
            {"description": "최신 수집 확인·필요 시 재수집 → 전체 리포트", "cron": "매일 08:00"},
        ),
    },
    {
        "name": "restart_report_site_job",
        "title": "리포트 서버 재시작",
        "category": "운영",
        "purpose": "Django 코드를 변경한 뒤 실행 중인 웹 서버가 새 코드를 읽도록 교체합니다.",
        "method": (
            "restart-site.ps1이 8000번 포트의 기존 Python/Waitress 프로세스를 종료하고 "
            "run-site.ps1을 백그라운드로 다시 시작합니다. 이후 API가 정상 응답하는지 확인합니다. "
            "PostgreSQL이나 Dagster 자체는 재시작하지 않습니다."
        ),
        "steps": (
            "8000번 포트의 기존 report-site 프로세스 확인·종료",
            "새 Waitress 프로세스로 Django 기동",
            "API 상태 확인이 통과하면 완료",
        ),
        "result": "새 코드가 반영된 웹 리포트 서버",
        "schedules": (
            {"description": "리포트 서버 재시작", "cron": "수동 실행 (Dagster UI)"},
        ),
    },
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
