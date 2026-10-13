"""Sends ESC/POS bytes to a LAN thermal printer (raw TCP, port 9100) if PRINTER_HOST is set."""
import os
import socket
import time

PRINTER_HOST = os.getenv("PRINTER_HOST", "").strip()
PRINTER_PORT = int(os.getenv("PRINTER_PORT") or 9100)

_status = {"checked": 0.0, "online": False}


def status():
    """'connected', 'offline' (host set but unreachable) or 'simulator' (no host). Cached for 10 s."""
    if not PRINTER_HOST:
        return "simulator"
    if time.time() - _status["checked"] > 10:
        try:
            with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=1.5):
                _status["online"] = True
        except OSError:
            _status["online"] = False
        _status["checked"] = time.time()
    return "connected" if _status["online"] else "offline"


def send(data: bytes):
    """Returns 'printed', or 'simulator' if there is no printer / it is unreachable."""
    if not PRINTER_HOST:
        return "simulator"
    try:
        with socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=3) as s:
            s.sendall(data)
        _status.update(checked=time.time(), online=True)
        return "printed"
    except OSError:
        _status.update(checked=time.time(), online=False)
        return "simulator"
