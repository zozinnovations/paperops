"""PaperOps web app: push-to-talk / text -> STT -> variant B pipeline -> ESC/POS -> printer or simulator.

Run:  uvicorn app.main:app --port 8000
"""
import base64
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict, defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import escpos, health, llm, pipeline, printer, stt  # noqa: E402
from .data import CASES, HISTORY, demo_stamp  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("paperops")

PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
MAX_AUDIO_BYTES = 5 * 1024 * 1024
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "10"))  # per client IP; the team key allows ~20/min in total
SAMPLES = ROOT / "samples"
STATIC = Path(__file__).resolve().parent / "static"

_ASSET_VERSION = hashlib.sha256(b"".join((STATIC / n).read_bytes() for n in ("app.js", "escpos.js", "style.css"))
                                ).hexdigest()[:10]

app = FastAPI(title="PaperOps")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_stale_assets(request: Request, call_next):
    """Browsers must revalidate the page and its JS/CSS (cheap via ETag): after a deploy a cached old
    escpos.js would mis-render new printer commands."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
if SAMPLES.exists():
    app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")

_busy = threading.BoundedSemaphore(4)       # Token Factory allows 8 concurrent requests per key
_hits = defaultdict(deque)
_tickets = OrderedDict()                   # id -> result, newest last (in memory)
_drafts = OrderedDict()                    # draft id -> report that needs clarification (not printed, no number)
_FIRST_ID = max(int(t["id"].split("-")[1]) for t in HISTORY) + 1  # 941: continues the ticket history
_next_id = [_FIRST_ID]
_id_lock = threading.Lock()


@app.on_event("startup")
def startup():
    # model discovery and Whisper loading in the background, so the server answers immediately
    threading.Thread(target=llm.discover_models, daemon=True).start()
    threading.Thread(target=stt.warm_up, daemon=True).start()


def _rate_limited(ip):
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


def _new_id():
    with _id_lock:
        _next_id[0] += 1
        return _next_id[0] - 1


@app.get("/api/health")
def api_health():
    """Liveness for the hosting platform - no external calls."""
    return {"ok": True}


@app.get("/")
def index(request: Request, mode: str = ""):
    # versioned asset URLs: a browser that cached an old escpos.js before no-cache headers existed would
    # still mis-render new printer commands (e.g. ESC 3 shown as a box)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "escpos.js", "style.css"):
        html = html.replace(f"/static/{name}\"", f"/static/{name}?v={_ASSET_VERSION}\"")
    # link previews need an absolute image URL
    html = html.replace("__OG_IMAGE__", f"{PUBLIC_URL or str(request.base_url).rstrip('/')}/static/og.png")
    if mode == "floor":
        # shop-floor mode: only the button, progress and the receipt (set server-side, so nothing flashes)
        html = html.replace("<body>", '<body class="floor">', 1)
    return HTMLResponse(html)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon.ico", media_type="image/x-icon")


@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(STATIC / "apple-touch-icon.png", media_type="image/png")


@app.post("/api/reset")
def api_reset(request: Request):
    """Reset demo: clear recent tickets and drafts, numbering restarts at the first number after the history."""
    if _rate_limited(request.client.host if request.client else "?"):
        raise HTTPException(429, "Too many requests - please wait a minute.")
    with _id_lock:
        _tickets.clear()
        _drafts.clear()
        _next_id[0] = _FIRST_ID
    log.info("demo reset: numbering restarts at #%s", _FIRST_ID)
    return {"ok": True, "next_id": _FIRST_ID}


@app.get("/api/status")
def api_status():
    models = llm.chain()  # while the model list is unknown this also retries discovery in the background
    return {"printer": printer.status(), "printer_host": printer.PRINTER_HOST or None,
            "models": models if llm._available is not None else [], "stt": stt.BACKEND,
            "replay_mode": llm.REPLAY_MODE}


@app.get("/api/samples")
def api_samples():
    return [{"id": cid, "transcript": c["payload"]["transcript"], "difficulty": c["difficulty"],
             "label": c.get("label", cid), "featured": c.get("featured", False),
             "audio": f"/samples/{cid}.wav" if (SAMPLES / f"{cid}.wav").exists() else None}
            for cid, c in CASES.items()]


@app.get("/api/machines")
def api_machines():
    """Machine health table: history (30 days on the demo clock) plus tickets printed in this app."""
    return health.machine_health([r["ticket"] for r in _tickets.values()])


@app.get("/api/tickets")
def api_tickets():
    return [{"id": r["id"], "machine_id": r["ticket"].get("machine_id") or "UNKNOWN",
             "priority": r["ticket"]["priority"], "error_code": r["ticket"].get("error_code"), "created": r["created"]}
            for r in reversed(_tickets.values())]


@app.get("/api/tickets/{ticket_id}")
def api_ticket(ticket_id: int):
    if ticket_id not in _tickets:
        raise HTTPException(404, "Ticket not found")
    return _tickets[ticket_id]


def _finalize(ticket, text, model_info, base_url, timings):
    """Number the ticket, render ESC/POS, send it to the printer (or the simulator) and keep it."""
    t0 = time.perf_counter()
    ticket_id = _new_id()
    created = demo_stamp()  # demo clock, consistent with "3x in 12 days" and Machine health
    ticket["qr_action_url"] = f"{PUBLIC_URL or base_url.rstrip('/')}/?ticket={ticket_id}"
    footer = f"{model_info['model']} on AMD GPUs via AMD Token Factory"
    data = escpos.render(ticket, ticket_id, created, footer, replay=model_info["replay"])
    print_status = printer.send(data)
    timings = dict(timings, printing=time.perf_counter() - t0)
    result = {"id": ticket_id, "created": created, "transcript": text, "ticket": ticket,
              "escpos": base64.b64encode(data).decode(), "printer": print_status, **model_info,
              "timings_ms": {k: round(v * 1000) for k, v in timings.items()}}
    _tickets[ticket_id] = result
    while len(_tickets) > 50:
        _tickets.popitem(last=False)
    log.info("ticket #%s %s %s %s (%s, %s)", ticket_id, ticket.get("machine_id"), ticket.get("error_code"),
             ticket["priority"], model_info["model"], print_status)
    return result


def _event(**kw):
    return json.dumps(kw, ensure_ascii=False) + "\n"


def _process(audio, text, base_url, replay_for=None):
    """Generator of NDJSON progress events: listening, understanding, manual, stock, printing, result."""
    t_total = time.perf_counter()
    timings = {}
    try:
        if audio:
            yield _event(step="listening", status="active")
            s = stt.transcribe(audio)
            text = s["text"]
            timings["listening"] = s["seconds"]
            yield _event(step="listening", status="done", ms=round(s["seconds"] * 1000), transcript=text,
                         backend=s["backend"])
        else:
            yield _event(step="listening", status="skipped", note="text input", transcript=text)
        if not text.strip():
            yield _event(step="error", message="No speech recognised - please try again.")
            return

        yield _event(step="understanding", status="active")
        model_info, ticket = {}, None
        for step, dt, data in pipeline.run(text, replay_for=replay_for):
            if step == "ticket":
                ticket = data
                break
            timings[step] = dt
            if step == "understanding":
                model_info = {"model": data["model"], "replay": data["replay"], "attempts": data["attempts"]}
                if data["replay"] and data.get("recorded_seconds") is not None:
                    # show the recorded run's own timing, not how long we waited for the live models
                    model_info["waited_ms"] = round(dt * 1000)
                    timings[step] = dt = data["recorded_seconds"]
            yield _event(step=step, status="done", ms=round(dt * 1000), **({"model": model_info["model"],
                         "replay": model_info["replay"]} if step == "understanding" else {}))
            nxt = {"understanding": "manual", "manual": "stock", "stock": "printing"}[step]
            yield _event(step=nxt, status="active")

        if ticket.get("clarify"):
            # nothing recognised (nonsense, small talk, machine without a fault): ask back instead of
            # wasting paper; the technician can still print it with "Print anyway"
            draft_id = uuid.uuid4().hex[:12]
            _drafts[draft_id] = {"ticket": ticket, "transcript": text, "model_info": model_info, "base_url": base_url}
            while len(_drafts) > 50:
                _drafts.popitem(last=False)
            total = time.perf_counter() - t_total
            yield _event(step="printing", status="skipped", note="not printed")
            log.info("clarification needed (%s) for %r", ticket.get("machine_id") or "UNKNOWN", text[:80])
            yield _event(step="clarify", draft=draft_id, question=ticket["clarify"], transcript=text, ticket=ticket,
                         **model_info, timings_ms={k: round(v * 1000) for k, v in timings.items()},
                         total_ms=round(total * 1000))
            return

        result = _finalize(ticket, text, model_info, base_url, timings)
        result["total_ms"] = (sum(result["timings_ms"].values()) if model_info["replay"]
                              else round((time.perf_counter() - t_total) * 1000))
        yield _event(step="printing", status="done", ms=result["timings_ms"]["printing"], printer=result["printer"])
        yield _event(step="result", **result)
    except llm.AllModelsFailed as e:
        log.warning("ticket failed: %s", e)
        yield _event(step="error", message="The AI service is not reachable right now. "
                                           "Please try one of the sample recordings - they also work offline.")
    except Exception as e:  # report to the UI instead of a broken stream
        log.exception("ticket failed")
        yield _event(step="error", message=f"{type(e).__name__}: {e}")
    finally:
        _busy.release()


@app.post("/api/drafts/{draft_id}/print")
def api_print_draft(request: Request, draft_id: str):
    """ "Print anyway" for a report that needed clarification: turns the draft into a numbered ticket."""
    if _rate_limited(request.client.host if request.client else "?"):
        raise HTTPException(429, "Too many requests - please wait a minute.")
    draft = _drafts.pop(draft_id, None)
    if draft is None:
        raise HTTPException(404, "Draft not found or already printed")
    ticket = {k: v for k, v in draft["ticket"].items() if k != "clarify"}
    result = _finalize(ticket, draft["transcript"], draft["model_info"], draft["base_url"], {})
    result["total_ms"] = result["timings_ms"]["printing"]
    return result


@app.post("/api/ticket")
async def api_create_ticket(request: Request, audio: UploadFile | None = File(None), text: str = Form(""),
                            sample: str = Form("")):
    if _rate_limited(request.client.host if request.client else "?"):
        raise HTTPException(429, "Too many requests - please wait a minute.")
    data, replay_for = None, None
    if sample:
        path = SAMPLES / f"{sample}.wav"
        if sample not in CASES or not path.exists():
            raise HTTPException(404, "Unknown sample")
        data = path.read_bytes()
        replay_for = CASES[sample]["payload"]["transcript"]
    elif audio is not None:
        data = await audio.read()
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Recording too long")
    elif not text.strip():
        raise HTTPException(400, "Send audio, text or a sample id")
    text = text.strip()[:1000]
    if not _busy.acquire(blocking=False):  # released when the stream generator finishes
        raise HTTPException(503, "Busy - please try again in a few seconds.")
    return StreamingResponse(_process(data, text, str(request.base_url), replay_for), media_type="application/x-ndjson")
