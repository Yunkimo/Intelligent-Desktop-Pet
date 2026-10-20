@echo off
rem 切到 UTF-8 代码页，以便中文提示正常显示
chcp 65001 >nul
rem 启动桌宠：缺少虚拟环境时先执行 setup.bat 初始化，再用 pythonw 无控制台运行。
rem 启动异常写入 data\pet-error.log；需要看实时输出时改用 .venv\Scripts\python.exe main.py。
cd /d "%~dp0"

if not exist .venv\Scripts\pythonw.exe (
    echo 未找到虚拟环境，先执行 setup.bat 初始化...
    call setup.bat
    if errorlevel 1 exit /b 1
)

start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
if errorlevel 1 (
    echo.
    echo 桌宠启动失败，请检查 data\pet-error.log。
    pause
)
exit /b 0
