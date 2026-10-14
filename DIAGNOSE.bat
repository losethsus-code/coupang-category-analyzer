@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
 ".venv\Scripts\python.exe" diagnose.py
) else (
 where py >nul 2>nul
 if not errorlevel 1 (
   py -3 diagnose.py
 ) else (
   python diagnose.py
 )
)
if exist logs (explorer.exe "%~dp0logs")
pause
endlocal
