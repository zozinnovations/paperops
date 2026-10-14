"""Copies the latest cached Gemma answers for the 12 test transcripts into replay/ (run after a prompt change
and a passing scripts/bench_cases.py run), replacing the old replay files."""
import hashlib
import json
import shutil

from common import CASES, ROOT, check_ticket

from app import pipeline

MODEL = "Gemma-4-31B-IT"
sha = hashlib.sha256(pipeline.SYSTEM_PROMPT.encode()).hexdigest()[:16]
wanted = {c["payload"]["transcript"]: cid for cid, c in CASES.items()}
found = {}
for f in sorted((ROOT / "cache").glob("*.json")):
    e = json.loads(f.read_text(encoding="utf-8"))
    if e["system_sha"] == sha and e["user"] in wanted and e["model"] == MODEL:
        found[wanted[e["user"]]] = (f, e)

missing = sorted(set(CASES) - set(found))
if missing:
    raise SystemExit(f"no cached {MODEL} answer for {missing} - run scripts/bench_cases.py first")
bad = []
for cid, (f, e) in found.items():  # only replay answers that still produce a correct ticket
    fault = json.loads(e["content"])
    pipeline.llm.json_call = lambda *a, _fault=fault, **k: (_fault, {"model": MODEL, "replay": True, "attempts": []})
    ticket, _, _ = pipeline.run_sync(CASES[cid]["payload"]["transcript"])
    ok, fails = check_ticket(ticket, CASES[cid]["expected"])
    if not ok:
        bad.append(f"{cid}: {fails}")
if bad:
    raise SystemExit("cached answers that give a wrong ticket: " + "; ".join(bad))
for f in (ROOT / "replay").glob("*.json"):
    f.unlink()
for f, _ in found.values():
    shutil.copy(f, ROOT / "replay" / f.name)
print(f"replay/: {len(found)} {MODEL} answers for prompt {sha}")
