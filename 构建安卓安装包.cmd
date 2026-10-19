@echo off
setlocal
cd /d "%~dp0"
rem Use an ASCII PowerShell drive alias because some bundled Android tools
rem cannot read Chinese workspace paths.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; if (-not (Get-PSDrive -Name S -ErrorAction SilentlyContinue)) { New-PSDrive -Name S -PSProvider FileSystem -Root (Get-Location).Path | Out-Null }; Set-Location S:\; & S:\.venv\Scripts\python.exe S:\app\scripts\build_android.py"
if errorlevel 1 pause
