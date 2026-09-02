@echo off
setlocal
title Real Estate Scan
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-scan.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
    echo [FAILED] Review the messages above.
)
echo Press any key to close this window.
pause >nul
exit /b %EXITCODE%
