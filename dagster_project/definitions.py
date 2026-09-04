"""The report server, the scan, and the morning report as Dagster assets.

Runs natively on this Windows machine - no WSL required. That is the whole
reason this exists instead of the Airflow plan in `airflow/dags/`: Airflow
needs WSL2, and WSL2 needs a CPU virtualization bit this PC's firmware has
off with no software way to flip it (see .agent/PROJECT_STATE.md, "막힌
지점"). Each app keeps its own virtual environment, so Dagster launches the
app's Python command as a child process instead of importing Playwright or
Django into Dagster's dependency tree. PowerShell is reserved for Windows
process lifecycle work such as starting or restarting the report server.

**Assets, not plain ops (changed 2026-09-04).** This used to be one
`property_pipeline_job` whose three steps were switched on and off by config
(`scan_step.mode="skip"`, `report_step.enabled=False`) so that three
schedules could share one graph. Assets express the same thing better: what
each schedule wants is a *selection* of the chain

    naver_listings --> morning_report

so "this hour, only check the server" is a job that runs the server-check op
alone, rather than a run that executes all three steps and has two of them
decide to do nothing. Two config knobs disappeared with the change, the
Dagster UI's Catalog and Lineage screens now show what the pipeline actually
produces, and every scan attaches its own counts to the materialization.

**Why the server check is not its own asset.** It briefly was, and that was
wrong: an asset is a thing that *exists* afterwards, and "the server
answered" leaves nothing behind - it materialized with permanently empty
metadata, the only one of the three that did. It is now `ensure_site_op`,
a plain op used in two places: as the whole of `server_check_job`, and as
the first step inside `naver_listings`. A `@dg.graph_asset` is what makes
that possible - a plain op cannot be the upstream dependency of an asset
(`@dg.asset(deps=[some_op])` is rejected), but ops composed *inside* an
asset run in order just fine. The cost is that the server check no longer
appears as its own node in Catalog/Lineage; it shows up as the
`naver_listings.ensure_site_op` step in every run, and inside the asset's
own graph view.

Load with: `dagster dev -f definitions.py --host 127.0.0.1 --port 3000`
(see run-dagster.ps1, which also supplies the webserver path prefix). Binding
to 127.0.0.1 still matters: the webserver is reachable externally only through
the explicit Tailscale Funnel path, not as a directly listening LAN service.

Editing this file has no effect until Dagster is restarted - it is read once
at process start. Use `dagster_project/restart-dagster.bat`, never a Dagster
job (a job that kills its own process aborts its own run).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import dagster as dg

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_ESTATE_FINDER = REPO_ROOT / "real-estate-finder"
REPORT_SITE = REPO_ROOT / "report-site"
PYTHON_EXE = REAL_ESTATE_FINDER / ".venv" / "Scripts" / "python.exe"
MANAGE_PY = REPORT_SITE / "manage.py"

RETRY_POLICY = dg.RetryPolicy(max_retries=1, delay=300)
GROUP = "property_report"


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


def _run_manage(
    *args: str, timeout: float = 60, capture: bool = False
) -> subprocess.CompletedProcess:
    """Run one `manage.py` command directly - no PowerShell layer needed.

    Unlike the Airflow/WSL version of this plan, there is no interop
    boundary to cross: this process already runs as a native Windows
    process, so subprocess's own returncode already is manage.py's real
    exit code, with nothing to lose in translation (the Airflow DAGs need an
    explicit `exit $LASTEXITCODE` for exactly this reason - not needed here).

    `capture=True` decodes as UTF-8 with `errors="replace"`. Only ASCII
    payloads are ever parsed out of it (see `_scan_metadata`), so Korean
    console text that comes back mangled is not this function's problem -
    but it must never be allowed to raise.
    """
    return subprocess.run(
        [str(PYTHON_EXE), str(MANAGE_PY), *args],
        cwd=REPORT_SITE,
        timeout=timeout,
        capture_output=capture,
        text=capture,
        encoding="utf-8" if capture else None,
        errors="replace" if capture else None,
    )


def _run_finder(*args: str, timeout: float = 1200) -> None:
    """Run a collector command in its own venv and stream output to Dagster."""
    result = subprocess.run(
        [str(PYTHON_EXE), "-u", "-m", "real_estate_finder", *args],
        cwd=REAL_ESTATE_FINDER,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"real_estate_finder {' '.join(args)} 실패 (종료 코드 {result.returncode})"
        )


def _require_manage(*args: str, timeout: float = 60) -> None:
    """Run a Django command and turn its exit code into an op failure."""
    result = _run_manage(*args, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"manage.py {' '.join(args)} 실패 (종료 코드 {result.returncode})"
        )


def _scan_metadata(context) -> dict:
    """Ask Django what the latest successful scan of today actually produced.

    The collector runs in its own venv as a child Python process, so Dagster
    intentionally learns only its exit code. Without this the Catalog would
    show a name and a timestamp and nothing else. Django already records the
    counts on every `Scan` row; this reads them back with `scan_status --json`.

    Best-effort by design: a materialization must not fail because the
    decoration around it failed. On any problem the asset still counts as
    materialized, with the reason in place of the numbers.
    """
    try:
        result = _run_manage(
            "scan_status", "--since=00:00", "--json", timeout=30, capture=True
        )
        line = next(
            line
            for line in reversed((result.stdout or "").splitlines())
            if line.startswith("{")
        )
        payload = json.loads(line)
    except (OSError, subprocess.TimeoutExpired, StopIteration, ValueError) as exc:
        context.log.warning(f"수집 메타데이터를 읽지 못했습니다: {exc}")
        return {"메타데이터": "읽지 못함"}

    scan = payload.get("scan")
    if not scan:
        return {"메타데이터": "오늘 성공한 수집 기록이 없음"}
    return {
        "수집 시작": scan["started_at"],
        "수집 수": scan["collected"],
        "조건 충족 수": scan["matched"],
        "급매 수": scan["urgent"],
        "제외 수": scan["excluded"],
    }


@dg.op(retry_policy=RETRY_POLICY)
def ensure_site_op() -> None:
    """리포트 서버 생존 확인, 죽어 있으면 기동.

    두 곳에서 쓴다 - `server_check_job` 전체이자, `naver_listings` 안의 첫
    단계다. 스캔은 데이터를 보낼 곳이 없으면 의미가 없기 때문이다.
    `ensure-site.ps1`은 멱등이라 이미 떠 있으면 아무것도 하지 않는다.

    asset이 아니라 op인 이유: 이 단계가 끝나도 남는 산출물이 없다.
    """
    _run_powershell(REPORT_SITE / "ensure-site.ps1", timeout=90)


@dg.op(
    retry_policy=RETRY_POLICY,
    ins={"start": dg.In(dg.Nothing)},
    config_schema={"mode": dg.Field(str, default_value="run")},
)
def run_scan_op(context) -> None:
    """네이버에서 매물을 수집해 PostgreSQL에 넣는다.

    모드는 둘뿐이다. 예전의 `skip`은 사라졌다 - "이 시간대에는 수집하지
    않는다"는 이제 이 op이 든 asset을 선택하지 않는 것으로 표현한다.

    - `run`: 무조건 수집한다.
    - `ensure_fresh`: 오늘 07:00 이후 성공한 수집이 있으면 그대로 두고,
      없을 때만 수집한다. 어느 쪽이든 "매물이 최신이다"라는 결과는 같으므로
      머티리얼라이즈는 두 경우 모두 성립한다.

    Edge와 네이버 로그인 세션이 Windows 데스크톱에 있어야 한다 - 세션이
    잠겨 있으면 사람이 로그인할 때까지 매달린다. 자동화할 수 없는 지점이고
    (PROJECT_STATE.md 위험 절 참고), 타임아웃 후 재시도 1회, 그래도 실패하면
    failure hook이 카톡으로 알리는 것이 유일한 대응이다.

    여기서 붙인 메타데이터가 `naver_listings` 머티리얼라이즈에 실린다 -
    graph_asset의 마지막 op 출력이 곧 asset의 출력이기 때문이다.
    """
    mode = context.op_config["mode"]
    skipped = False
    if mode == "ensure_fresh":
        if _run_manage("scan_status", "--since=07:00", timeout=30).returncode == 0:
            context.log.info("오늘 07:00 이후 성공한 수집이 있어 재수집하지 않습니다.")
            skipped = True
    elif mode != "run":
        raise ValueError(f"지원하지 않는 run_scan_op mode: {mode}")

    if not skipped:
        _run_finder("run-scan", timeout=1200)

    metadata = _scan_metadata(context)
    if skipped:
        metadata = {"재수집": "생략 (07:00 이후 성공한 수집 있음)", **metadata}
    context.add_output_metadata(metadata)


@dg.graph_asset(group_name="property_report", kinds={"python", "playwright"})
def naver_listings():
    """네이버 매물 원본. 살아 있는 리포트 서버를 확인한 뒤 수집한다.

    op 두 개를 묶은 graph_asset이다. 서버 확인이 별도 asset이 아니라 이
    안의 첫 단계인 이유는 파일 맨 위 설명 참고 - 서버가 응답했다는 것은
    산출물이 아니다. 실행하면 런 상세에 `naver_listings.ensure_site_op`,
    `naver_listings.run_scan_op` 두 step으로 보인다.
    """
    return run_scan_op(start=ensure_site_op())


@dg.asset(
    deps=[naver_listings],
    retry_policy=RETRY_POLICY,
    group_name=GROUP,
    kinds={"python", "django"},
)
def morning_report(context) -> dg.MaterializeResult:
    """활성 매물 전체를 카카오톡으로 발송한다.

    예전의 `enabled` 설정은 사라졌다 - "이 시간대에는 리포트를 보내지
    않는다"는 이제 이 asset을 선택하지 않는 것으로 표현한다. 메타데이터에는
    이 리포트가 어떤 수집을 근거로 나갔는지가 남는다.
    """
    _require_manage("send_digest", timeout=180)
    return dg.MaterializeResult(metadata=_scan_metadata(context))


@dg.op(retry_policy=RETRY_POLICY)
def restart_report_site() -> None:
    """report-site 프로세스를 종료하고 새로 띄운다.

    report-site(Django, f/e·b/e 구분 없이 waitress 한 프로세스) 코드를
    바꾼 뒤 수동으로 실행하는 용도다. real-estate-finder는 스캔·리포트
    전송이 매번 새 subprocess로 도니 재시작이 필요 없다(파일 맨 위 설명
    참고).

    산출물이 아니라 조작이라 asset이 아니라 op다 - 이걸 실행한다고 해서
    새로 만들어지는 것은 없다.
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


@dg.job(hooks={alert_on_failure}, description="리포트 서버만 확인한다.")
def server_check_job() -> None:
    """매시 정각의 서버 확인. asset을 만들지 않으므로 op job이다.

    `naver_listings` 안에서 쓰는 것과 **같은 op**을 재사용한다 - 확인 로직이
    두 벌로 갈라지지 않는다.
    """
    ensure_site_op()


scan_job = dg.define_asset_job(
    name="scan_job",
    selection=dg.AssetSelection.assets(naver_listings),
    description="서버 확인 후 매물을 수집한다.",
    hooks={alert_on_failure},
)
morning_report_job = dg.define_asset_job(
    name="morning_report_job",
    selection=dg.AssetSelection.assets(morning_report).upstream(),
    description="서버 확인 → 최신 수집 확인/재시도 → 전체 리포트 발송.",
    hooks={alert_on_failure},
)


@dg.job(hooks={alert_on_failure})
def restart_report_site_job() -> None:
    """report-site 코드를 바꾼 뒤 수동으로 실행하는 재시작 전용 job.

    init 목적의 단발성 작업이라 스케줄에는 올리지 않는다 - Dagster UI
    (`/common/dagster/console/`)에서 필요할 때 Launch Run으로 실행한다.
    """
    restart_report_site()


# graph_asset이라 설정 경로가 한 겹 깊다: asset 이름 아래 다시 ops가 온다.
def _scan_config(mode: str) -> dict:
    return {"ops": {"naver_listings": {"ops": {"run_scan_op": {"config": {"mode": mode}}}}}}


server_only_schedule = dg.ScheduleDefinition(
    name="server_only_schedule",
    job=server_check_job,
    # 7·8·12·17시는 아래 전용 스케줄이 같은 서버 확인부터 시작한다.
    cron_schedule="0 0-6,9-11,13-16,18-23 * * *",
    execution_timezone="Asia/Seoul",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
scan_schedule = dg.ScheduleDefinition(
    name="scan_schedule",
    job=scan_job,
    cron_schedule="0 7,12,17 * * *",
    execution_timezone="Asia/Seoul",
    default_status=dg.DefaultScheduleStatus.RUNNING,
    run_config=_scan_config("run"),
)
morning_report_schedule = dg.ScheduleDefinition(
    name="morning_report_schedule",
    job=morning_report_job,
    cron_schedule="0 8 * * *",
    execution_timezone="Asia/Seoul",
    default_status=dg.DefaultScheduleStatus.RUNNING,
    run_config=_scan_config("ensure_fresh"),
)

defs = dg.Definitions(
    assets=[naver_listings, morning_report],
    jobs=[server_check_job, scan_job, morning_report_job, restart_report_site_job],
    schedules=[server_only_schedule, scan_schedule, morning_report_schedule],
)
