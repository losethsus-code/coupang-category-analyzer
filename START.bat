@echo off
setlocal
cd /d "%~dp0"
echo [Coupang Sourcing Explorer v0.6] Starting dashboard...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] Dashboard did not start. Check logs in this folder.
  echo If needed, run DIAGNOSE.bat and send logs/launcher.log to ChatGPT.
  pause
)
endlocal
