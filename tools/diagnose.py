"""Finds which part of the app crashes on this computer. Run via diagnose.bat"""
import os, platform, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
lines = []


def out(s=""):
    print(s)
    lines.append(s)


def cpu_name():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"],
                           capture_output=True, text=True, timeout=20)
        if r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


STAGES = [
    ("import numpy", "import numpy; print(numpy.__version__)"),
    ("import cv2 (OpenCV)", "import cv2; print(cv2.__version__)"),
    ("import onnxruntime", "import onnxruntime as o; print(o.__version__, o.get_available_providers())"),
    ("load detector model", "import onnxruntime as o; s=o.InferenceSession('models/det_500m.onnx',providers=['CPUExecutionProvider']); print('ok')"),
    ("load recognizer model", "import onnxruntime as o; s=o.InferenceSession('models/w600k_mbf.onnx',providers=['CPUExecutionProvider']); print('ok')"),
    ("run face engine on a blank image", "import numpy as np; from app.engine import FaceEngine; e=FaceEngine(); print('faces:', len(e.detect(np.full((480,640,3),120,np.uint8))))"),
    ("import web server", "import fastapi, uvicorn, openpyxl; print('ok')"),
    ("import whole app", "import app.main; print('ok')"),
]

out("Face Attendance - diagnostics")
out(f"Time    : {time.strftime('%Y-%m-%d %H:%M:%S')}")
out(f"Windows : {platform.platform()}")
out(f"Python  : {sys.version}")
out(f"Bits    : {platform.architecture()[0]}")
out(f"CPU     : {cpu_name()}")
out(f"RAM/folder: {ROOT}")
out()
bad = None
for name, code in STAGES:
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code], capture_output=True, text=True)
    rc = r.returncode
    hexrc = f"0x{rc & 0xFFFFFFFF:08X}"
    if rc == 0:
        out(f"[ OK ]  {name}: {r.stdout.strip()}")
    else:
        out(f"[FAIL]  {name}  (exit code {rc} = {hexrc})")
        tail = (r.stderr or r.stdout).strip().splitlines()[-12:]
        for t in tail:
            out("        " + t)
        bad = bad or name
out()
out("RESULT: " + ("everything works on this computer" if not bad else f"first failure -> {bad}"))
os.makedirs("logs", exist_ok=True)
with open(os.path.join("logs", "diagnose.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\nSaved to logs\\diagnose.txt - send that file to support.")
