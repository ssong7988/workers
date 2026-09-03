# Run one property scan.
#
# 1) Check the report server, which owns the database. A scan has nowhere to
#    go without it, so this runs before the browser is touched.
# 2) Start Edge with a dedicated profile if the debugging port is unavailable.
# 3) Check the Naver login and wait for the user to sign in when necessary.
# 4) Collect the listings and hand them to the report server, which decides
#    what matches, what is urgent, and whether KakaoTalk goes out. The reason
#    is printed either way.
#    Use send-report.bat to send the full result on demand.
#
# Double-click run-scan.bat to launch this script.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Share the repo-root .env (KAKAO_REPORT_URL, and FINDER_API_BASE if set).
. (Join-Path $Root '..\load-env.ps1')

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

Write-Host "[1/4] Checking the report server..." -ForegroundColor Cyan
& $Python -m real_estate_finder check-api
if ($LASTEXITCODE -ne 0) {
    throw @"
The report server is not answering.
It owns the database, so a scan cannot be stored without it.
Start report-site\run-site.bat, then run this file again.
"@
}

if (Test-DebugPort) {
    Write-Host "[2/4] Found Edge on the debugging endpoint ($Endpoint)." -ForegroundColor Green
} else {
    Write-Host "[2/4] Starting Edge with the dedicated profile..." -ForegroundColor Cyan
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

Write-Host "[3/4] Checking the Naver login..." -ForegroundColor Cyan
& $Python -m real_estate_finder browser-login
if ($LASTEXITCODE -ne 0) { throw "Naver login failed." }

Write-Host "[4/4] Collecting listings (KakaoTalk goes out only when there is something to report)..." -ForegroundColor Cyan
& $Python -m real_estate_finder scan-once
if ($LASTEXITCODE -ne 0) { throw "The property scan failed." }

Write-Host "Completed." -ForegroundColor Green
