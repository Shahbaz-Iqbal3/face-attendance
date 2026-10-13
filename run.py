"""Start the server.  python run.py [--port 8000] [--https]"""
import argparse
import socket
import sys

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    ap.add_argument("--https", action="store_true", help="serve over HTTPS (lets other PCs use the camera)")
    a = ap.parse_args()
    scheme = "https" if a.https else "http"
    ssl = {}
    if a.https:
        ssl["ssl_certfile"], ssl["ssl_keyfile"] = make_cert()
    ip = lan_ip()
    print("\n  Face Attendance is starting (100% offline)\n")
    print(f"  This computer : {scheme}://localhost:{a.port}")
    print(f"  Kiosk screen  : {scheme}://localhost:{a.port}/kiosk")
    print(f"  Admin (LAN)   : {scheme}://{ip}:{a.port}/admin\n")
    from app.main import app
    if not a.no_browser:
        import threading, webbrowser
        threading.Timer(2.5, lambda: webbrowser.open(f"{scheme}://localhost:{a.port}/")).start()
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning", **ssl)


if __name__ == "__main__":
    main()
