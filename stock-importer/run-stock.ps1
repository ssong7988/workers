# Run the collector elevated. No UAC prompt appears.
#
# It triggers the "run with highest privileges" scheduled task registered once
# by setup-task.ps1. A scheduled task takes no arguments at trigger time, so the
# subcommand is written to data\next-command.txt and run-stock.cmd reads it.
#
#   .\run-stock.ps1 -Command hable-import    collect and hand to report-site
#   .\run-stock.ps1 -Command hable-collect   collect to JSON only
#   .\run-stock.ps1 -Command hable-probe     diagnose the screen
#
# Console messages are English on purpose - see setup-task.ps1.

param(
    [string]$Command = 'hable-import',
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'

$TaskName = 'KB-StockImporter'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $Root 'data'
$CommandFile = Join-Path $DataDir 'next-command.txt'
$LogFile = Join-Path $DataDir 'last-run.log'
$STILL_RUNNING = 267009

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    throw "Scheduled task '$TaskName' is not registered. Run setup-task.ps1 as administrator once."
}

if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory $DataDir | Out-Null }
Set-Content -Path $CommandFile -Value $Command -Encoding ascii
if (Test-Path $LogFile) { Remove-Item $LogFile -Force }

Start-ScheduledTask -TaskName $TaskName

# The task runs asynchronously. Wait for it, then show the log it wrote.
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$result = $STILL_RUNNING
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $result = (Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo).LastTaskResult
    if ($result -ne $STILL_RUNNING) { break }
}

if ($result -eq $STILL_RUNNING) {
    Write-Host "Still running after $TimeoutSeconds seconds." -ForegroundColor Yellow
}
if (Test-Path $LogFile) {
    Get-Content $LogFile -Encoding UTF8
} else {
    Write-Host "No log was written." -ForegroundColor Yellow
}
