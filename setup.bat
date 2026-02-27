@echo off
echo ================================================
echo   GrokHive Autonomous - Setup
echo   https://github.com/HeavenFYouMissed/GrokHive-Autonomous
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Install Python 3.11+ from python.org
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
cd /d "%~dp0"
python -m venv venv
if errorlevel 1 (
    echo [ERROR] Failed to create venv. Check your Python installation.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

echo [2/3] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [WARNING] Some packages may have failed. The app might still work.
)

echo.
echo [3/3] Setup complete!
echo.
echo ================================================
echo   To run the app:
echo     Double-click run.bat
echo     (or: venv\Scripts\activate ^& python main.py)
echo.
echo   For a Desktop shortcut:
echo     Run create_shortcut.bat
echo.
echo   For OCR tool (optional):
echo     Install Tesseract from:
echo     https://github.com/tesseract-ocr/tesseract/releases
echo ================================================
echo.
pause
