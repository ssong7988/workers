"""Shared plumbing for this repo's Airflow DAGs.

Airflow runs in WSL2 and drives the Windows side of this machine through
interop rather than reimplementing any of it - see .agent/PROJECT_STATE.md,
"Planned Work: Airflow로 스케줄 이관", for why. Every task below ultimately
shells out to a script or `manage.py` command that already exists and already
works; nothing here talks to PostgreSQL, Naver, or Kakao directly.

**Not yet run against a real Airflow instance.** Written ahead of the WSL2
install (blocked on BIOS access - see PROJECT_STATE.md's "막힌 지점"), so the
Task SDK import paths and callback context keys below are believed correct
for Airflow 3.x from documentation, not confirmed against a live scheduler.
Re-check them once Airflow is actually installed, before trusting the
schedule unattended.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import timedelta

from airflow.sdk import Variable

log = logging.getLogger(__name__)

# Overridable via an Airflow Variable of the same name, in case the repo ever
# moves or this is set up on a different machine.
WSL_ROOT = Variable.get(
    "wsl_repo_root",
    default="/mnt/c/Users/userpc/Documents/Codex/2026-09-01/d/outputs",
)


def _win(relative_path: str) -> str:
    """A `$(wslpath -w ...)` expression for a repo-relative path.

    WSL interop does not translate paths inside arguments: handing a Windows
    executable "/mnt/c/..." does not resolve. Every command below converts
    to a native "C:\\..." path first.
    """
    wsl_path = f"{WSL_ROOT}/{relative_path}"
    return f'$(wslpath -w "{wsl_path}")'


def run_ps1(relative_path: str) -> str:
    """Bash command that runs one of this repo's existing `.ps1` scripts.

    Never point a task at the `.bat` wrappers instead: they end in
    `pause >nul` so a person double-clicking one can read the result before
    the window closes. An unattended task hitting that on any failure path
    would hang forever rather than fail - `ensure-site.ps1` used to make
    exactly this mistake starting `run-site.bat`; fixed alongside this DAG
    work (see PROJECT_STATE.md).
    """
    return f"powershell.exe -NoProfile -ExecutionPolicy Bypass -File {_win(relative_path)}"


def run_manage(*args: str) -> str:
    """Bash command that runs one `report-site/manage.py` command directly.

    No wrapper script needed: `manage.py`'s settings module resolves
    `BASE_DIR` from its own file location, not the caller's working
    directory, so this works from any WSL starting point.

    PowerShell does not forward a native command's exit code as its own
    process exit code when invoked via `-Command` (unlike `-File`, where a
    script's own `exit`/`throw` already propagates - relied on elsewhere in
    this repo, e.g. run-scan.bat's `%ERRORLEVEL%` check). Without the
    trailing `exit $LASTEXITCODE` here, a failing `manage.py` command would
    still report success to Airflow.
    """
    python_exe = _win("real-estate-finder/.venv/Scripts/python.exe")
    manage_py = _win("report-site/manage.py")
    quoted_args = " ".join(f"'{arg}'" for arg in args)
    inner = f"& {python_exe} {manage_py} {quoted_args}; exit $LASTEXITCODE"
    return f'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "{inner}"'


def alert_on_failure(context: dict) -> None:
    """`on_failure_callback`: summarize the failure and send it to Kakao.

    Fires once a task has exhausted its retries, not on every attempt. Runs
    as plain Python in the scheduler/worker process rather than as a task of
    its own, so it shells out itself instead of returning a bash_command.
    Swallows its own failure (e.g. the report server being down too) rather
    than compounding the original one - Airflow's UI is still the source of
    truth for what actually happened; this is best-effort paging on top.
    """
    task_instance = context["task_instance"]
    exception = context.get("exception")
    summary = (
        f"{task_instance.dag_id}/{task_instance.task_id} 실패 "
        f"(시도 {task_instance.try_number}): {exception}"
    )
    command = run_manage("send_alert", summary)
    try:
        result = subprocess.run(
            ["bash", "-c", command], capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            log.error(
                "send_alert도 실패했습니다 (%s): %s",
                result.returncode,
                result.stderr.strip(),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.error("send_alert 호출 자체가 실패했습니다: %s", exc)


DEFAULT_ARGS = {
    "owner": "property-report",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": alert_on_failure,
}
