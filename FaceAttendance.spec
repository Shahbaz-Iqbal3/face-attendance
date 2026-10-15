# PyInstaller recipe (works on Windows, Linux, macOS)
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("models", "models"), ("app/static", "app/static")]
binaries, hidden = [], collect_submodules("app")
for pkg in ("cv2", "uvicorn", "cryptography"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
hidden += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
           "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "multipart"]

a = Analysis(["run.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "scipy", "pandas", "PIL"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FaceAttendance", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="FaceAttendance")
