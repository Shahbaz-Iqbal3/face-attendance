@echo off
REM Builds the customer version: dist\FaceAttendance\FaceAttendance.exe (no Python, no setup, no internet).
REM Run setup.bat first, then this.
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo  Run setup.bat first. & pause & exit /b 1 )
.venv\Scripts\python.exe -m pip install pyinstaller
if errorlevel 1 ( echo  Could not install PyInstaller. & pause & exit /b 1 )
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean FaceAttendance.spec
if errorlevel 1 ( echo  Build FAILED. & pause & exit /b 1 )
echo.
echo  Done. Give the customer the whole folder:  dist\FaceAttendance
echo  They only double-click FaceAttendance.exe
pause
