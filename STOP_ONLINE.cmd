@echo off
cd /d "%~dp0"
if not exist tmp mkdir tmp
type nul > tmp\stop-online.flag
echo Stopping SIID-01 (backend and ngrok will shut down within 15 seconds)...
timeout /t 5 >nul
