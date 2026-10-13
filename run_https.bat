@echo off
REM Same as run.bat but over HTTPS, so other PCs on the Wi-Fi can use the camera.
REM Their browser shows a one-time "not secure" warning (self-signed certificate): Advanced > Continue.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo  Please run setup.bat first. & pause & exit /b 1 )
.venv\Scripts\python.exe run.py --https %*
pause
