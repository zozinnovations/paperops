"""Speech-to-text behind one function: transcribe(audio_bytes) -> {"text", "seconds", "backend"}.

faster-whisper on CPU in our backend (final: the Token Factory offers no audio model before the deadline).
"""
import io
import json
import os
import threading
import time
from pathlib import Path

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en")
WHISPER_DIR = os.getenv("WHISPER_DIR") or None  # Docker bakes the model in here at build time
WHISPER_BEAM = int(os.getenv("WHISPER_BEAM", "1"))
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS") or min(8, os.cpu_count() or 4))  # 8 vs default 4: 1.4 s vs 1.8 s
BACKEND = f"faster-whisper:{WHISPER_MODEL}"

_MANUAL = Path(__file__).resolve().parent.parent / "data" / "machines_manual.json"


def _initial_prompt():
    """Plant vocabulary for Whisper: machine names, aliases and error codes (spoken and written)."""
    machines = json.loads(_MANUAL.read_text(encoding="utf-8"))["machines"]
    names, codes = [], []
    for m in machines:
        names += [m["machine_id"], *m["aliases"]]
        codes += [e["code"] for e in m["error_codes"]]
    return ("Maintenance report. Machines: " + ", ".join(names) + ". Error codes: " + ", ".join(codes)
            + ". For example: Press three, error E four oh two.")


INITIAL_PROMPT = _initial_prompt()

_model, _lock = None, threading.Lock()


def _local_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=WHISPER_DIR,
                                  cpu_threads=WHISPER_THREADS)
    return _model


def warm_up():
    """Load the model at startup so the first request is not slow."""
    _local_model()


def transcribe(audio: bytes) -> dict:
    t0 = time.perf_counter()
    segments, _ = _local_model().transcribe(
        io.BytesIO(audio),  # any format PyAV can decode: wav, webm/opus from the browser, ...
        language="en",
        beam_size=WHISPER_BEAM,
        initial_prompt=INITIAL_PROMPT,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "seconds": time.perf_counter() - t0, "backend": BACKEND}
