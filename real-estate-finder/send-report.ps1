# Send the current property report to KakaoTalk.
#
# Sends every currently active listing as one KakaoTalk card, whether or not it
# is an urgent deal. The listings, the card and the delivery all belong to
# report-site now, so this only calls its management command: no browser, no
# Naver login, and no web server needed - just the database.
#
# Double-click send-report.bat to launch this script.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Share KAKAO_REPORT_URL (the report-site's public URL) with the digest.
. (Join-Path $Root '..\load-env.ps1')

$Python = Join-Path $Root '.venv\Scripts\python.exe'
$SiteDir = Join-Path $Root '..\report-site'

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python`nComplete the installation steps in README.md first."
}
if (-not (Test-Path (Join-Path $SiteDir 'manage.py'))) {
    throw "report-site\manage.py not found next to this project."
}

Write-Host "Sending the current listings to KakaoTalk..." -ForegroundColor Cyan
Push-Location $SiteDir
try {
    & $Python manage.py send_digest
    if ($LASTEXITCODE -ne 0) { throw "Sending the report failed." }
} finally {
    Pop-Location
}

Write-Host "Completed." -ForegroundColor Green
