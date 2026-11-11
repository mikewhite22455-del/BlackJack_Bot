@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 casinotime_lab.py %*
) else (
    python casinotime_lab.py %*
)
if errorlevel 1 (
    echo Experiment failed. Review the error above.
    pause
    exit /b 1
)
echo Results saved. Default report: casinotime-results\report.html
pause
