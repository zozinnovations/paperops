"""Sends ESC/POS bytes to a thermal printer, or reports "simulator".

Two ways to the printer:
- LAN printer: raw TCP, port 9100 (PRINTER_HOST / PRINTER_PORT).
- USB printer on Windows: PRINTER_NAME = the printer's name in Windows (e.g. "POS-80C", driver
  "Generic / Text Only"). The bytes go unchanged through the Windows print spooler as a RAW job
  (winspool via ctypes, no extra package). Takes precedence over PRINTER_HOST.

The LAN target comes from PRINTER_HOST / PRINTER_PORT, or from the "Printer settings" dialog when
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
WINDOWS_NAME = os.getenv("PRINTER_NAME", "").strip() if os.name == "nt" else ""
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


# ---------- USB printer through the Windows spooler ----------
if WINDOWS_NAME:
    import ctypes
    from ctypes import wintypes

    class _DocInfo1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    _winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    _PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x400
    _PRINTER_STATUS_BAD = 0x2 | 0x8 | 0x80 | 0x400000  # error, paper jam, offline, not available


def _win_open():
    handle = wintypes.HANDLE()
    if not _winspool.OpenPrinterW(WINDOWS_NAME, ctypes.byref(handle), None):
        raise OSError(ctypes.get_last_error(), f"Windows printer {WINDOWS_NAME!r} not found")
    return handle


def _win_online():
    """Printer known to Windows and not offline (Windows marks an unplugged USB printer offline)."""
    handle = _win_open()
    try:
        needed = wintypes.DWORD()
        _winspool.GetPrinterW(handle, 2, None, 0, ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if not _winspool.GetPrinterW(handle, 2, buf, needed, ctypes.byref(needed)):
            return True  # opened fine; no details
        # PRINTER_INFO_2: 13 pointers, then Attributes, Priority, DefaultPriority, StartTime, UntilTime, Status
        ptr = ctypes.sizeof(ctypes.c_void_p)
        attributes = int.from_bytes(buf.raw[13 * ptr:13 * ptr + 4], "little")
        status_bits = int.from_bytes(buf.raw[13 * ptr + 20:13 * ptr + 24], "little")
        return not (attributes & _PRINTER_ATTRIBUTE_WORK_OFFLINE or status_bits & _PRINTER_STATUS_BAD)
    finally:
        _winspool.ClosePrinter(handle)


def _win_send(data):
    handle = _win_open()
    try:
        if not _winspool.StartDocPrinterW(handle, 1, ctypes.byref(_DocInfo1("PaperOps ticket", None, "RAW"))):
            raise OSError(ctypes.get_last_error(), "StartDocPrinter failed")
        try:
            _winspool.StartPagePrinter(handle)
            written = wintypes.DWORD()
            buf = ctypes.create_string_buffer(data, len(data))
            if not _winspool.WritePrinter(handle, buf, len(data), ctypes.byref(written)) or written.value != len(data):
                raise OSError(ctypes.get_last_error(), "WritePrinter failed")
            _winspool.EndPagePrinter(handle)
        finally:
            _winspool.EndDocPrinter(handle)
    finally:
        _winspool.ClosePrinter(handle)


def target():
    """Human-readable printer target, e.g. for the test page."""
    if WINDOWS_NAME:
        return f"Windows printer {WINDOWS_NAME} (USB)"
    cfg = config()
    return f"{cfg['host']}:{cfg['port']}" if cfg["host"] else "simulator"


def status():
    """'connected', 'offline' (printer set but unreachable) or 'simulator' (none). Cached for 10 s."""
    if WINDOWS_NAME:
        if time.time() - _status["checked"] > 10:
            try:
                _status["online"] = _win_online()
            except OSError:
                _status["online"] = False
            _status["checked"] = time.time()
        return "connected" if _status["online"] else "offline"
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
    if WINDOWS_NAME:
        try:
            _win_send(data)
            _status.update(checked=time.time(), online=True)
            return "printed"
        except OSError:
            _status.update(checked=time.time(), online=False)
            return "simulator"
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
