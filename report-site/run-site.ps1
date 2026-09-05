# Run the property report application.
#
# Serves the report from PostgreSQL on every request, so there is no build or
# deploy step: a scan's result shows up on refresh. This only starts the local
# server on 127.0.0.1:8000; making it reachable from outside this PC is a
# separate one-time step (`tailscale funnel --bg 8000`), documented in
# .docs/RUNBOOK.md.
#
# The scanner (real-estate-finder) posts to this server's API, so it has to be
# running before a scan, not only when someone opens the report.
#
# Double-click run-site.bat to launch this script.

param([switch]$LoggedChild)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not $LoggedChild) {
    $LogPython = Join-Path $Root '..\real-estate-finder\.venv\Scripts\python.exe'
    & $LogPython (Join-Path $Root '..\run-logged.py') --app report-site --health-port 8000 --health-path /property/report/ -- powershell.exe -NoProfile -ExecutionPolicy Bypass -File $MyInvocation.MyCommand.Path -LoggedChild
    exit $LASTEXITCODE
}
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

# Share KAKAO_REPORT_URL so this window can print the same public link Kakao
# cards use.
. (Join-Path $Root '..\load-env.ps1')

# The outer run-logged.py captures startup checks and server output live.

$Python = Join-Path $Root '..\real-estate-finder\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in real-estate-finder/README.md first."
}

$EnvFile = Join-Path $Root '.env'
if (-not (Test-Path $EnvFile)) {
    throw "report-site\.env not found. Copy .env.example to .env and fill it in first."
}

Write-Host "Checking Django configuration..." -ForegroundColor Cyan
& $Python manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django configuration check failed." }

# The database is the application's storage now, so an unapplied migration is
# a broken server rather than a stale page.
Write-Host "Checking database migrations..." -ForegroundColor Cyan
& $Python manage.py migrate --check
if ($LASTEXITCODE -ne 0) {
    throw @"
The database is not up to date (or is unreachable).
Start PostgreSQL, check report-site\.env, then run:
    ..\real-estate-finder\.venv\Scripts\python.exe manage.py migrate
"@
}

# Only the admin needs these; waitress serves no static files on its own and
# this never runs with DEBUG on. Cheap enough to keep automatic so it cannot
# be forgotten after a Django upgrade.
& $Python manage.py collectstatic --noinput --verbosity 0
if ($LASTEXITCODE -ne 0) { throw "collectstatic failed." }

$Token = ($env:REPORT_PATH_TOKEN)
if (-not $Token) {
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith('REPORT_PATH_TOKEN=')) {
            $Token = $trimmed.Substring('REPORT_PATH_TOKEN='.Length).Trim()
        }
    }
}
$Token = ([string]$Token).Trim().Trim('"').Trim("'").Trim('/')
if ($Token.Contains('/') -or $Token.Contains('\')) {
    throw 'REPORT_PATH_TOKEN cannot contain path separators.'
}

Write-Host ""
$RoutePrefix = if ([string]::IsNullOrWhiteSpace($Token)) { '' } else { "$Token/" }
Write-Host "Local report:  http://127.0.0.1:8000/${RoutePrefix}property/report/" -ForegroundColor Green
Write-Host "Local stats:   http://127.0.0.1:8000/${RoutePrefix}property/statistics/" -ForegroundColor Green
Write-Host "Local Dagster: http://127.0.0.1:8000/${RoutePrefix}common/dagster/" -ForegroundColor Green
Write-Host "Local admin:   http://127.0.0.1:8000/${RoutePrefix}property/admin/" -ForegroundColor Green
if ($env:KAKAO_REPORT_URL) {
    Write-Host "Public report: $env:KAKAO_REPORT_URL" -ForegroundColor Green
} else {
    Write-Host "Public report: not set yet (KAKAO_REPORT_URL) - see .docs/RUNBOOK.md for the Tailscale Funnel setup." -ForegroundColor Yellow
}
Write-Host "Press Ctrl+C to stop."
Write-Host ""

& $Python -m waitress --listen=127.0.0.1:8000 report_site.wsgi:application
exit $LASTEXITCODE
