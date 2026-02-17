@echo off
setlocal

:: Launch browser script in background. It will wait for the server to be ready.
call venv\Scripts\activate.bat
start /b python launch_browser.py

:loop
echo Starting vCompanion...
python main.py
if %errorlevel% == 123 (
    echo Restarting vCompanion...
    goto loop
)
pause
