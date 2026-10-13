@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo  Please run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe run.py %*
set EC=%errorlevel%
echo.
echo  The app has stopped. Exit code: %EC%
if not "%EC%"=="0" (
  echo  It did not close normally. Please double-click diagnose.bat, then send these files to support:
  echo     logs\diagnose.txt   logs\app.log   logs\crash.log
)
pause
