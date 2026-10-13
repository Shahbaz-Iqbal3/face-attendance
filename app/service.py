"""Business logic: matching, attendance rules, reports."""
from __future__ import annotations
import io
import threading
import time
from datetime import datetime, timedelta

import cv2
import numpy as np

from . import db
from .engine import FaceEngine, Face

FMT = "%Y-%m-%d %H:%M:%S"


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


class Gallery:
    """All enrolled embeddings kept in memory as one matrix for fast matching."""

    def __init__(self):
        self.lock = threading.Lock()
        self.matrix = np.zeros((0, 512), np.float32)
        self.owner = np.zeros((0,), np.int64)
        self.people: dict[int, dict] = {}
        self.reload()

    def reload(self):
        c = db.conn()
        people = {r["id"]: dict(r) for r in c.execute(
            "SELECT id, emp_code, name, department, active FROM people")}
        rows = c.execute("SELECT person_id, vector FROM embeddings").fetchall()
        vecs, owners = [], []
        for r in rows:
            p = people.get(r["person_id"])
            if p and p["active"]:
                vecs.append(np.frombuffer(r["vector"], np.float32))
                owners.append(r["person_id"])
        with self.lock:
            self.people = people
            self.matrix = np.vstack(vecs) if vecs else np.zeros((0, 512), np.float32)
            self.owner = np.array(owners, np.int64)

    def best_match(self, emb: np.ndarray, exclude: int | None = None):
        """Return (person_id, similarity) of best person, or (None, best_sim)."""
        with self.lock:
            if self.matrix.shape[0] == 0:
                return None, 0.0
            sims = self.matrix @ emb
            if exclude is not None:
                sims = np.where(self.owner == exclude, -1.0, sims)
            # score per person = mean of top-2 samples (robust against one odd sample)
            best_pid, best = None, -1.0
            for pid in np.unique(self.owner):
                s = np.sort(sims[self.owner == pid])[::-1]
                score = float(s[:2].mean()) if s.size > 1 else float(s[0])
                if score > best:
                    best, best_pid = score, int(pid)
            if best_pid is None or best < -0.5:
                return None, 0.0
            return best_pid, best


class Recognizer:
    def __init__(self):
        self.engine = FaceEngine()
        self.gallery = Gallery()
        self._pending: dict[int, tuple[int, float]] = {}   # pid -> (hits, last_ts)
        self._last_event: dict[int, float] = {}            # pid -> monotonic time of last logged event
        self._last_unknown = 0.0

    # ---- kiosk ----
    def process_frame(self, bgr: np.ndarray) -> dict:
        s = db.get_settings()
        thr = float(s["threshold"])
        min_px = int(s["min_face_px"])
        confirm = max(1, int(s["confirm_frames"]))
        cooldown = int(s["cooldown_sec"])
        h, w = bgr.shape[:2]
        out = []
        faces = self.engine.detect(bgr)[:3]
        for f in faces:
            bw, bh = f.box[2] - f.box[0], f.box[3] - f.box[1]
            item = {"box": [f.box[0] / w, f.box[1] / h, f.box[2] / w, f.box[3] / h], "state": "scan"}
            if min(bw, bh) < min_px:
                item["state"] = "far"
                out.append(item)
                continue
            self.engine.embed(bgr, f)
            if not f.quality.get("ok") and f.quality.get("reason") in ("Too dark - add more light", "Image is blurry - hold still"):
                item["state"] = "poor"
                item["message"] = f.quality["reason"]
                out.append(item)
                continue
            pid, sim = self.gallery.best_match(f.embedding)
            if pid is not None and sim >= thr:
                person = self.gallery.people[pid]
                item.update(person_id=pid, name=person["name"], department=person["department"],
                            similarity=round(sim, 3))
                hits, last = self._pending.get(pid, (0, 0))
                hits = hits + 1 if time.monotonic() - last < 3 else 1
                self._pending[pid] = (hits, time.monotonic())
                if hits < confirm:
                    item["state"] = "confirming"
                else:
                    item.update(self._mark(pid, sim, cooldown))
            else:
                item["state"] = "unknown"
                if time.monotonic() - self._last_unknown > 10:
                    self._last_unknown = time.monotonic()
                    self._log("unknown", None, "Unknown person", "", sim)
            out.append(item)
        return {"faces": out, "ts": now().strftime(FMT)}

    def _mark(self, pid: int, sim: float, cooldown: int) -> dict:
        s = db.get_settings()
        person = self.gallery.people[pid]
        t = now()
        day = t.strftime("%Y-%m-%d")
        c = db.conn()
        row = c.execute("SELECT * FROM attendance WHERE person_id=? AND day=?", (pid, day)).fetchone()
        mono = time.monotonic()
        in_cooldown = mono - self._last_event.get(pid, -1e9) < cooldown

        if row is None or row["check_in"] is None:
            h, m = parse_hhmm(s["office_start"])
            start = t.replace(hour=h, minute=m, second=0)
            late_after = start + timedelta(minutes=int(s["late_after_min"]))
            status = "late" if t > late_after else "on_time"
            with db.tx() as cx:
                if row is None:
                    cx.execute("INSERT INTO attendance(person_id,day,check_in,status,source) VALUES(?,?,?,?, 'auto')",
                               (pid, day, t.strftime(FMT), status))
                else:  # existing manual 'absent' row gets overwritten by a real scan
                    cx.execute("UPDATE attendance SET check_in=?, status=?, source='auto' WHERE id=?",
                               (t.strftime(FMT), status, row["id"]))
            self._last_event[pid] = mono
            self._log("check_in", pid, person["name"], status, sim)
            return {"state": "marked", "action": "check_in", "status": status, "time": t.strftime("%H:%M")}

        ci = datetime.strptime(row["check_in"], FMT)
        gap = int(s["checkout_gap_min"])
        if t - ci >= timedelta(minutes=gap) and not in_cooldown:
            with db.tx() as cx:
                cx.execute("UPDATE attendance SET check_out=? WHERE id=?", (t.strftime(FMT), row["id"]))
            self._last_event[pid] = mono
            self._log("check_out", pid, person["name"], "", sim)
            return {"state": "marked", "action": "check_out", "status": row["status"], "time": t.strftime("%H:%M")}

        if not in_cooldown:
            self._last_event[pid] = mono
            self._log("repeat", pid, person["name"], "already marked", sim)
        return {"state": "already", "action": "already", "status": row["status"],
                "time": ci.strftime("%H:%M")}

    def _log(self, kind, pid, name, detail, sim):
        with db.tx() as c:
            c.execute("INSERT INTO events(ts,kind,person_id,name,detail,similarity) VALUES(?,?,?,?,?,?)",
                      (now().strftime(FMT), kind, pid, name, detail, float(sim) if sim is not None else None))


# ---------- reports ----------
def today_summary() -> dict:
    day = now().strftime("%Y-%m-%d")
    c = db.conn()
    total = c.execute("SELECT COUNT(*) FROM people WHERE active=1 AND EXISTS "
                      "(SELECT 1 FROM embeddings e WHERE e.person_id=people.id)").fetchone()[0]
    rows = c.execute("""SELECT p.id, p.emp_code, p.name, p.department, a.check_in, a.check_out, a.status, a.source
                        FROM people p LEFT JOIN attendance a ON a.person_id=p.id AND a.day=?
                        WHERE p.active=1 AND EXISTS (SELECT 1 FROM embeddings e WHERE e.person_id=p.id)
                        ORDER BY (a.check_in IS NULL), a.check_in""", (day,)).fetchall()
    items = [dict(r) for r in rows]
    present = sum(1 for r in items if r["check_in"])
    late = sum(1 for r in items if r["status"] == "late")
    return {"day": day, "enrolled": total, "present": present, "late": late,
            "on_time": present - late, "not_in": total - present, "rows": items}


def attendance_range(start: str, end: str, department: str = "", person_id: int | None = None,
                     status: str = "") -> list[dict]:
    q = """SELECT a.id, a.day, p.id AS person_id, p.emp_code, p.name, p.department,
                  a.check_in, a.check_out, a.status, a.source, a.note
           FROM attendance a JOIN people p ON p.id=a.person_id
           WHERE a.day BETWEEN ? AND ?"""
    args: list = [start, end]
    if department:
        q += " AND p.department=?"; args.append(department)
    if person_id:
        q += " AND p.id=?"; args.append(person_id)
    if status:
        q += " AND a.status=?"; args.append(status)
    q += " ORDER BY a.day DESC, a.check_in"
    return [dict(r) for r in db.conn().execute(q, args).fetchall()]


def hours(ci: str | None, co: str | None) -> str:
    if not ci or not co:
        return ""
    d = datetime.strptime(co, FMT) - datetime.strptime(ci, FMT)
    mins = int(d.total_seconds() // 60)
    return f"{mins // 60}:{mins % 60:02d}"


def to_csv(rows: list[dict]) -> bytes:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Employee ID", "Name", "Department", "Check in", "Check out", "Hours", "Status", "Source", "Note"])
    for r in rows:
        w.writerow([r["day"], r["emp_code"], r["name"], r["department"],
                    (r["check_in"] or "")[11:16], (r["check_out"] or "")[11:16],
                    hours(r["check_in"], r["check_out"]), r["status"], r["source"], r["note"]])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")   # BOM so Excel opens Urdu names correctly


def to_xlsx(rows: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    head = ["Date", "Employee ID", "Name", "Department", "Check in", "Check out", "Hours", "Status", "Source", "Note"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1B2A41")
    for r in rows:
        ws.append([r["day"], r["emp_code"], r["name"], r["department"],
                   (r["check_in"] or "")[11:16], (r["check_out"] or "")[11:16],
                   hours(r["check_in"], r["check_out"]), r["status"], r["source"], r["note"]])
    for col, w in zip("ABCDEFGHIJ", (12, 14, 24, 18, 10, 10, 8, 10, 10, 28)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
