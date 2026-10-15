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


ENGINE_TEST = ("import cv2; from app.engine import FaceEngine; e=FaceEngine(); img=cv2.imread('tools/sample_face.jpg'); "
               "fs=e.detect(img); f=fs[0]; e.embed(img,f); print(e.label, '| faces', len(fs), '| box', f.box, '| embedding', f.embedding.shape)")

STAGES = [
    ("import numpy", "import numpy; print(numpy.__version__)"),
    ("import cv2 (OpenCV)", "import cv2; print(cv2.__version__)"),
    ("OpenCV has the face detector", "import cv2; cv2.FaceDetectorYN; cv2.FaceRecognizerSF; print('ok')"),
    ("face detection + recognition on a sample face", ENGINE_TEST),
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
status = {}
for stage in STAGES:
    name, code = stage[0], stage[1]
    extra = stage[2] if len(stage) > 2 else {}
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code], capture_output=True, text=True,
                       env={**os.environ, **extra})
    status[name] = r.returncode == 0
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
out("RESULT: " + ("everything works on this computer" if not bad else f"PROBLEM - first failure: {bad}"))
os.makedirs("logs", exist_ok=True)
with open(os.path.join("logs", "diagnose.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\nSaved to logs\\diagnose.txt - send that file to support.")
