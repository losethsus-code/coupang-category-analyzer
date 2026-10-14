@echo off
setlocal
cd /d "%~dp0"
echo Updating Coupang Sourcing Explorer from GitHub...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
if errorlevel 1 (
 echo.
 echo [ERROR] GitHub update failed. Please check logs\github_update.log.
 pause
 exit /b 1
)
echo.
echo Update done. Starting dashboard...
call "%~dp0START.bat"
endlocal
