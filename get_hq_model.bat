@echo off
REM Downloads the optional high-accuracy face model (needs internet once). Then restart the app and re-enrol people.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo  Please run setup.bat first. & pause & exit /b 1 )
.venv\Scripts\python.exe run.py --get-hq-model
