@echo off
rem Entry point the scheduled task runs. See setup-task.ps1 for why this exists:
rem H-able only runs elevated, Windows UIPI drops input from a lower-integrity
rem process, and asking for UAC on every run would rule out unattended
rem collection. The task runs this with highest privileges and no prompt.
rem
rem A scheduled task cannot take arguments at trigger time, so the subcommand is
rem read from data\next-command.txt (run-stock.ps1 writes it). Defaults to
rem hable-import.
setlocal
set "HERE=%~dp0"
cd /d "%HERE%"

if not exist "%HERE%data" mkdir "%HERE%data"
set "COMMAND_FILE=%HERE%data\next-command.txt"
set "LOG=%HERE%data\last-run.log"

set "SUBCOMMAND=hable-import"
if exist "%COMMAND_FILE%" (
    for /f "usebackq delims=" %%L in ("%COMMAND_FILE%") do set "SUBCOMMAND=%%L"
)

echo [%date% %time%] %SUBCOMMAND%> "%LOG%"
"%HERE%..\real-estate-finder\.venv\Scripts\python.exe" -X utf8 -m stock_importer %SUBCOMMAND% >> "%LOG%" 2>&1
rem A space before >> matters: `%ERRORLEVEL%>>` would read as a stream redirect.
set "CODE=%ERRORLEVEL%"
echo EXIT=%CODE% >> "%LOG%"
exit /b %CODE%
