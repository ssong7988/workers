# Load the repo-root .env into the current process's environment.
#
# Dot-sourced by run-scan.ps1, send-report.ps1, and report-site/run-site.ps1
# so all three share one KAKAO_REPORT_URL without duplicating it per script.
# Real secrets (kakao-notifier/.env, report-site/.env) stay in their own
# directories; this file only carries the shared, non-secret report URL.

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $RepoRoot '.env'

if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) {
            continue
        }
        $key, $value = $trimmed.Split('=', 2)
        $key = $key.Trim()
        if (-not (Test-Path "env:$key")) {
            Set-Item -Path "env:$key" -Value $value.Trim()
        }
    }
}
