"""One Dagster pipeline for the report server, scan, and morning report.

Runs natively on this Windows machine - no WSL required. That is the whole
reason this exists instead of the Airflow plan in `airflow/dags/`: Airflow
needs WSL2, and WSL2 needs a CPU virtualization bit this PC's firmware has
off with no software way to flip it (see .agent/PROJECT_STATE.md, "막힌
지점"). Every op below shells out to a script or `manage.py` command that
already exists and already works; this file only adds scheduling, retries,
and failure alerting on top - same shape as the parked Airflow DAGs, but
without any interop layer, since this process already runs natively on
Windows.

Load with: `dagster dev -f definitions.py --host 127.0.0.1 --port 3000`
(see run-dagster.ps1, which also supplies the webserver path prefix). Binding
to 127.0.0.1 still matters: the webserver is reachable externally only through
the explicit Tailscale Funnel path, not as a directly listening LAN service.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import dagster as dg

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_ESTATE_FINDER = REPO_ROOT / "real-estate-finder"
REPORT_SITE = REPO_ROOT / "report-site"
PYTHON_EXE = REAL_ESTATE_FINDER / ".venv" / "Scripts" / "python.exe"
MANAGE_PY = REPORT_SITE / "manage.py"

RETRY_POLICY = dg.RetryPolicy(max_retries=1, delay=300)


def _run_powershell(script_path: Path, *, timeout: float) -> None:
    """Run one of this repo's `.ps1` scripts and raise if it fails.

    Never point this at a `.bat` wrapper: every one of them ends in
    `pause >nul` for the person double-clicking it, and an unattended run
    hitting that on any failure path would hang until the timeout instead of
    failing cleanly. (Found and fixed for ensure-site.ps1 while writing the
    Airflow version of this same plan - see PROJECT_STATE.md.)
    """
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script_path.name} 실패 (종료 코드 {result.returncode})")


def _run_manage(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    """Run one `manage.py` command directly - no PowerShell layer needed.

    Unlike the Airflow/WSL version of this plan, there is no interop
    boundary to cross: this process already runs as a native Windows
    process, so subprocess's own returncode already is manage.py's real
    exit code, with nothing to lose in translation (the Airflow DAGs need an
    explicit `exit $LASTEXITCODE` for exactly this reason - not needed here).
    """
    return subprocess.run(
        [str(PYTHON_EXE), str(MANAGE_PY), *args],
        cwd=REPORT_SITE,
        timeout=timeout,
    )


@dg.op(retry_policy=RETRY_POLICY)
def ensure_site() -> None:
    """리포트 서버 생존 확인, 죽어 있으면 기동."""
    _run_powershell(REPORT_SITE / "ensure-site.ps1", timeout=90)


@dg.op(
    retry_policy=RETRY_POLICY,
    ins={"start": dg.In(dg.Nothing)},
    config_schema={"mode": dg.Field(str, default_value="skip")},
)
def scan_step(context) -> None:
    """시간대에 따라 수집을 생략, 실행, 또는 최신 여부 확인 후 실행한다.

    Edge와 네이버 로그인 세션이 Windows 데스크톱에 있어야 한다 - 세션이
    잠겨 있으면 사람이 로그인할 때까지 매달린다. 자동화할 수 없는 지점이고
    (PROJECT_STATE.md 위험 절 참고), 타임아웃 후 재시도 1회, 그래도 실패하면
    failure hook이 카톡으로 알리는 것이 유일한 대응이다.
    """
    mode = context.op_config["mode"]
    if mode == "skip":
        context.log.info("이 시간대에는 서버 확인만 합니다.")
        return
    if mode == "run":
        _run_powershell(REAL_ESTATE_FINDER / "run-scan.ps1", timeout=1200)
        return
    if mode == "ensure_fresh":
        result = _run_manage("scan_status", "--since=07:00", timeout=30)
        if result.returncode == 0:
            context.log.info("오늘 07:00 이후 성공한 수집이 있어 재수집하지 않습니다.")
            return
        _run_powershell(REAL_ESTATE_FINDER / "run-scan.ps1", timeout=1200)
        return
    raise ValueError(f"지원하지 않는 scan_step mode: {mode}")


@dg.op(
    retry_policy=RETRY_POLICY,
    ins={"start": dg.In(dg.Nothing)},
    config_schema={"enabled": dg.Field(bool, default_value=False)},
)
def report_step(context) -> None:
    """활성 매물 전체 발송. 아침 리포트 시간 외에는 명시적으로 생략한다."""
    if not context.op_config["enabled"]:
        context.log.info("이 시간대에는 리포트를 보내지 않습니다.")
        return
    _run_powershell(REAL_ESTATE_FINDER / "send-report.ps1", timeout=180)


@dg.op(retry_policy=RETRY_POLICY)
def restart_report_site() -> None:
    """report-site 프로세스를 종료하고 새로 띄운다.

    report-site(Django, f/e·b/e 구분 없이 waitress 한 프로세스) 코드를
    바꾼 뒤 수동으로 실행하는 용도다. real-estate-finder는 스캔·리포트
    전송이 매번 새 subprocess로 도니 재시작이 필요 없다(파일 맨 위 설명
    참고).
    """
    _run_powershell(REPORT_SITE / "restart-site.ps1", timeout=150)


@dg.failure_hook
def alert_on_failure(context: dg.HookContext) -> None:
    """실패를 요약해 카카오톡으로 보낸다. 재시도를 다 쓴 뒤에만 호출된다.

    스케줄러 자신의 프로세스 안에서 도는 훅이라 태스크가 아니라 여기서
    직접 subprocess를 부른다. send_alert 자체가 실패해도(예: 리포트 서버도
    같이 죽어 있는 경우) 원래 실패를 더 키우지 않도록 예외를 삼킨다 -
    Dagster UI가 실제로 무슨 일이 있었는지의 원천이고, 이건 그 위에 얹은
    최선의 페이징일 뿐이다.
    """
    summary = f"{context.job_name}/{context.op.name} 실패: {context.op_exception}"
    try:
        _run_manage("send_alert", summary, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        context.log.error(f"send_alert도 실패했습니다: {exc}")


@dg.job(hooks={alert_on_failure})
def property_pipeline_job() -> None:
    """서버 확인 → 필요 시 수집 → 필요 시 리포트의 단일 실행 그래프."""
    report_step(start=scan_step(start=ensure_site()))


@dg.job(hooks={alert_on_failure})
def restart_report_site_job() -> None:
    """report-site 코드를 바꾼 뒤 수동으로 실행하는 재시작 전용 job.

    init 목적의 단발성 작업이라 스케줄에는 올리지 않는다 - Dagster UI
    (`/dagster/console/`)에서 필요할 때 Launch Run으로 실행한다.
    """
    restart_report_site()


server_only_schedule = dg.ScheduleDefinition(
    name="server_only_schedule",
    job=property_pipeline_job,
    # 7·8·12·17시는 아래 전용 스케줄이 같은 서버 확인부터 시작한다.
    cron_schedule="0 0-6,9-11,13-16,18-23 * * *",
    execution_timezone="Asia/Seoul",
    default_status=dg.DefaultScheduleStatus.RUNNING,
    run_config={
        "ops": {
            "scan_step": {"config": {"mode": "skip"}},
            "report_step": {"config": {"enabled": False}},
        }
    },
)
scan_schedule = dg.ScheduleDefinition(
    name="scan_schedule",
    job=property_pipeline_job,
    cron_schedule="0 7,12,17 * * *",
    execution_timezone="Asia/Seoul",
    default_status=dg.DefaultScheduleStatus.RUNNING,
    run_config={
        "ops": {
            "scan_step": {"config": {"mode": "run"}},
            "report_step": {"config": {"enabled": False}},
        }
    },
)
morning_report_schedule = dg.ScheduleDefinition(
    name="morning_report_schedule",
    job=property_pipeline_job,
    cron_schedule="0 8 * * *",
    execution_timezone="Asia/Seoul",
    default_status=dg.DefaultScheduleStatus.RUNNING,
    run_config={
        "ops": {
            "scan_step": {"config": {"mode": "ensure_fresh"}},
            "report_step": {"config": {"enabled": True}},
        }
    },
)

defs = dg.Definitions(
    jobs=[property_pipeline_job, restart_report_site_job],
    schedules=[server_only_schedule, scan_schedule, morning_report_schedule],
)
