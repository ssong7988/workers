# Make sure the report server is running; start it if it is not.
#
# This is the piece run-site.ps1 cannot be, and run-scan.ps1's own check
# cannot replace: run-site.ps1 ends by blocking on waitress forever, so
# calling it directly from a scheduler task would never return. This script
# checks health first and only starts the server - detached - when it is
# actually down, so the caller gets an answer in seconds either way.
#
# Airflow's hourly site_watchdog DAG (see .agent/PROJECT_STATE.md, "Planned
# Work: Airflow로 스케줄 이관") calls this through WSL interop:
#   powershell.exe -File /mnt/c/.../report-site/ensure-site.ps1
# It is safe to run by hand too - a healthy server makes this a no-op.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FinderDir = Join-Path $Root '..\real-estate-finder'
$Python = Join-Path $FinderDir '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in real-estate-finder/README.md first."
}

function Test-Site {
    # check-api authenticates with FINDER_API_TOKEN and exits non-zero on any
    # failure - down server, bad token, or unreachable database. `-m
    # real_estate_finder` only resolves from inside real-estate-finder, so
    # this pushes location there rather than assuming the caller's cwd.
    Push-Location $FinderDir
    try {
        & $Python -m real_estate_finder check-api *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        Pop-Location
    }
}

if (Test-Site) {
    Write-Host "리포트 서버가 이미 실행 중입니다." -ForegroundColor Green
    exit 0
}

Write-Host "리포트 서버가 응답하지 않습니다. run-site.bat을 새로 띄웁니다..." -ForegroundColor Yellow
Start-Process -FilePath (Join-Path $Root 'run-site.bat') -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-Site) {
        Write-Host "리포트 서버가 떴습니다." -ForegroundColor Green
        exit 0
    }
}

Write-Host "60초 안에 리포트 서버가 뜨지 않았습니다." -ForegroundColor Red
exit 1
