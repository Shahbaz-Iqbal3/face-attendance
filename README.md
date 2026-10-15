# Face Attendance (offline)

Face-recognition attendance for small offices. One computer runs the server and the kiosk camera;
the owner or HR opens the admin panel from any PC on the same Wi-Fi. **No internet, no cloud.**

## Installing for a customer (recommended)
Download **FaceAttendance-Setup.exe** (GitHub > Actions > newest *Build Windows app* run > Artifacts) and run it.
It installs the app, adds Start Menu shortcuts (Admin panel, Kiosk screen full-screen, Stop, Data folder), optionally starts
the server hidden whenever Windows starts, and opens the firewall for the office network. All data (database, backups, logs)
is kept in `C:\ProgramData\FaceAttendance` and is **kept when the app is uninstalled**.
On the camera PC tick *Also open the kiosk screen full-screen at login*; on the owner's PC use the Admin shortcut.
No black window is shown. To stop the server use Start Menu > Face Attendance > Stop Face Attendance.

## Better accuracy (optional, non-commercial)
Start Menu > Face Attendance > *Get high-accuracy face model* (or `get_hq_model.bat`), restart, then enrol people again.
This uses InsightFace ArcFace-R50, which is free for testing and in-house use only; selling a product that includes it
needs a licence from InsightFace. The model is downloaded by the customer and is never part of the installer or repo.
Delete `models\w600k_r50.onnx` (in the data folder) to go back to the standard model.

## Portable version (no installer)
Give them the `FaceAttendance` folder (built by `build_exe.bat`, or downloaded from GitHub Actions, see below).
They double-click **FaceAttendance.exe**: no Python, no setup, no internet. Keep the black window open while in use.
Data is saved in the `data` folder next to the exe. If Windows Firewall asks, click **Allow** (needed for other PCs to open the admin panel).

**Build the exe without a Windows dev setup:** push this folder to a GitHub repository, open the **Actions** tab,
run **Build Windows app**, and download `FaceAttendance-windows.zip` from the finished run.

## If it does not start
The black window shows the error and it is saved in `logs\error.log`. Most common causes: Python 3.14 (use 3.12),
setup.bat not finished successfully, or port 8000 already in use (start with `run.bat --port 8001`).

## Start (Windows, developer mode)
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

## Tech and licences
Python, FastAPI, SQLite, OpenCV. Face detection: **YuNet** (MIT licence). Face recognition: **SFace** (Apache-2.0).
Both come from the OpenCV Zoo and are included in `models/` together with their licence texts, so the app can be
sold commercially. No `onnxruntime` or other native AI runtime is needed.
The code can also use InsightFace models (non-commercial research licence) if you place `w600k_mbf.onnx` and
`det_500m.onnx` in `models/` and start with `FA_MODEL=arcface`. They are not shipped and must not be used in a product you sell.

## Tuning with real people
Admin > **Live test** shows, live, how the system scores each face against enrolled people and where the accept line is.
Enrol 3 to 5 staff, test in the real office light, and move the strictness slider until staff score above the line and
strangers well below it. Face data is per model: after upgrading from an older version, people show **Re-enrol needed**.
