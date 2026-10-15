"""Downloads the optional high-accuracy ArcFace-R50 model (InsightFace). Needs internet once."""
import os
import tempfile
import urllib.request
import zipfile

from .paths import USER_MODELS_DIR

URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
WANTED = "w600k_r50.onnx"
EXPECTED_SIZE = 174383860


def download(say=print) -> bool:
    dst = USER_MODELS_DIR / WANTED
    if dst.exists() and dst.stat().st_size == EXPECTED_SIZE:
        say("The high-accuracy model is already installed.")
        return True
    say("Downloading the high-accuracy face model (about 290 MB). This needs internet, once.")
    say("Licence note: this model is free for testing and for use inside your own company.")
    say("Selling a product that contains it needs a licence from InsightFace (insightface.ai).\n")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        with urllib.request.urlopen(URL, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done, last = 0, -10
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                tmp.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    if pct >= last + 10:
                        last = pct
                        say(f"  {pct}%")
        tmp.close()
        say("Extracting...")
        with zipfile.ZipFile(tmp.name) as z:
            with z.open(WANTED) as src, open(dst, "wb") as out:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    out.write(b)
        say("Done. Restart Face Attendance, then enrol people again (the new model needs fresh face samples).")
        return True
    except Exception as ex:
        say(f"Download failed: {ex}")
        return False
    finally:
        try:
            tmp.close()
            os.unlink(tmp.name)
        except OSError:
            pass
