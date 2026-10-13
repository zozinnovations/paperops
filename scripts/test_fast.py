"""Variant B - one model call extracts {machine_id, error_code, part, symptoms, transcript};
manual, inventory and recurring-fault lookups and the ticket are built in code (app/pipeline.py).

Usage:  python scripts/test_fast.py [--model MODEL] [--case T01]
"""
import argparse
import json
import time

from common import CASES, PRIMARY_MODEL, check_ticket

from app import pipeline


def run_fast(model, case, transcript=None, verbose=True):
    """Runs the app pipeline pinned to one model. Returns {ticket, info, timings, total}."""
    t_start = time.perf_counter()
    try:
        ticket, timings, info = pipeline.run_sync(transcript or case["payload"]["transcript"], models=[model])
    except RuntimeError as e:  # every attempt failed (API error or invalid output)
        return {"ticket": None, "raw": str(e), "timings": [], "total": time.perf_counter() - t_start}
    if verbose:
        print(f"  [model] {info['model']}  -> {json.dumps(info['fault'], ensure_ascii=False)}")
    return {"ticket": ticket, "info": info, "timings": timings, "total": time.perf_counter() - t_start}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=PRIMARY_MODEL)
    ap.add_argument("--case", default="T01")
    args = ap.parse_args()

    case = CASES[args.case]
    print(f"Variant B (single call)  Model: {args.model}  Case: {case['id']} - {case['payload']['transcript']}\n")
    r = run_fast(args.model, case)
    for name, dt in r["timings"]:
        print(f"  {name:<18} {dt * 1000:9.1f} ms")
    if r["ticket"] is None:
        print("FAILED:\n" + r["raw"])
    else:
        print("\n--- Ticket JSON ---\n" + json.dumps(r["ticket"], indent=2, ensure_ascii=False))
        ok, fails = check_ticket(r["ticket"], case["expected"])
        print("Ticket correct:", "yes" if ok else f"no - {fails}")
    print(f"Total response time: {r['total']:.2f}s")


if __name__ == "__main__":
    main()
