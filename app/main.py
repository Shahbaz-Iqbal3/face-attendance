"""FastAPI app: kiosk + admin, fully local."""
from __future__ import annotations
import secrets
import socket
import sqlite3
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, service
from .engine import decode_image
from .paths import BACKUP_DIR, STATIC_DIR

db.init()
app = FastAPI(title="Face Attendance", docs_url=None, redoc_url=None, openapi_url=None)
rec = service.Recognizer()

SESSIONS: dict[str, float] = {}
SESSION_TTL = 12 * 3600
_login_fail: dict[str, tuple[int, float]] = {}
FRONT_POSE: dict[int, dict] = {}


# ---------------- auth ----------------
def require_admin(request: Request):
    tok = request.cookies.get("fa_session")
    exp = SESSIONS.get(tok or "")
    if not exp or exp < time.time():
        raise HTTPException(401, "Please sign in")
    return True


class PasswordIn(BaseModel):
    password: str


def _new_session(resp: Response):
    tok = secrets.token_urlsafe(32)
    SESSIONS[tok] = time.time() + SESSION_TTL
    resp.set_cookie("fa_session", tok, httponly=True, samesite="lax", max_age=SESSION_TTL)


@app.get("/api/status")
def status(request: Request):
    tok = request.cookies.get("fa_session")
    s = db.get_settings()
    return {"has_password": db.has_password(),
            "authed": bool(tok and SESSIONS.get(tok, 0) > time.time()),
            "company": s["company_name"]}


@app.post("/api/setup")
def setup(body: PasswordIn, response: Response):
    if db.has_password():
        raise HTTPException(400, "A password is already set")
    if len(body.password) < 6:
        raise HTTPException(400, "Use at least 6 characters")
    db.set_setting("admin_hash", db.hash_password(body.password))
    _new_session(response)
    return {"ok": True}


@app.post("/api/login")
def login(body: PasswordIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    fails, last = _login_fail.get(ip, (0, 0))
    if fails >= 5 and time.time() - last < 60:
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
    if not db.verify_password(body.password, db.get_settings().get("admin_hash", "")):
        _login_fail[ip] = (fails + 1, time.time())
        raise HTTPException(401, "Wrong password")
    _login_fail.pop(ip, None)
    _new_session(response)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    SESSIONS.pop(request.cookies.get("fa_session", ""), None)
    response.delete_cookie("fa_session")
    return {"ok": True}


@app.post("/api/admin/password", dependencies=[Depends(require_admin)])
def change_password(body: PasswordIn):
    if len(body.password) < 6:
        raise HTTPException(400, "Use at least 6 characters")
    db.set_setting("admin_hash", db.hash_password(body.password))
    return {"ok": True}


# ---------------- kiosk ----------------
@app.post("/api/kiosk/frame")
async def kiosk_frame(request: Request):
    data = await request.body()
    img = decode_image(data)
    if img is None:
        raise HTTPException(400, "Bad image")
    return await run_blocking(rec.process_frame, img)


async def run_blocking(fn, *a):
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(fn, *a)


@app.get("/api/kiosk/info")
def kiosk_info():
    s = db.get_settings()
    t = service.today_summary()
    ev = db.conn().execute(
        "SELECT ts, kind, name, detail FROM events WHERE kind IN ('check_in','check_out') "
        "ORDER BY id DESC LIMIT 8").fetchall()
    return {"company": s["company_name"], "present": t["present"], "late": t["late"],
            "enrolled": t["enrolled"], "recent": [dict(e) for e in ev]}


# ---------------- admin: dashboard ----------------
@app.get("/api/admin/summary", dependencies=[Depends(require_admin)])
def summary():
    return service.today_summary()


@app.get("/api/admin/events", dependencies=[Depends(require_admin)])
def events(after: int = 0, limit: int = 40):
    c = db.conn()
    if after:
        rows = c.execute("SELECT * FROM events WHERE id>? ORDER BY id DESC LIMIT ?", (after, limit)).fetchall()
    else:
        rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------------- admin: settings ----------------
class SettingsIn(BaseModel):
    company_name: str | None = None
    office_start: str | None = None
    late_after_min: int | None = None
    cooldown_sec: int | None = None
    checkout_gap_min: int | None = None
    threshold: float | None = None
    min_face_px: int | None = None
    confirm_frames: int | None = None


@app.get("/api/admin/settings", dependencies=[Depends(require_admin)])
def get_settings():
    s = db.get_settings()
    s.pop("admin_hash", None)
    s["threshold"] = str(service.threshold(rec.engine))
    s["threshold_default"] = str(rec.engine.default_threshold)
    s["model"] = rec.engine.label
    return s


@app.put("/api/admin/settings", dependencies=[Depends(require_admin)])
def put_settings(body: SettingsIn):
    data = body.model_dump(exclude_none=True)
    if "office_start" in data:
        try:
            datetime.strptime(data["office_start"], "%H:%M")
        except ValueError:
            raise HTTPException(400, "Office start must look like 09:00")
    if "threshold" in data and not (0.2 <= data["threshold"] <= 0.9):
        raise HTTPException(400, "Matching strictness must be between 0.20 and 0.90")
    for k, v in data.items():
        db.set_setting(f"threshold_{rec.engine.model_id}" if k == "threshold" else k, str(v))
    return get_settings()


# ---------------- admin: people ----------------
class PersonIn(BaseModel):
    emp_code: str
    name: str
    department: str = ""
    active: bool = True


@app.get("/api/admin/people", dependencies=[Depends(require_admin)])
def people():
    rows = db.conn().execute("""SELECT p.id, p.emp_code, p.name, p.department, p.active, p.created_at,
        (SELECT COUNT(*) FROM embeddings e WHERE e.person_id=p.id AND e.model=?) AS samples,
        (SELECT COUNT(*) FROM embeddings e WHERE e.person_id=p.id AND e.model<>?) AS old_samples,
        (p.thumb IS NOT NULL) AS has_thumb FROM people p ORDER BY p.name""",
        (rec.engine.model_id, rec.engine.model_id)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/people", dependencies=[Depends(require_admin)])
def add_person(body: PersonIn):
    code, name = body.emp_code.strip(), body.name.strip()
    if not code or not name:
        raise HTTPException(400, "Employee ID and name are required")
    try:
        with db.tx() as c:
            cur = c.execute("INSERT INTO people(emp_code,name,department) VALUES(?,?,?)",
                            (code, name, body.department.strip()))
            pid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Employee ID {code} is already used")
    return {"id": pid}


@app.put("/api/admin/people/{pid}", dependencies=[Depends(require_admin)])
def edit_person(pid: int, body: PersonIn):
    try:
        with db.tx() as c:
            c.execute("UPDATE people SET emp_code=?, name=?, department=?, active=? WHERE id=?",
                      (body.emp_code.strip(), body.name.strip(), body.department.strip(), int(body.active), pid))
    except sqlite3.IntegrityError:
        raise HTTPException(400, "That Employee ID is already used")
    rec.gallery.reload()
    return {"ok": True}


@app.delete("/api/admin/people/{pid}", dependencies=[Depends(require_admin)])
def delete_person(pid: int):
    with db.tx() as c:
        c.execute("DELETE FROM people WHERE id=?", (pid,))
    rec.gallery.reload()
    return {"ok": True}


@app.post("/api/admin/people/{pid}/clear-faces", dependencies=[Depends(require_admin)])
def clear_faces(pid: int):
    with db.tx() as c:
        c.execute("DELETE FROM embeddings WHERE person_id=?", (pid,))
        c.execute("UPDATE people SET thumb=NULL WHERE id=?", (pid,))
    FRONT_POSE.pop(pid, None)
    rec.gallery.reload()
    return {"ok": True}


@app.get("/api/admin/people/{pid}/thumb", dependencies=[Depends(require_admin)])
def thumb(pid: int):
    r = db.conn().execute("SELECT thumb FROM people WHERE id=?", (pid,)).fetchone()
    if not r or not r["thumb"]:
        raise HTTPException(404)
    return Response(r["thumb"], media_type="image/jpeg", headers={"Cache-Control": "max-age=60"})


STEPS = {"front", "left", "right", "up", "down", "upload"}
STEP_HINT = {"left": "Turn your head slightly to your left", "right": "Turn your head slightly to your right",
             "up": "Lift your chin slightly", "down": "Lower your chin slightly"}


@app.post("/api/admin/people/{pid}/enroll", dependencies=[Depends(require_admin)])
async def enroll(pid: int, request: Request, step: str = "front", force: int = 0):
    if step not in STEPS:
        raise HTTPException(400, "Unknown step")
    data = await request.body()
    return await run_blocking(_enroll, pid, data, step, bool(force))


def _enroll(pid: int, data: bytes, step: str, force: bool):
    c = db.conn()
    person = c.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()
    if not person:
        raise HTTPException(404, "Person not found")
    img = decode_image(data)
    if img is None:
        return {"ok": False, "reason": "Could not read that image"}
    faces = rec.engine.detect(img, min_score=0.6)
    if not faces:
        return {"ok": False, "reason": "No face found - look at the camera"}
    if len(faces) > 1 and (faces[1].box[2] - faces[1].box[0]) > 0.6 * (faces[0].box[2] - faces[0].box[0]):
        return {"ok": False, "reason": "More than one face in the picture"}
    f = faces[0]
    rec.engine.embed(img, f)
    q = f.quality
    if not q["ok"]:
        return {"ok": False, "reason": q["reason"], "quality": q}
    pose = rec.engine.pose(f)
    if step != "upload":
        if step == "front":
            if abs(pose["yaw"]) > 0.18:
                return {"ok": False, "reason": "Look straight at the camera", "pose": pose}
        else:
            ref = FRONT_POSE.get(pid)
            if ref:
                dy, dp = pose["yaw"] - ref["yaw"], pose["pitch"] - ref["pitch"]
                ok = {"left": dy > 0.10, "right": dy < -0.10, "up": dp < -0.06, "down": dp > 0.06}[step]
                if not ok:
                    return {"ok": False, "reason": STEP_HINT[step], "pose": pose}
    # does this face already belong to someone else?
    other, sim = rec.gallery.best_match(f.embedding, exclude=pid)
    thr = service.threshold(rec.engine)
    if other is not None and sim >= thr and not force:
        nm = rec.gallery.people[other]["name"]
        return {"ok": False, "duplicate": True, "reason": f"This face looks like {nm} (already enrolled)",
                "similarity": round(sim, 2)}
    with db.tx() as cx:
        cx.execute("INSERT INTO embeddings(person_id, vector, label, model) VALUES(?,?,?,?)",
                   (pid, f.embedding.astype(np.float32).tobytes(), step, rec.engine.model_id))
        if person["thumb"] is None:
            x1, y1, x2, y2 = f.box
            pad = int(0.25 * (x2 - x1))
            h, w = img.shape[:2]
            crop = img[max(0, y1 - pad):min(h, y2 + pad), max(0, x1 - pad):min(w, x2 + pad)]
            crop = cv2.resize(crop, (160, 160))
            cx.execute("UPDATE people SET thumb=? WHERE id=?", (cv2.imencode(".jpg", crop)[1].tobytes(), pid))
    if step == "front":
        FRONT_POSE[pid] = pose
    n = c.execute("SELECT COUNT(*) FROM embeddings WHERE person_id=? AND model=?", (pid, rec.engine.model_id)).fetchone()[0]
    rec.gallery.reload()
    rec._log("enroll", pid, person["name"], f"sample {n} ({step})", None)
    return {"ok": True, "samples": n, "box": list(f.box), "quality": q}


@app.post("/api/admin/test-frame", dependencies=[Depends(require_admin)])
async def test_frame(request: Request):
    img = decode_image(await request.body())
    if img is None:
        raise HTTPException(400, "Bad image")
    return await run_blocking(rec.analyze, img)


# ---------------- admin: attendance ----------------
@app.get("/api/admin/departments", dependencies=[Depends(require_admin)])
def departments():
    rows = db.conn().execute("SELECT DISTINCT department FROM people WHERE department<>'' ORDER BY 1").fetchall()
    return [r[0] for r in rows]


def _range(start: str, end: str):
    today = datetime.now().date()
    start = start or today.strftime("%Y-%m-%d")
    end = end or start
    return start, end


@app.get("/api/admin/attendance", dependencies=[Depends(require_admin)])
def attendance(start: str = "", end: str = "", department: str = "", person_id: int = 0, status: str = ""):
    start, end = _range(start, end)
    rows = service.attendance_range(start, end, department, person_id or None, status)
    for r in rows:
        r["hours"] = service.hours(r["check_in"], r["check_out"])
    return rows


class ManualIn(BaseModel):
    person_id: int
    day: str
    status: str                 # on_time | late | absent
    check_in: str | None = None  # HH:MM
    check_out: str | None = None
    note: str = ""


@app.put("/api/admin/attendance", dependencies=[Depends(require_admin)])
def manual(body: ManualIn):
    if body.status not in ("on_time", "late", "absent"):
        raise HTTPException(400, "Status must be on_time, late or absent")

    def full(t):
        return f"{body.day} {t}:00" if t else None
    ci, co = (None, None) if body.status == "absent" else (full(body.check_in), full(body.check_out))
    with db.tx() as c:
        c.execute("""INSERT INTO attendance(person_id,day,check_in,check_out,status,source,note)
                     VALUES(?,?,?,?,?,'manual',?)
                     ON CONFLICT(person_id,day) DO UPDATE SET check_in=excluded.check_in,
                       check_out=excluded.check_out, status=excluded.status, source='manual', note=excluded.note""",
                  (body.person_id, body.day, ci, co, body.status, body.note))
    p = db.conn().execute("SELECT name FROM people WHERE id=?", (body.person_id,)).fetchone()
    rec._log("manual", body.person_id, p["name"] if p else "", f"{body.day}: {body.status}", None)
    return {"ok": True}


@app.delete("/api/admin/attendance/{aid}", dependencies=[Depends(require_admin)])
def del_attendance(aid: int):
    with db.tx() as c:
        c.execute("DELETE FROM attendance WHERE id=?", (aid,))
    return {"ok": True}


@app.get("/api/admin/export", dependencies=[Depends(require_admin)])
def export(format: str = "csv", start: str = "", end: str = "", department: str = "",
           person_id: int = 0, status: str = ""):
    start, end = _range(start, end)
    rows = service.attendance_range(start, end, department, person_id or None, status)
    name = f"attendance_{start}_to_{end}"
    if format == "xlsx":
        return Response(service.to_xlsx(rows), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(service.to_csv(rows), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ---------------- admin: backup ----------------
@app.post("/api/admin/backup", dependencies=[Depends(require_admin)])
def backup():
    name = f"attendance_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    dst = sqlite3.connect(BACKUP_DIR / name)
    db.conn().backup(dst)
    dst.close()
    return {"name": name}


@app.get("/api/admin/backups", dependencies=[Depends(require_admin)])
def backups():
    files = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
    return [{"name": f.name, "size": f.stat().st_size} for f in files[:30]]


@app.get("/api/admin/backups/{name}", dependencies=[Depends(require_admin)])
def get_backup(name: str):
    f = (BACKUP_DIR / name).resolve()
    if f.parent != BACKUP_DIR.resolve() or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, filename=f.name)


# ---------------- pages ----------------
@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/kiosk")
def kiosk_page():
    return FileResponse(STATIC_DIR / "kiosk.html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/api/lan")
def lan(request: Request):
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # no packet is sent; just picks the LAN interface
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    scheme = request.url.scheme
    port = request.url.port or (443 if scheme == "https" else 80)
    return {"ip": ip, "port": port, "scheme": scheme}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
