@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Install Python 3.10 or newer from python.org, then run this file again.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependencies could not be installed. Check the message above.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" blackjack_bot.py
if errorlevel 1 pause
