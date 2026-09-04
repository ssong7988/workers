# Stop the running Dagster process and start a fresh one.
#
# Same shape as report-site/restart-site.ps1, and needed for the same
# reason: `dagster dev -f definitions.py` reads definitions.py once at
# startup and keeps it in memory (see run-dagster.ps1) - editing a job,
# schedule, or op does not take effect until the process restarts, and
# run-dagster.bat itself does not kill an already-running instance (it just
# fails to bind port 3000).
#
# Deliberately a standalone script, not a Dagster job like
# restart_report_site_job: a job that kills the very process running it
# would abort its own run before the replacement finished starting. Run
# this by hand (or from Task Scheduler) after changing
# dagster_project/definitions.py.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# Same path-prefix computation as run-dagster.ps1, needed to poll the right
# GraphQL URL below (report_site/settings.py: DAGSTER_GRAPHQL_URL =
# http://127.0.0.1:3000<prefix>/graphql).
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
$DagsterPathPrefix = if ([string]::IsNullOrWhiteSpace($ReportPathToken)) {
    '/common/dagster/console'
} else {
    "/$ReportPathToken/common/dagster/console"
}
$GraphqlUrl = "http://127.0.0.1:3000$DagsterPathPrefix/graphql"

function Test-Dagster {
    # No auth on Dagster's own GraphQL endpoint (see report/dagster_client.py) -
    # a minimal query is enough to prove the webserver is up and serving.
    try {
        $response = Invoke-WebRequest -Uri $GraphqlUrl -Method Post `
            -ContentType 'application/json' -Body '{"query":"{__typename}"}' `
            -TimeoutSec 5 -UseBasicParsing
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$listeners = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
$processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $processIds) {
    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $proc) { continue }
    if ($proc.ProcessName -notmatch '^python') {
        Write-Host "Process on port 3000 ($($proc.ProcessName), PID $processId) is not python - skipping. Check it manually." -ForegroundColor Yellow
        continue
    }
    Write-Host "Stopping existing Dagster (PID $processId)..." -ForegroundColor Yellow
    Stop-Process -Id $processId -Force
}

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
        break
    }
    Start-Sleep -Milliseconds 500
}

Write-Host "Starting run-dagster.ps1..." -ForegroundColor Cyan
# run-dagster.bat, not run-dagster.ps1, is what a person double-clicks, and
# .bat ends in `pause >nul` - started unattended that would leave a hidden
# process waiting forever for a keypress nobody will send. Launch
# run-dagster.ps1 directly, same as restart-site.ps1 does for run-site.ps1.
$RunDagsterPs1 = Join-Path $Root 'run-dagster.ps1'
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$RunDagsterPs1`""
)

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-Dagster) {
        Write-Host "Dagster is back up with the new code." -ForegroundColor Green
        exit 0
    }
}

Write-Host "Dagster did not come back within 60 seconds." -ForegroundColor Red
exit 1
