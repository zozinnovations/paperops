"""Audio end-to-end: WAV -> backend Whisper (app/stt.py) -> variant B -> ticket.
Prints transcription time + variant B time = total.

Usage:  python scripts/test_audio.py [--wav samples/T01.wav] [--case T01] [--runs 3]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from common import CASES, PRIMARY_MODEL, ROOT, check_ticket, make_client
from test_fast import run_fast

sys.path.insert(0, str(ROOT))
from app import stt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", default=str(ROOT / "samples" / "T01.wav"))
    ap.add_argument("--case", default="T01")
    ap.add_argument("--model", default=PRIMARY_MODEL)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    audio = Path(args.wav).read_bytes()
    case = CASES[args.case]
    t0 = time.perf_counter()
    stt.warm_up()
    print(f"STT {stt.STT_BACKEND}:{stt.WHISPER_MODEL} (beam {stt.WHISPER_BEAM}) loaded in {time.perf_counter() - t0:.2f}s\n")

    client = make_client()
    for i in range(args.runs):
        s = stt.transcribe(audio)
        r = run_fast(client, args.model, dict(case, payload=dict(case["payload"], transcript=s["text"])), verbose=False)
        ok, fails = check_ticket(r["ticket"], case["expected"]) if r["ticket"] else (False, ["invalid output"])
        print(f"run {i + 1}: STT {s['seconds']:.2f}s + variant B {r['total']:.2f}s = {s['seconds'] + r['total']:.2f}s"
              f"  correct: {'yes' if ok else fails}")
        print(f"   transcript: {s['text']!r}")
    if r["ticket"]:
        print("\n" + json.dumps(r["ticket"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
