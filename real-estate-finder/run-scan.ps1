# Run one property scan.
#
# 1) Start Edge with a dedicated profile if the debugging port is unavailable.
# 2) Check the Naver login and wait for the user to sign in when necessary.
# 3) Scan listings and send the result to KakaoTalk.
#
# Double-click run-scan.bat to launch this script.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Port = 9222
$Endpoint = "http://127.0.0.1:$Port"
# Modern Edge ignores --remote-debugging-port for the default profile.
# Use a dedicated profile outside the repository.
$EdgeProfile = Join-Path $env:LOCALAPPDATA 'naver-land-edge'
$Python = Join-Path $Root '.venv\Scripts\python.exe'

function Find-Edge {
    # The (x86) variable needs braces: "$env:ProgramFiles(x86)" would expand the
    # bare ProgramFiles and append a literal "(x86)", losing the space.
    $candidates = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    $command = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Microsoft Edge was not found. Check the msedge.exe installation path."
}

function Test-DebugPort {
    try {
        Invoke-WebRequest "$Endpoint/json/version" -TimeoutSec 3 -UseBasicParsing | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in README.md first."
}

if (Test-DebugPort) {
    Write-Host "[1/3] Found Edge on the debugging endpoint ($Endpoint)." -ForegroundColor Green
} else {
    Write-Host "[1/3] Starting Edge with the dedicated profile..." -ForegroundColor Cyan
    Write-Host "      Profile: $EdgeProfile"
    $edgeExe = Find-Edge
    Start-Process $edgeExe -ArgumentList @(
        "--remote-debugging-port=$Port",
        "--user-data-dir=`"$EdgeProfile`""
    )

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        if (Test-DebugPort) { break }
    }
    if (-not (Test-DebugPort)) {
        throw @"
Edge started, but the debugging port did not open.
If Edge was already running, it may have opened only a new window without the port.
Close every Edge window and run this file again.
"@
    }
    Write-Host "      The debugging port is ready." -ForegroundColor Green
}

Write-Host "[2/3] Checking the Naver login..." -ForegroundColor Cyan
& $Python -m real_estate_finder browser-login
if ($LASTEXITCODE -ne 0) { throw "Naver login failed." }

Write-Host "[3/3] Scanning listings and sending the KakaoTalk message..." -ForegroundColor Cyan
& $Python -m real_estate_finder scan-once
if ($LASTEXITCODE -ne 0) { throw "The property scan failed." }

Write-Host "Completed." -ForegroundColor Green
