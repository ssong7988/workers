"""8시: send the full report, retrying the morning scan first if it never landed.

Maps to PROJECT_STATE.md request #3. What matters is whether there is fresh
data to send, not whether the 7시 `scan` DAG run happened to succeed -
`manage.py scan_status` answers that straight from the `Scan` table (a scan
run by hand counts too; see PROJECT_STATE.md for why Airflow's own run
metadata was rejected as the source of truth here).
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

from _common import DEFAULT_ARGS, run_manage, run_ps1

with DAG(
    dag_id="morning_digest",
    description="아침 리포트 발송 (8시, 필요하면 수집 재시도)",
    default_args=DEFAULT_ARGS,
    schedule="0 8 * * *",
    start_date=pendulum.datetime(2026, 9, 4, tz="Asia/Seoul"),
    catchup=False,
    max_active_runs=1,
    tags=["property-report"],
) as dag:
    ensure_fresh_scan = BashOperator(
        task_id="ensure_fresh_scan",
        # scan_status exits 0 (and this does nothing further) when a
        # successful scan already ran today at or after 07:00; otherwise it
        # exits 1, `||` catches that, and this reruns the scan in place
        # before send_digest gets a chance to run on stale data.
        bash_command=(
            f"{run_manage('scan_status', '--since=07:00')} || "
            f"{run_ps1('real-estate-finder/run-scan.ps1')}"
        ),
        execution_timeout=timedelta(minutes=20),
    )
    send_digest = BashOperator(
        task_id="send_digest",
        bash_command=run_ps1("real-estate-finder/send-report.ps1"),
        execution_timeout=timedelta(minutes=3),
    )
    ensure_fresh_scan >> send_digest
