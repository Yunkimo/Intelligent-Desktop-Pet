@echo off
rem 切到 UTF-8 代码页，以便中文提示正常显示
chcp 65001 >nul
rem 启动桌宠：缺少虚拟环境时先执行 setup.bat 初始化，再运行桌宠。
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo 未找到虚拟环境，先执行 setup.bat 初始化...
    call setup.bat
    if errorlevel 1 exit /b 1
)

.venv\Scripts\python.exe main.py
if errorlevel 1 (
    echo.
    echo 桌宠启动失败，请查看上方错误信息。
    pause
)
