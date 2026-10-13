"""Speech-to-text behind one function: transcribe(audio_bytes) -> {"text", "seconds", "backend"}.

STT_BACKEND=local       faster-whisper on CPU (default)
STT_BACKEND=tokenfactory Whisper on the AMD Token Factory (once AMD enables an audio model)
"""
import io
import json
import os
import threading
import time
from pathlib import Path

STT_BACKEND = os.getenv("STT_BACKEND", "local")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en")
WHISPER_DIR = os.getenv("WHISPER_DIR") or None  # Docker bakes the model in here at build time
WHISPER_BEAM = int(os.getenv("WHISPER_BEAM", "1"))
TF_STT_MODEL = os.getenv("TF_STT_MODEL", "whisper-large-v3")

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
            _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=WHISPER_DIR)
    return _model


def _transcribe_local(audio):
    segments, _ = _local_model().transcribe(
        io.BytesIO(audio),  # any format PyAV can decode: wav, webm/opus from the browser, ...
        language="en",
        beam_size=WHISPER_BEAM,
        initial_prompt=INITIAL_PROMPT,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()


def _transcribe_tokenfactory(audio):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["RADEON_API_KEY"], base_url=os.environ["RADEON_BASE_URL"], timeout=30)
    r = client.audio.transcriptions.create(model=TF_STT_MODEL, file=("audio.wav", audio), language="en",
                                           prompt=INITIAL_PROMPT)
    return r.text.strip()


def warm_up():
    """Load the local model at startup so the first request is not slow."""
    if STT_BACKEND == "local":
        _local_model()


def transcribe(audio: bytes) -> dict:
    t0 = time.perf_counter()
    if STT_BACKEND == "tokenfactory":
        text = _transcribe_tokenfactory(audio)
    else:
        text = _transcribe_local(audio)
    return {"text": text, "seconds": time.perf_counter() - t0, "backend": f"{STT_BACKEND}:{WHISPER_MODEL}"}
