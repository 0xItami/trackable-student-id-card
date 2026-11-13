@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_DEMO.ps1"
if errorlevel 1 (
  echo.
  echo The demo could not start. Read the error above.
)
pause
