"""Makes app/static/og.png (1200x675, 16:9): a real screenshot of the running app with the T01 ticket.

Needs the app running (default http://localhost:8000) and a Chromium-based browser for the headless
screenshot (Edge on Windows by default). Resets the demo, creates ticket #941 from the T01 text, then
captures /?ticket=941 at 2x and scales it down for crisp text.

Usage:  python scripts/make_og_image.py [--url http://localhost:8000] [--browser PATH]
"""
import argparse
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "og.png"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
T01 = "Press three is stuck. Error E four oh two. The axis is running hot."
W, H = 1200, 675


def post(url, data=None):
    body, headers = None, {}
    if data:
        boundary = "paperopsogimage"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n{data}\r\n--{boundary}--\r\n"
                ).encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    with urllib.request.urlopen(urllib.request.Request(url, data=body or b"", headers=headers, method="POST"),
                                timeout=60) as r:
        return r.read().decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--browser", default=EDGE)
    args = ap.parse_args()

    post(f"{args.url}/api/reset")
    stream = post(f"{args.url}/api/ticket", T01)
    if '"step": "result"' not in stream:
        raise SystemExit("ticket was not created: " + stream[-300:])

    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "shot.png"
        subprocess.run([args.browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--user-data-dir={tmp}", "--force-device-scale-factor=2",
                        f"--window-size={W},{H}", "--virtual-time-budget=8000",
                        f"--screenshot={shot}", f"{args.url}/?ticket=941"], check=True, timeout=120)
        for _ in range(20):  # the browser may return before the file is flushed
            if shot.exists() and shot.stat().st_size:
                break
            time.sleep(0.5)
        Image.open(shot).convert("RGB").resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
