@echo off
chcp 65001 >nul
cd /d "%~dp0"
set NODE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe
if not exist "%NODE%" (
  echo 未找到 Node 运行时，路径：
  echo %NODE%
  echo 请参考 docs\installation.md 准备前端构建与浏览器测试环境。
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo 缺少本地 Python 运行环境，请先按 README 安装依赖。
  pause
  exit /b 1
)
"%NODE%" app\scripts\capture-demo.cjs
if errorlevel 1 (
  echo.
  echo 截图失败，请查看上方错误信息。
  pause
  exit /b 1
)
echo.
echo 完成。截图位于 docs\screenshots\
pause