@echo off
rem 切到 UTF-8 代码页，以便中文提示正常显示
chcp 65001 >nul
rem One-time environment setup: create venv and install dependencies.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing dependencies...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

echo.
echo Done. Next steps:
echo   1. copy .env.example .env  and fill in LLM_API_KEY
echo   2. Run  启动桌宠.bat
