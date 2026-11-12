@echo off
rem Installs (or repairs) and starts OmniKeep by running scripts\install.ps1, the one
rem installer the README describes. It can be run again: finished steps are skipped and
rem an existing .env or database is never overwritten. Arguments are passed through,
rem for example:  run.bat -DryRun
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
if errorlevel 1 (
    echo.
    echo Setup did not finish. See the messages above, or follow the install steps in README.md.
    pause
)
