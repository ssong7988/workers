@echo off
rem Entry point the scheduled task runs. See setup-task.ps1 for why this exists:
rem H-able only runs elevated, Windows UIPI drops input from a lower-integrity
rem process, and asking for UAC on every run would rule out unattended
rem collection. The task runs this with highest privileges and no prompt.
rem
rem A scheduled task cannot take arguments at trigger time, so the subcommand is
rem read from data\next-command.txt (run-stock.ps1 writes it). Defaults to
rem hable-import.
rem
rem A line starting with "script:" runs that Python file instead. It is an
rem escape hatch for one-off diagnostics that need the same elevation - the
rem screen has to be poked to find out what a button does.
setlocal
set "HERE=%~dp0"
cd /d "%HERE%"

if not exist "%HERE%data" mkdir "%HERE%data"
set "COMMAND_FILE=%HERE%data\next-command.txt"
set "LOG=%HERE%data\last-run.log"
set "PYTHON=%HERE%..\real-estate-finder\.venv\Scripts\python.exe"

set "SUBCOMMAND=hable-import"
if exist "%COMMAND_FILE%" (
    for /f "usebackq delims=" %%L in ("%COMMAND_FILE%") do set "SUBCOMMAND=%%L"
)

echo [%date% %time%] %SUBCOMMAND%> "%LOG%"
set "SCRIPT="
for /f "tokens=1,* delims=:" %%A in ("%SUBCOMMAND%") do (
    if /i "%%A"=="script" set "SCRIPT=%%B"
)

if defined SCRIPT (
    "%PYTHON%" -X utf8 -c "import ctypes,runpy,sys; w=ctypes.windll.kernel32.GetConsoleWindow(); ctypes.windll.user32.ShowWindow(w,0) if w else None; sys.argv=[r'%SCRIPT%']; runpy.run_path(r'%SCRIPT%', run_name='__main__')" >> "%LOG%" 2>&1
) else (
    "%PYTHON%" -X utf8 -m stock_importer --hide-console %SUBCOMMAND% >> "%LOG%" 2>&1
)
rem A space before >> matters: `%ERRORLEVEL%>>` would read as a stream redirect.
set "CODE=%ERRORLEVEL%"
echo EXIT=%CODE% >> "%LOG%"
exit /b %CODE%
