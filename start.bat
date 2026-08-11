@echo off
REM Double-click this file to run the PFAS Reporting tool.
REM Leave the window open while you use the app; close it or press Ctrl+C to stop.

cd /d "%~dp0"

echo ============================================
echo   PFAS Reporting Automation
echo   Opening http://127.0.0.1:5000
echo   Keep this window OPEN while using the app.
echo ============================================
echo.

REM Give the server a moment to bind the port, then open the browser.
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"

python main.py

echo.
echo Server stopped.
pause
