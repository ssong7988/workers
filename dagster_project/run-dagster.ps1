# Run the Dagster webserver + daemon that drive this repo's schedule.
#
# Native Windows process - no WSL. This is the whole point of this directory
# existing alongside the parked airflow/dags/ plan; see
# .agent/PROJECT_STATE.md, "Active Work: Dagster로 스케줄 구동".
#
# Binds to 127.0.0.1 only. Tailscale Funnel exposes it through the report
# site's HTTPS origin below the common namespace and the same optional token;
# the prefix must therefore be present in Dagster's generated asset and
# GraphQL URLs as well as in Funnel routing.
#
# Double-click run-dagster.bat to launch this script.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# This project's own venv, so unlike the other run-*.ps1 scripts it does not
# dot-source load-env.ps1 - but the logging helper lives at the repo root
# the same way.
. (Join-Path $Root '..\start-logging.ps1')
Start-AppLog -App 'dagster_project'

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`n" +
          "Create it first:`n" +
          "  py -3.11 -m venv dagster_project\.venv`n" +
          "  dagster_project\.venv\Scripts\python.exe -m pip install -r dagster_project\requirements.txt"
}

# DAGSTER_HOME holds run history and Dagster's own SQLite metadata - kept
# inside this directory (gitignored, like report-site/data/) rather than a
# user-profile default so it is obvious where it lives and easy to wipe.
$DataDir = Join-Path $Root 'data'
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}
$env:DAGSTER_HOME = $DataDir

# Reuse Django's optional path token instead of duplicating configuration.
# Empty means /common/dagster/console; a value means
# /<TOKEN>/common/dagster/console.
$ReportPathToken = $env:REPORT_PATH_TOKEN
if ([string]::IsNullOrWhiteSpace($ReportPathToken)) {
    $ReportEnv = Join-Path $Root '..\report-site\.env'
    if (Test-Path -LiteralPath $ReportEnv) {
        $TokenLine = Get-Content -LiteralPath $ReportEnv -Encoding utf8 |
            Where-Object { $_ -match '^\s*REPORT_PATH_TOKEN\s*=' } |
            Select-Object -Last 1
        if ($TokenLine) {
            $ReportPathToken = ($TokenLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
        }
    }
}
$ReportPathToken = ([string]$ReportPathToken).Trim().Trim('/')
if ($ReportPathToken.Contains('/') -or $ReportPathToken.Contains('\')) {
    throw 'REPORT_PATH_TOKEN cannot contain path separators.'
}
$DagsterPathPrefix = if ([string]::IsNullOrWhiteSpace($ReportPathToken)) {
    '/common/dagster/console'
} else {
    "/$ReportPathToken/common/dagster/console"
}
$env:DAGSTER_WEBSERVER_PATH_PREFIX = $DagsterPathPrefix

# Run/event-log/schedule storage lives in the same PostgreSQL database
# report-site uses (its own "dagster" schema - see dagster.yaml), not the
# SQLite files Dagster falls back to with no `storage:` block. The password
# is read from report-site/.env the same way REPORT_PATH_TOKEN is above, so
# it is never duplicated into a second .env: dagster.yaml only references
# the env var name, never the value itself.
$ReportEnvForPassword = Join-Path $Root '..\report-site\.env'
$PgPassword = $null
if (Test-Path -LiteralPath $ReportEnvForPassword) {
    $PgPasswordLine = Get-Content -LiteralPath $ReportEnvForPassword -Encoding utf8 |
        Where-Object { $_ -match '^\s*POSTGRES_PASSWORD\s*=' } |
        Select-Object -Last 1
    if ($PgPasswordLine) {
        $PgPassword = ($PgPasswordLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
    }
}
if ([string]::IsNullOrEmpty($PgPassword)) {
    throw "POSTGRES_PASSWORD not found in report-site\.env - Dagster's run storage needs it to reach PostgreSQL."
}
$env:DAGSTER_PG_PASSWORD = $PgPassword

# Silences dagster's "no dagster.yaml found" warning on every startup and
# opts out of the anonymous usage telemetry Dagster sends by default - this
# is a personal single-PC deployment, not something to phone home from. Also
# points run/event-log/schedule storage at PostgreSQL (see comment above).
# Rewritten on every launch, so a change here actually reaches the running
# instance; hand edits to data/dagster.yaml do not survive a restart.
#
# `timezone=UTC` is not cosmetic. This database's default TimeZone is
# Asia/Seoul, and the columns PostgreSQL fills from its own
# CURRENT_TIMESTAMP default (runs.create_timestamp, job_ticks.*, ...) then
# hold KST wall-clock time, which Dagster reads back as UTC - every run
# lands 9 hours in the future, so the Overview timeline draws nothing while
# the Runs list still looks fine. SQLite never showed this because its
# CURRENT_TIMESTAMP is always UTC. Scoped to Dagster's own connections so
# Django (which pins UTC per session itself) is untouched.
$ConfigFile = Join-Path $DataDir 'dagster.yaml'
@"
telemetry:
  enabled: false

storage:
  postgres:
    postgres_db:
      username: property_report
      password:
        env: DAGSTER_PG_PASSWORD
      hostname: 127.0.0.1
      db_name: property_report
      port: 5432
      params:
        options: "-c search_path=dagster -c timezone=UTC"
"@ | Set-Content -Path $ConfigFile -Encoding utf8

Write-Host "Dagster webserver: http://127.0.0.1:3000$DagsterPathPrefix/runs" -ForegroundColor Green
Write-Host "DAGSTER_HOME: $DataDir"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

# `dagster dev` prints a "superseded, use 'dg dev' instead" notice - accepted
# for now (see PROJECT_STATE.md): `dg` ships in a separate package this
# install does not have, and the command used here was smoke-tested directly
# (webserver up, a real job executed end to end, the failure hook verified)
# rather than assumed from docs.
& $Python -m dagster dev -f definitions.py --host 127.0.0.1 --port 3000
exit $LASTEXITCODE
