@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 goto failed
rem 首次启动会自动建好空库；已有数据库结构不一致时会停止，不会清空或改表。
echo 后端接口文档：http://localhost:8010/docs
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
if errorlevel 1 goto failed
exit /b 0
:failed
echo 后端启动失败，请查看上方错误信息。不要关闭窗口后反复重试。
pause
exit /b 1
