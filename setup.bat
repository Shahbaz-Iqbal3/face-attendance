@echo off
REM One-time setup (needs internet ONCE, to download Python packages). After this the app runs fully offline.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run setup.bat again.
  pause & exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if exist wheels (
  echo Installing from the local "wheels" folder - no internet needed.
  pip install --no-index --find-links wheels -r requirements.txt
) else (
  pip install -r requirements.txt
)
echo.
echo Setup finished. Double-click run.bat to start.
pause
