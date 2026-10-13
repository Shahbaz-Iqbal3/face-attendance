"""Resolves folders both when run from source and when frozen with PyInstaller."""
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    DATA_ROOT = Path(sys.executable).parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    DATA_ROOT = BUNDLE_DIR

MODELS_DIR = BUNDLE_DIR / "models"
STATIC_DIR = BUNDLE_DIR / "app" / "static"
DATA_DIR = DATA_ROOT / "data"
BACKUP_DIR = DATA_ROOT / "backups"
DATA_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)


LOG_DIR = DATA_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def applog(msg: str):
    """Append a timestamped line to logs/app.log (never raises)."""
    try:
        import time
        with open(LOG_DIR / "app.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass
