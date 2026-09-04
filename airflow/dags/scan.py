"""7/12/17시: run one collection pass.

Maps to PROJECT_STATE.md request #2. Kakao already gets the urgent/new
listings without any help from this DAG - record_scan() sends that the
moment scan-once posts results, inside report-site's own transaction (see
properties/scanning.py). This DAG only has to get the browser scan running
on schedule; ensure_site goes first since a scan with no server to post its
results to is wasted motion.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

from _common import DEFAULT_ARGS, run_ps1

with DAG(
    dag_id="scan",
    description="매물 수집 (7/12/17시)",
    default_args=DEFAULT_ARGS,
    schedule="0 7,12,17 * * *",
    start_date=pendulum.datetime(2026, 9, 4, tz="Asia/Seoul"),
    catchup=False,
    max_active_runs=1,
    tags=["property-report"],
) as dag:
    ensure_site = BashOperator(
        task_id="ensure_site",
        bash_command=run_ps1("report-site/ensure-site.ps1"),
        execution_timeout=timedelta(minutes=3),
    )
    run_scan = BashOperator(
        task_id="run_scan",
        # Edge and the Naver login live on the Windows desktop session, so
        # this can stall waiting for a login nobody is there to complete.
        # There is no way to make that part unattended (PROJECT_STATE.md,
        # 위험 절) - a long timeout plus one retry, then the failure
        # callback pages a person, is the whole mitigation.
        bash_command=run_ps1("real-estate-finder/run-scan.ps1"),
        execution_timeout=timedelta(minutes=20),
    )
    ensure_site >> run_scan
