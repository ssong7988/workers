# Manual compatibility wrapper. The actual four-step workflow is the Python
# `real_estate_finder.cli.run_scan_workflow` function, which Dagster invokes
# directly. This file only keeps double-click/PowerShell operation convenient.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

. (Join-Path $Root '..\start-logging.ps1')
Start-AppLog -App 'real-estate-finder'

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in README.md first."
}

& $Python -u -m real_estate_finder run-scan
if ($LASTEXITCODE -ne 0) { throw "The property scan failed." }

Write-Host "Completed." -ForegroundColor Green
