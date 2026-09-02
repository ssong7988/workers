# 매물 조회 한 번에 실행하기.
#
# 1) 디버깅 포트로 열린 Edge가 없으면 전용 프로필로 띄운다
# 2) 네이버 로그인을 확인한다 (안 돼 있으면 로그인 화면을 열고 기다린다)
# 3) 매물을 조회하고 결과를 카카오톡으로 보낸다
#
# run-scan.bat을 더블클릭하면 이 스크립트가 실행된다.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Port = 9222
$Endpoint = "http://127.0.0.1:$Port"
# Chrome 136(Edge 동일)부터 기본 프로필에서는 --remote-debugging-port가 무시된다.
# 반드시 별도 프로필이어야 하며, 저장소 밖에 둔다.
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
    throw "Edge를 찾지 못했습니다. msedge.exe 경로를 확인하세요."
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
    throw "가상환경이 없습니다: $Python`n먼저 README의 설치 절차를 실행하세요."
}

if (Test-DebugPort) {
    Write-Host "[1/3] 디버깅 포트로 열린 Edge를 찾았습니다 ($Endpoint)." -ForegroundColor Green
} else {
    Write-Host "[1/3] Edge를 전용 프로필로 실행합니다..." -ForegroundColor Cyan
    Write-Host "      프로필: $EdgeProfile"
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
Edge를 띄웠지만 디버깅 포트가 열리지 않았습니다.
이미 실행 중인 Edge가 있으면 새 창만 열리고 포트는 열리지 않습니다.
Edge 창을 모두 닫고 이 파일을 다시 실행하세요.
"@
    }
    Write-Host "      포트가 열렸습니다." -ForegroundColor Green
}

Write-Host "[2/3] 네이버 로그인 확인..." -ForegroundColor Cyan
& $Python -m real_estate_finder browser-login
if ($LASTEXITCODE -ne 0) { throw "네이버 로그인에 실패했습니다." }

Write-Host "[3/3] 매물 조회 및 카카오톡 전송..." -ForegroundColor Cyan
& $Python -m real_estate_finder scan-once
if ($LASTEXITCODE -ne 0) { throw "매물 조회에 실패했습니다." }

Write-Host "완료했습니다." -ForegroundColor Green
