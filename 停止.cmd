@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 缺少本地运行环境，请查看 docs\installation.md。
  pause
  exit /b 1
)
set PYTHONUTF8=1
".venv\Scripts\python.exe" app\scripts\stop.py
pause
