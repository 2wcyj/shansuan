@echo off
setlocal
cd /d "%~dp0"
set SHANSUAN_MOBILE_LAUNCH=1
set PYTHONPATH=%~dp0
"%~dp0.venv\Scripts\python.exe" "%~dp0app\scripts\mobile.py" %*
if errorlevel 1 pause
