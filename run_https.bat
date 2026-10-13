@echo off
REM Same as run.bat but over HTTPS, so other PCs on the Wi-Fi can use the camera.
REM Their browser will show a one-time "not secure" warning (self-signed certificate): choose Advanced > Continue.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run.py --https %*
pause
