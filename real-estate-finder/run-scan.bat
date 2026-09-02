@echo off
chcp 65001 >nul
title 과천 관심 매물 조회
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-scan.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
    echo [실패] 위 메시지를 확인하세요.
)
echo 창을 닫으려면 아무 키나 누르세요.
pause >nul
exit /b %EXITCODE%
