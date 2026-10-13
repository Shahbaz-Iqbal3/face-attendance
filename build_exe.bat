@echo off
REM Builds a Windows folder you can hand to a customer: no Python, no setup, no internet.
REM Run setup.bat first, then this. Result: dist\FaceAttendance\FaceAttendance.exe
cd /d "%~dp0"
call .venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller --noconfirm --clean --name FaceAttendance ^
  --add-data "models;models" --add-data "app\static;app\static" ^
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on --collect-submodules app --collect-all onnxruntime ^
  run.py
echo.
echo Done. Copy the dist\FaceAttendance folder to the customer PC and double-click FaceAttendance.exe
pause
