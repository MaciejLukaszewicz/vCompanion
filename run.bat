@echo off
:loop
echo Starting vCompanion...
call venv\Scripts\activate.bat
python main.py
if %errorlevel% == 123 (
    echo Restarting vCompanion...
    goto loop
)
pause
