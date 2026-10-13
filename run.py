"""Start the server.  python run.py [--port 8000] [--https]"""
import argparse
import os
import socket
import sys
import traceback

import uvicorn

from app.paths import DATA_DIR


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


def main():
    if sys.stdout is None:                      # windowed exe: no console attached
        sys.stdout = sys.stderr = open(os.devnull, "w")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    ap.add_argument("--https", action="store_true", help="serve over HTTPS (lets other PCs use the camera)")
    a = ap.parse_args()
    if not port_free(a.port):
        print(f"\n  Port {a.port} is already in use. Face Attendance may already be running")
        print(f"  (look for another black window), or another program uses that port.")
        print(f"  Open http://localhost:{a.port} in your browser, or start with: --port 8001\n")
        input("  Press Enter to close...")
        sys.exit(1)
    scheme = "https" if a.https else "http"
    ssl = {}
    if a.https:
        ssl["ssl_certfile"], ssl["ssl_keyfile"] = make_cert()
    ip = lan_ip()
    print("\n  Face Attendance is starting (100% offline)")
    print("  Keep this window open while the system is in use. Close it to stop.\n")
    print(f"  This computer : {scheme}://127.0.0.1:{a.port}")
    print(f"  Kiosk screen  : {scheme}://127.0.0.1:{a.port}/kiosk")
    print(f"  Admin (LAN)   : {scheme}://{ip}:{a.port}/admin\n")
    log("starting; loading models...")
    from app.main import app
    import threading
    threading.Thread(target=_announce_ready, args=(a.port, scheme, not a.no_browser), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning", **ssl)


def log(msg):
    try:
        d = DATA_DIR.parent / "logs"
        d.mkdir(exist_ok=True)
        import time
        with open(d / "app.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


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
        log = DATA_DIR.parent / "logs"
        log.mkdir(exist_ok=True)
        (log / "error.log").write_text(
            f"Python {sys.version}\n\n" + traceback.format_exc(), encoding="utf-8")
        print("\n  The app could not start.\n")
        print(traceback.format_exc())
        print(f"  This was saved to: {log / 'error.log'}")
        print("  Please send that file (or a photo of this window) to your support person.\n")
        input("  Press Enter to close...")
        sys.exit(1)
