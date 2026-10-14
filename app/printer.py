"""Sends ESC/POS bytes to a LAN thermal printer (raw TCP, port 9100), or reports "simulator".

The target comes from PRINTER_HOST / PRINTER_PORT, or from the "Printer settings" dialog when
ALLOW_PRINTER_SETUP=1 (local installs only). Settings are applied at once and kept in cache/printer.json.
Even then only local-network targets are accepted (private, loopback or link-local addresses): the app must
never be usable to open connections to arbitrary hosts. On the hosted demo the setup stays disabled.
"""
import ipaddress
import json
import os
import re
import socket
import threading
import time
from pathlib import Path

ALLOW_SETUP = os.getenv("ALLOW_PRINTER_SETUP", "0") == "1"
_SAVED = Path(__file__).resolve().parent.parent / "cache" / "printer.json"
_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")

_lock = threading.Lock()
_cfg = {"host": os.getenv("PRINTER_HOST", "").strip(), "port": int(os.getenv("PRINTER_PORT") or 9100)}
_status = {"checked": 0.0, "online": False}

if ALLOW_SETUP and _SAVED.exists():  # settings saved from the dialog win over .env
    try:
        _cfg.update(json.loads(_SAVED.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def config():
    with _lock:
        return dict(_cfg)


def _check_target(host, port):
    """Raises ValueError unless host:port is a plausible printer on the local network."""
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Port must be a number from 1 to 65535.")
    try:
        ip = ipaddress.ip_address(host)
        addresses = [ip]
    except ValueError:
        if not _HOSTNAME.match(host):
            raise ValueError("Enter an IP address or a host name.")
        try:
            addresses = {ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        except OSError:
            raise ValueError(f"Host name {host!r} could not be resolved.")
    for ip in addresses:
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            raise ValueError("Only printers on the local network are allowed (private IP address).")


def configure(host, port):
    """Apply and save new printer settings (empty host = simulator). Raises PermissionError / ValueError."""
    if not ALLOW_SETUP:
        raise PermissionError("Printer setup is disabled (set ALLOW_PRINTER_SETUP=1 on a local install).")
    host = (host or "").strip()
    if host:
        _check_target(host, port)
    with _lock:
        _cfg.update(host=host, port=port)
        _status.update(checked=0.0, online=False)
    _SAVED.parent.mkdir(exist_ok=True)
    _SAVED.write_text(json.dumps(_cfg), encoding="utf-8")
    return status()


def status():
    """'connected', 'offline' (host set but unreachable) or 'simulator' (no host). Cached for 10 s."""
    cfg = config()
    if not cfg["host"]:
        return "simulator"
    if time.time() - _status["checked"] > 10:
        try:
            with socket.create_connection((cfg["host"], cfg["port"]), timeout=1.5):
                _status["online"] = True
        except OSError:
            _status["online"] = False
        _status["checked"] = time.time()
    return "connected" if _status["online"] else "offline"


def send(data: bytes):
    """Returns 'printed', or 'simulator' if there is no printer / it is unreachable."""
    cfg = config()
    if not cfg["host"]:
        return "simulator"
    try:
        with socket.create_connection((cfg["host"], cfg["port"]), timeout=3) as s:
            s.sendall(data)
        _status.update(checked=time.time(), online=True)
        return "printed"
    except OSError:
        _status.update(checked=time.time(), online=False)
        return "simulator"
