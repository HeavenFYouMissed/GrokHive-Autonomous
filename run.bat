@echo off
:: ================================================
::   GrokHive Autonomous - Quick Launcher
::   Double-click this to run the app.
::   Auto-pulls latest changes from GitHub first.
:: ================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo         Run setup.bat first to create it.
    pause
    exit /b 1
)

:: Auto-update from GitHub (silent, non-blocking)
git pull --ff-only >nul 2>&1

:: Re-install deps in case requirements changed
venv\Scripts\pip.exe install -q -r requirements.txt >nul 2>&1

start "" /B "venv\Scripts\pythonw.exe" main.py
