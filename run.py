"""Face Attendance launcher.

  run.py                       start the server (opens the browser)
  run.py --background          start hidden, no browser (used for start-with-Windows)
  run.py --open admin|kiosk    make sure the server runs, then open that page   [--fullscreen for the kiosk]
  run.py --stop                stop a running server
  run.py --get-hq-model        download the optional high-accuracy face model
  run.py --https               serve over HTTPS (other PCs can then use the camera)
"""
import argparse
import faulthandler
import os
import socket
import sys
import subprocess
import time
import traceback

import uvicorn

from app.paths import DATA_DIR, LOG_DIR, applog

# If Python itself crashes (native crash in a DLL), record where into logs/crash.log
_crash_file = open(LOG_DIR / "crash.log", "w")
faulthandler.enable(file=_crash_file, all_threads=True)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_cert():
    """Self-signed certificate so other PCs on the LAN can use the camera (browsers need HTTPS)."""
    cert, key = DATA_DIR / "cert.pem", DATA_DIR / "key.pem"
    if cert.exists() and key.exists():
        return str(cert), str(key)
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Face Attendance")])
    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    try:
        san.append(x509.IPAddress(ipaddress.ip_address(lan_ip())))
    except ValueError:
        pass
    now = datetime.datetime.utcnow()
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=3650))
         .add_extension(x509.SubjectAlternativeName(san), critical=False).sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return str(cert), str(key)


def hide_console():
    if os.name == "nt":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def self_cmd(*args):
    """Command line that starts this same program again (works for source and for the frozen exe)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, os.path.abspath(__file__), *args]


def server_up(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


def wait_ready(port, seconds=180):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if server_up(port):
            return True
        time.sleep(0.5)
    return False


def start_background(port, https=False):
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200 | 0x08000000     # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    cmd = self_cmd("--background", "--port", str(port)) + (["--https"] if https else [])
    subprocess.Popen(cmd, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def find_kiosk_browser():
    if os.name != "nt":
        return None
    pf = [os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")]
    for root in pf:
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = os.path.join(root, rel)
            if root and os.path.exists(p):
                return p
    return None


def open_ui(kind, port, scheme, fullscreen):
    url = f"{scheme}://127.0.0.1:{port}/{'' if kind == 'home' else kind}"
    exe = find_kiosk_browser() if (fullscreen and kind == "kiosk") else None
    if exe:
        from app.paths import DATA_ROOT
        profile = str(DATA_ROOT / "kiosk-browser")           # separate profile so fullscreen always applies
        args = [exe, "--kiosk", url, "--no-first-run", "--use-fake-ui-for-media-stream",
                f"--user-data-dir={profile}", "--disable-session-crashed-bubble"]
        if "msedge" in exe.lower():
            args.append("--edge-kiosk-type=fullscreen")
        subprocess.Popen(args)
    else:
        import webbrowser
        webbrowser.open(url)


def stop_server():
    if os.name == "nt" and getattr(sys, "frozen", False):
        name = os.path.basename(sys.executable)
        subprocess.run(["taskkill", "/F", "/IM", name, "/FI", f"PID ne {os.getpid()}"],
                       capture_output=True, creationflags=0x08000000)
        print("  Face Attendance was stopped.")
    else:
        print("  Close the Face Attendance window (or press Ctrl+C in it) to stop.")


def main():
    if sys.stdout is None:                      # windowed exe: no console attached
        sys.stdout = sys.stderr = open(os.devnull, "w")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    ap.add_argument("--https", action="store_true", help="serve over HTTPS (lets other PCs use the camera)")
    ap.add_argument("--background", action="store_true", help="run hidden, without a browser or prompts")
    ap.add_argument("--open", choices=["admin", "kiosk", "home"], help="open that page (starting the server if needed)")
    ap.add_argument("--fullscreen", action="store_true", help="with --open kiosk: fullscreen browser window")
    ap.add_argument("--stop", action="store_true", help="stop a running server")
    ap.add_argument("--get-hq-model", action="store_true", help="download the optional high-accuracy model")
    a = ap.parse_args()
    scheme = "https" if a.https else "http"

    if a.stop:
        return stop_server()
    if a.get_hq_model:
        from app.hqmodel import download
        ok = download()
        input("\n  Press Enter to close...")
        return sys.exit(0 if ok else 1)
    if a.open:
        if not server_up(a.port):
            log(f"--open {a.open}: server not running, starting it")
            start_background(a.port, a.https)
            if not wait_ready(a.port):
                log("--open: server did not start in time")
                return
        return open_ui(a.open, a.port, scheme, a.fullscreen)

    if a.background:
        hide_console()
    if not port_free(a.port):
        if a.background:
            log("background start skipped: already running")
            return
        if server_up(a.port):
            print("\n  Face Attendance is already running. Opening it in your browser...\n")
            if not a.no_browser:
                open_ui("home", a.port, scheme, False)
            time.sleep(2)
            return
        print(f"\n  Port {a.port} is used by another program. Start with: --port 8001\n")
        input("  Press Enter to close...")
        sys.exit(1)
    ssl = {}
    if a.https:
        ssl["ssl_certfile"], ssl["ssl_keyfile"] = make_cert()
    ip = lan_ip()
    print("\n  Face Attendance is starting (100% offline)")
    print("  Keep this window open while the system is in use. Close it to stop.\n")
    print(f"  This computer : {scheme}://127.0.0.1:{a.port}")
    print(f"  Kiosk screen  : {scheme}://127.0.0.1:{a.port}/kiosk")
    print(f"  Admin (LAN)   : {scheme}://{ip}:{a.port}/admin\n")
    log(f"starting (python {sys.version.split()[0]}, frozen={getattr(sys, 'frozen', False)}, background={a.background}); loading app...")
    from app.main import app
    log("app loaded; starting web server...")
    import threading
    threading.Thread(target=_announce_ready, args=(a.port, scheme, not (a.no_browser or a.background)), daemon=True).start()
    config = uvicorn.Config(app, host="0.0.0.0", port=a.port, log_level="warning", **ssl)
    uvicorn.Server(config).run(sockets=make_sockets(a.port))


def make_sockets(port):
    """Listen on IPv4 AND IPv6, so http://localhost:PORT works even when Windows resolves localhost to ::1."""
    socks = []
    s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":
        s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s4.bind(("0.0.0.0", port))
    socks.append(s4)
    if socket.has_ipv6:
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            if os.name != "nt":
                s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.bind(("::", port))
            socks.append(s6)
        except OSError:
            pass          # machine without IPv6: IPv4 alone is fine
    return socks


def log(msg):
    applog(msg)


def _announce_ready(port, scheme, open_browser):
    """Wait until the server really answers, then tell the user and open the browser."""
    import time
    t0 = time.time()
    while time.time() - t0 < 180:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.5)
    else:
        print("  The server did not start within 3 minutes.")
        log("server did not become ready")
        return
    url = f"{scheme}://127.0.0.1:{port}/"
    print(f"  READY - open {url}\n")
    log(f"ready on {url} after {time.time() - t0:.1f}s")
    if open_browser:
        import webbrowser
        webbrowser.open(url)


def port_free(port):
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except BaseException:
        logd = LOG_DIR
        (logd / "error.log").write_text(
            f"Python {sys.version}\n\n" + traceback.format_exc(), encoding="utf-8")
        print("\n  The app could not start.\n")
        print(traceback.format_exc())
        print(f"  This was saved to: {logd / 'error.log'}")
        print("  Please send that file (or a photo of this window) to your support person.\n")
        if "--background" not in sys.argv:
            input("  Press Enter to close...")
        sys.exit(1)
