# Stop whatever is listening on the report server's port and start a fresh one.
#
# Unlike ensure-site.ps1 (a no-op when the server is already healthy), this
# always kills the current process and starts run-site.ps1 again - the
# "코드를 바꿨으면 재시작" step AGENTS.md requires after a report-site (Django
# 뷰·템플릿 등, f/e·b/e 구분 없이 한 프로세스) code change. Wired up as a
# Dagster job (see dagster_project/definitions.py, restart_report_site_job)
# so that step does not need a person to find and kill the old process by
# hand. real-estate-finder needs no equivalent: its ops already run as a
# fresh subprocess per invocation, so it never holds old code in memory.
#
# Not on any schedule - trigger it manually from the Dagster UI (Launch Run
# on restart_report_site_job) right after a report-site code change.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FinderDir = Join-Path $Root '..\real-estate-finder'
$Python = Join-Path $FinderDir '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in real-estate-finder/README.md first."
}

function Test-Site {
    # Same check ensure-site.ps1 uses: authenticates with FINDER_API_TOKEN
    # and exits non-zero on any failure - down server, bad token, or
    # unreachable database.
    Push-Location $FinderDir
    try {
        & $Python -m real_estate_finder check-api *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        Pop-Location
    }
}

$listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
$processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $processIds) {
    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $proc) { continue }
    if ($proc.ProcessName -notmatch '^python') {
        Write-Host "8000번 포트를 쓰는 프로세스($($proc.ProcessName), PID $processId)가 python이 아니라 건너뜁니다. 직접 확인하세요." -ForegroundColor Yellow
        continue
    }
    Write-Host "기존 리포트 서버(PID $processId)를 종료합니다..." -ForegroundColor Yellow
    Stop-Process -Id $processId -Force
}

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
        break
    }
    Start-Sleep -Milliseconds 500
}

Write-Host "run-site.ps1을 새로 띄웁니다..." -ForegroundColor Cyan
# run-site.bat, not run-site.ps1, is what a person double-clicks, and .bat
# ends in `pause >nul` - started unattended that would leave a hidden
# process waiting forever for a keypress nobody will send. Launch
# run-site.ps1 directly, same as ensure-site.ps1 does.
$RunSitePs1 = Join-Path $Root 'run-site.ps1'
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$RunSitePs1`""
)

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-Site) {
        Write-Host "리포트 서버가 새 코드로 다시 떴습니다." -ForegroundColor Green
        exit 0
    }
}

Write-Host "60초 안에 리포트 서버가 다시 뜨지 않았습니다." -ForegroundColor Red
exit 1
