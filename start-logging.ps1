# Shared per-app dated console logging, dot-sourced the same way load-env.ps1
# is - one line per caller, defines Start-AppLog, does nothing until called.
#
# Captures the *entire* console (Write-Host lines and native subprocess
# stdout/stderr) into .logs/<App>/<yyyy-MM-dd>.log, so a run started hidden
# or detached (see report-site/ensure-site.ps1) still leaves a readable
# record of why it failed.
#
# Start-Transcript, not `& $exe 2>&1 | Tee-Object`: every run-*.ps1 sets
# $ErrorActionPreference = 'Stop', and in Windows PowerShell 5.1 piping a
# native exe's stderr through `2>&1` wraps each line in a NativeCommandError
# record - combined with 'Stop' that kills the script on the first stderr
# line any tool prints. Transcript needs no pipe and avoids this entirely.
# Verified empirically: Start-Transcript does capture native stdout/stderr
# when the process owns a real console (a double-clicked .bat, or the hidden
# console Start-Process creates) - not when a parent tool has redirected the
# console's own streams.
#
# Deliberately NOT used by ensure-site.ps1: that script polls the server it
# just started via Start-Process, so it would try to open the same day's
# report-site log a second time while run-site.ps1 already holds it open -
# the second Start-Transcript would just fail to acquire the file (handled
# below, but pointless). ensure-site's own output already reaches its
# caller's console (Dagster); the server failure reason it is polling for
# lands in run-site.ps1's own log instead.

$LogsRoot = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '.logs'
$LogRetentionDays = 30

function Start-AppLog {
    param(
        [Parameter(Mandatory)]
        [string]$App
    )

    try {
        $appDir = Join-Path $LogsRoot $App
        if (-not (Test-Path $appDir)) {
            New-Item -ItemType Directory -Path $appDir -Force | Out-Null
        }

        # Prune old logs first so a large backlog never delays this run's
        # own log from starting.
        $cutoff = (Get-Date).AddDays(-$LogRetentionDays)
        Get-ChildItem -Path $appDir -Filter '*.log' -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $cutoff } |
            Remove-Item -Force -ErrorAction SilentlyContinue

        $logFile = Join-Path $appDir "$(Get-Date -Format 'yyyy-MM-dd').log"
        Start-Transcript -Path $logFile -Append -ErrorAction Stop | Out-Null
        Write-Host "Logging to: $logFile" -ForegroundColor DarkGray
    } catch {
        # Logging must never be the reason an app fails to start - e.g. a
        # transcript is already open in this process, or another process
        # (run-scan.ps1 and send-report.ps1 share one log per day) is
        # holding today's file at this exact moment.
        Write-Host "파일 로깅을 시작하지 못했습니다 ($_). 로깅 없이 계속합니다." -ForegroundColor Yellow
    }
}
