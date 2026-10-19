@echo off
setlocal
cd /d "%~dp0"
set SHANSUAN_MOBILE_LAUNCH=1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; if (-not (Get-PSDrive -Name S -ErrorAction SilentlyContinue)) { New-PSDrive -Name S -PSProvider FileSystem -Root (Get-Location).Path | Out-Null }; Set-Location S:\; & S:\.venv\Scripts\python.exe S:\app\scripts\mobile.py %*"
if errorlevel 1 pause
