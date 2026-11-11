@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 blackjack_lab.py %*
) else (
    python blackjack_lab.py %*
)
if errorlevel 1 (
    echo The learning run did not finish. Review the error above.
    pause
    exit /b 1
)
echo Open report.html inside your chosen output folder to inspect the results.
pause
