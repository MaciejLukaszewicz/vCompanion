@echo off
cd /d "%~dp0"
echo ==========================================
echo    vCompanion Update for Windows
echo ==========================================

:: Check for Git
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed or not in PATH.
    pause
    exit /b 1
)

echo [INFO] Checking for updates...
cd ..
if not exist ".git" (
    echo [INFO] Project was downloaded as a ZIP file. Skipping git pull.
    echo [INFO] To update, download the latest release and overwrite your files (excluding config/).
) else (
    echo [INFO] Pulling latest changes from GitHub...
    git pull
    if %errorlevel% neq 0 (
        echo [WARNING] git pull failed. Check your internet connection or local changes.
    )
)

echo [INFO] Updating dependencies...
if exist "venv" (
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    echo [WARNING] venv not found. Run setup.bat first.
)
cd setup

echo [SUCCESS] Update process finished.
pause
