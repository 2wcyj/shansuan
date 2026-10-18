@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" app\scripts\test_all.py
if errorlevel 1 (
 echo Tests failed. Read .test-output and fix before continuing.
 pause
 exit /b 1
)
echo All test stages passed.
pause
