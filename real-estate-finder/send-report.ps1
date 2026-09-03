# Send the saved property report to KakaoTalk.
#
# Sends every currently active listing as one KakaoTalk card, whether or not it
# is an urgent deal. It reuses the result stored by the last scan, so no browser
# and no Naver login are needed.
#
# Double-click send-report.bat to launch this script.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Share KAKAO_REPORT_URL (the report-site's public URL) with the digest.
. (Join-Path $Root '..\load-env.ps1')

$Python = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in README.md first."
}

Write-Host "Sending the saved listings to KakaoTalk..." -ForegroundColor Cyan
& $Python -m real_estate_finder send-digest
if ($LASTEXITCODE -ne 0) { throw "Sending the report failed." }

Write-Host "Completed." -ForegroundColor Green
