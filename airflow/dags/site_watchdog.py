"""Hourly: make sure the report server is up, and start it if it is not.

Maps to PROJECT_STATE.md request #1. The liveness check and the (if needed)
detached restart both already live in report-site/ensure-site.ps1 - this DAG
only has to run that on a schedule.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

from _common import DEFAULT_ARGS, run_ps1

with DAG(
    dag_id="site_watchdog",
    description="리포트 서버 생존 확인 및 자동 기동",
    default_args=DEFAULT_ARGS,
    schedule="0 * * * *",
    start_date=pendulum.datetime(2026, 9, 4, tz="Asia/Seoul"),
    catchup=False,
    max_active_runs=1,
    tags=["property-report"],
) as dag:
    BashOperator(
        task_id="ensure_site",
        bash_command=run_ps1("report-site/ensure-site.ps1"),
        execution_timeout=timedelta(minutes=3),
    )
