@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
where npm >nul 2>nul
if errorlevel 1 goto failed
if not exist "node_modules\@vue\cli-service\bin\vue-cli-service.js" (
  call npm ci
  if errorlevel 1 goto failed
)
echo 页面地址：http://localhost:8081
call npm run serve
if errorlevel 1 goto failed
exit /b 0
:failed
echo 前端启动失败，请确认已安装 Node.js，并查看上方错误信息。
pause
exit /b 1
