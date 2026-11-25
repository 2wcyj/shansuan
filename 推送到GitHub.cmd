@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 即将推送到：https://github.com/2wcyj/shansuan.git
echo.
echo 如果提示登录：
echo   用户名填 2wcyj
echo   密码栏粘贴 Personal Access Token（不要输入账号密码）
echo.
echo 如果你刚换过 GitHub 账号，请先打开「凭据管理器 - Windows 凭据」，
echo 删除 github.com 相关条目，避免继续使用旧账号的缓存凭据。
echo.
pause
git push -u origin main
if errorlevel 1 (
  echo.
  echo 推送失败。常见原因：
  echo   1. 账号被暂停（403 Your account is suspended）
  echo   2. 仍在使用旧账号的缓存凭据
  echo   3. 使用了账号密码而不是 PAT
  echo.
  pause
  exit /b 1
)
echo.
git status -sb
echo.
echo 推送完成。
pause