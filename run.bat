@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo  Please run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe run.py %*
echo.
echo  The app has stopped. If there is an error above, see logs\error.log
pause
