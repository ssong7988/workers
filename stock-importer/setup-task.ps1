# Register the collector as a scheduled task so it can run elevated without a
# UAC prompt. Run this once, as administrator.
#
# Why it is needed: H-able only ever runs elevated - hable.exe's manifest says
# requestedExecutionLevel="requireAdministrator". Windows UIPI silently drops
# input sent from a lower-integrity process to a higher-integrity window, so the
# collector must match that level or its clicks never arrive. Raising it with
# `Start-Process -Verb RunAs` works but asks a person to approve UAC on every
# run, which rules out the unattended weekday 18:30 collection.
#
# A "run with highest privileges" task needs administrator rights once, at
# registration. After that `schtasks /run` (or Start-ScheduledTask) launches it
# elevated with no prompt. Dagster can call the same task.
#
# Console messages are English on purpose: Windows PowerShell 5.1 reads .ps1 as
# ANSI, so non-ASCII text here would be mangled - the same reason the other
# scripts in this repo are English.

$ErrorActionPreference = 'Stop'

$TaskName = 'KB-StockImporter'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $Root 'run-stock.cmd'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This script must run as administrator."
}
if (-not (Test-Path $Runner)) {
    throw "Runner not found: $Runner"
}

# The task must run in the interactive logon session. H-able is a GUI program,
# so a session-0 service account could neither see nor touch its windows.
$action = New-ScheduledTaskAction -Execute $Runner
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal `
    -Settings $settings -Description 'KB stock importer, elevated without a UAC prompt' -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "Run it with: powershell -File `"$Root\run-stock.ps1`" -Command hable-import" -ForegroundColor Cyan
Write-Host "Those runs show no UAC prompt." -ForegroundColor Cyan
