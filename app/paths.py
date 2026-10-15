"""Resolves folders: from source, portable exe, or installed (data kept in ProgramData)."""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    APP_DIR = Path(sys.executable).parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    APP_DIR = BUNDLE_DIR

if os.environ.get("FA_DATA_DIR"):
    DATA_ROOT = Path(os.environ["FA_DATA_DIR"])
elif FROZEN and (APP_DIR / "installed.flag").exists():
    # Installed in Program Files (read-only for normal users): keep all data in a shared writable folder
    base = os.environ.get("PROGRAMDATA") or str(Path.home())
    DATA_ROOT = Path(base) / "FaceAttendance"
else:
    DATA_ROOT = APP_DIR                       # portable / source: data lives next to the program
DATA_ROOT.mkdir(parents=True, exist_ok=True)

STATIC_DIR = BUNDLE_DIR / "app" / "static"
DATA_DIR = DATA_ROOT / "data"
BACKUP_DIR = DATA_ROOT / "backups"
LOG_DIR = DATA_ROOT / "logs"
USER_MODELS_DIR = DATA_ROOT / "models"        # extra models you download (e.g. the high-accuracy one)
for _d in (DATA_DIR, BACKUP_DIR, LOG_DIR, USER_MODELS_DIR):
    _d.mkdir(exist_ok=True)

MODELS_DIR = BUNDLE_DIR / "models"


def model_path(name: str) -> Path:
    """A model file: your downloaded copy wins over the one bundled with the app."""
    p = USER_MODELS_DIR / name
    return p if p.exists() else MODELS_DIR / name


def applog(msg: str):
    """Append a timestamped line to logs/app.log (never raises)."""
    try:
        import time
        with open(LOG_DIR / "app.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass
