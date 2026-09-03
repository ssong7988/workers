# Run the property report server.
#
# Reads real-estate-finder/data/state.json on every request, so there is no
# build or deploy step: a scan's result shows up on refresh. This only starts
# the local server on 127.0.0.1:8000; making it reachable from outside this
# PC is a separate one-time step (`tailscale funnel --bg 8000`), documented
# in .agent/docs/RUNBOOK.md.
#
# Double-click run-site.bat to launch this script.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Share KAKAO_REPORT_URL so this window can print the same public link Kakao
# cards use.
. (Join-Path $Root '..\load-env.ps1')

$Python = Join-Path $Root '..\real-estate-finder\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in real-estate-finder/README.md first."
}

$EnvFile = Join-Path $Root '.env'
if (-not (Test-Path $EnvFile)) {
    throw "report-site\.env not found. Copy .env.example to .env and set REPORT_PATH_TOKEN first."
}

Write-Host "Checking Django configuration..." -ForegroundColor Cyan
& $Python manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django configuration check failed." }

$Token = ($env:REPORT_PATH_TOKEN)
if (-not $Token) {
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith('REPORT_PATH_TOKEN=')) {
            $Token = $trimmed.Substring('REPORT_PATH_TOKEN='.Length).Trim()
        }
    }
}

Write-Host ""
Write-Host "Local report:  http://127.0.0.1:8000/r/$Token/" -ForegroundColor Green
if ($env:KAKAO_REPORT_URL) {
    Write-Host "Public report: $env:KAKAO_REPORT_URL" -ForegroundColor Green
} else {
    Write-Host "Public report: not set yet (KAKAO_REPORT_URL) - see .agent/docs/RUNBOOK.md for the Tailscale Funnel setup." -ForegroundColor Yellow
}
Write-Host "Press Ctrl+C to stop."
Write-Host ""

& $Python -m waitress --listen=127.0.0.1:8000 report_site.wsgi:application
exit $LASTEXITCODE
