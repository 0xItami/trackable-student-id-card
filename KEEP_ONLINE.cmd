@echo off
cd /d "%~dp0"
start "SIID-01 online" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0KEEP_ONLINE.ps1"
echo SIID-01 is going online at http://frill-relay-nacho.ngrok-free.dev
echo Status log: tmp\keep-online.log   Stop it with STOP_ONLINE.cmd
timeout /t 5 >nul
