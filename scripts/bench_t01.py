"""Runs T01 through variant A (tool calling) for all models and variant B (single call) on MiMo,
logs per-step times and prints a comparison table.

Usage:  python scripts/bench_t01.py [--case T01]
"""
import argparse
import json

from common import CASES, FALLBACK_MODELS, PRIMARY_MODEL, check_ticket, make_client
from test_fast import run_fast
from test_t01 import run_agent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="T01")
    args = ap.parse_args()
    case = CASES[args.case]
    client = make_client()

    runs = [("A tool calling", m, run_agent) for m in [PRIMARY_MODEL, *FALLBACK_MODELS]]
    runs.append(("B single call", PRIMARY_MODEL, run_fast))

    rows = []
    for variant, model, fn in runs:
        print(f"\n=== {variant} | {model} ===")
        try:
            r = fn(client, model, case)
        except Exception as e:  # keep benchmarking the other models
            print(f"  ERROR: {type(e).__name__}: {e}")
            rows.append((variant, model, None, f"error ({type(e).__name__})"))
            continue
        for name, dt in r["timings"]:
            print(f"  {name:<24} {dt * 1000:9.1f} ms")
        if r["ticket"] is None:
            print("  INVALID JSON: " + r["raw"][:300])
            rows.append((variant, model, r["total"], "no (invalid JSON)"))
            continue
        print(json.dumps(r["ticket"], indent=2, ensure_ascii=False))
        ok, fails = check_ticket(r["ticket"], case["expected"])
        rows.append((variant, model, r["total"], "yes" if ok else "no - " + "; ".join(fails)))

    print(f"\n| Variant | Model | Total time | Ticket correct |\n|---|---|---|---|")
    for variant, model, total, ok in rows:
        print(f"| {variant} | {model} | {f'{total:.2f} s' if total is not None else '-'} | {ok} |")


if __name__ == "__main__":
    main()
