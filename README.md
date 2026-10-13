# Face Attendance (offline)

Face-recognition attendance for small offices. One computer runs the server and the kiosk camera;
the owner or HR opens the admin panel from any PC on the same Wi-Fi. **No internet, no cloud.**

## Start (Windows)
1. Install Python 3.10+ (tick "Add to PATH").
2. Double-click `setup.bat` (internet needed once, for Python packages).
3. Double-click `run.bat`. The browser opens. Choose **Admin** and set a password on first start.
4. Add people, enrol their faces (5 angles), then open **/kiosk** on the screen with the camera.

Linux / macOS / Raspberry Pi: `./setup.sh` then `./run.sh`.

## Pages
- `http://localhost:8000/kiosk` - entrance screen (camera, live result, beep)
- `http://<server-ip>:8000/admin` - dashboard, attendance, people, settings, export, backup

## Camera on other computers
Browsers only allow the camera on `localhost` or HTTPS. Use the kiosk on the server PC itself.
To use a camera (kiosk or enrolment) from another PC, start with `run_https.bat` (or `python run.py --https`).
The browser shows a one-time warning for the self-signed certificate. Enrolment also accepts uploaded photos.

## Fully offline install / selling it
- Models are included in `models/` (nothing downloads at run time).
- No internet on the target PC? On a connected PC run `pip download -r requirements.txt -d wheels`,
  copy the `wheels` folder next to `setup.bat`; setup will use it.
- No Python on the target PC? Run `build_exe.bat` once and ship `dist\FaceAttendance\`.

## How attendance works
- First recognised scan of the day = check-in. After the **office start time + grace minutes** it is marked *Late*.
- Repeat scans inside the **cooldown** are ignored. A scan after the **check-out gap** (default 120 min) sets check-out;
  later scans update it, so the last scan of the day is the check-out.
- Admin can add, correct, or delete any record by hand (including marking someone absent).
- A person must be recognised on 2 consecutive frames before being marked (reduces false matches).

## Data & privacy
Everything is in `data/attendance.db` (SQLite). Only face *embeddings* (512 numbers per sample) and one small
thumbnail per person are stored, not video. Use Settings > Backup, then copy the file to a USB drive.
Tell staff the system stores biometric data and get their consent.

## Known limits (v1)
- No liveness check: a high-quality photo or phone screen of a person can fool it. Do not use it for access control.
- Dates use the server PC's clock and time zone; keep it correct.
- Overnight shifts (check-in before midnight, out after) are not handled.
- Backup restore is manual: stop the app and replace `data/attendance.db` with a backup file.

## Tech
Python, FastAPI, SQLite, onnxruntime. SCRFD (det_500m) for detection and MobileFaceNet/ArcFace (w600k_mbf) for
512-d embeddings, from the InsightFace "buffalo_sc" pack. **Licence warning:** InsightFace's pretrained models are
for non-commercial research use. Before selling this product, swap in commercially licensed models (for example
OpenCV Zoo YuNet + SFace, which are MIT/Apache-2.0) or get a licence from InsightFace.
