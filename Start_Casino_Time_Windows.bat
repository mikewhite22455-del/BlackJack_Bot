@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Install Python 3.10 or newer from python.org, then try again.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Review the error above.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" casinotime_app.py
if errorlevel 1 pause
