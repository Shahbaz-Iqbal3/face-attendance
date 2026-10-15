@echo off
setlocal
cd /d "%~dp0"
echo.
echo  Face Attendance - one-time setup (needs internet once)
echo.

set "PY="
for %%V in (3.12 3.11 3.10 3.13) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo  No supported Python found. This app needs Python 3.10, 3.11, 3.12 or 3.13.
  echo  Newer versions ^(3.14+^) may not have all packages yet.
  echo  Install Python 3.12 from https://www.python.org/downloads/release/python-3120/
  echo  and tick "Add python.exe to PATH", then run setup.bat again.
  echo.
  pause
  exit /b 1
)
echo  Using: %PY%
%PY% --version

if exist .venv rmdir /s /q .venv
%PY% -m venv .venv
if errorlevel 1 ( echo  Could not create the virtual environment. & pause & exit /b 1 )

.venv\Scripts\python.exe -m pip install --upgrade pip
if exist wheels (
  echo  Installing from the local "wheels" folder - no internet needed.
  .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements.txt
) else (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if errorlevel 1 (
  echo.
  echo  Installing the packages FAILED. Check your internet connection and try again.
  echo  If it fails again, take a photo of this window and send it to support.
  pause
  exit /b 1
)

echo  Checking the install...
.venv\Scripts\python.exe -c "import numpy, cv2, fastapi, uvicorn, openpyxl; cv2.FaceDetectorYN; cv2.FaceRecognizerSF; print('  All packages load correctly.')"
if errorlevel 1 (
  echo  A package was installed but cannot load. Send a photo of this window to support.
  pause
  exit /b 1
)
echo.
echo  Setup finished. Double-click run.bat to start.
pause
