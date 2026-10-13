"""SQLite layer. Everything lives in one local file: data/attendance.db"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager

from .paths import DATA_DIR

DB_PATH = DATA_DIR / "attendance.db"
_local = threading.local()

DEFAULT_SETTINGS = {
    "company_name": "My Company",
    "office_start": "09:00",
    "late_after_min": "15",
    "cooldown_sec": "60",
    "checkout_gap_min": "120",
    "threshold": "0.45",       # cosine similarity needed to accept a match (higher = stricter)
    "min_face_px": "90",       # ignore faces smaller than this on the kiosk (people walking past)
    "confirm_frames": "2",     # consecutive matches needed before marking
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    thumb BLOB,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    vector BLOB NOT NULL,
    label TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_emb_person ON embeddings(person_id);
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    check_in TEXT,
    check_out TEXT,
    status TEXT NOT NULL,            -- on_time | late | absent
    source TEXT NOT NULL DEFAULT 'auto',
    note TEXT NOT NULL DEFAULT '',
    UNIQUE(person_id, day)
);
CREATE INDEX IF NOT EXISTS idx_att_day ON attendance(day);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,              -- check_in | check_out | repeat | unknown | enroll | manual
    person_id INTEGER,
    name TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    similarity REAL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(id);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        _local.c = c
    return c


@contextmanager
def tx():
    c = conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def init():
    with tx() as c:
        c.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


def get_settings() -> dict:
    rows = conn().execute("SELECT key,value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_setting(key: str, value: str):
    with tx() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))


# ---- password ----
def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + dk.hex()


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def has_password() -> bool:
    return bool(get_settings().get("admin_hash"))
