# Run the Dagster webserver + daemon that drive this repo's schedule.
#
# Native Windows process - no WSL. This is the whole point of this directory
# existing alongside the parked airflow/dags/ plan; see
# .agent/PROJECT_STATE.md, "Active Work: Dagster로 스케줄 구동".
#
# Binds to 127.0.0.1 only. Nothing about this server is meant to be reachable
# outside this PC, unlike the Tailscale Funnel-exposed report site.
#
# Double-click run-dagster.bat to launch this script.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

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

# Silences dagster's "no dagster.yaml found" warning on every startup and
# opts out of the anonymous usage telemetry Dagster sends by default - this
# is a personal single-PC deployment, not something to phone home from.
$ConfigFile = Join-Path $DataDir 'dagster.yaml'
if (-not (Test-Path $ConfigFile)) {
    "telemetry:`n  enabled: false`n" | Set-Content -Path $ConfigFile -Encoding utf8
}

Write-Host "Dagster webserver: http://127.0.0.1:3000" -ForegroundColor Green
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
