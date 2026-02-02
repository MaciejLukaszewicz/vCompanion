@echo off
SETLOCAL EnableDelayedExpansion

echo ==========================================
echo    vCompanion Setup for Windows
echo ==========================================

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.12 or later.
    pause
    exit /b 1
)

:: Create Virtual Environment
if not exist "..\venv" (
    echo [INFO] Creating Virtual Environment...
    python -m venv ..\venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
) else (
    echo [INFO] venv already exists.
)

:: Install Requirements
echo [INFO] Installing/Updating dependencies...
call ..\venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r ..\requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

echo [SUCCESS] Setup completed successfully.
echo You can now run the application using run.bat from the root directory.
pause
