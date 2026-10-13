"""Runs every test case in data/test_transcripts.json through variant B (single call, text input)
and prints a table: case, expected, result, pass/fail, time.

Usage:  python scripts/bench_cases.py [--model MODEL] [--cases T01,T02]
"""
import argparse
import json

from common import CASES, PRIMARY_MODEL, check_ticket
from test_fast import run_fast


def short(d, keys):
    return ", ".join(str(d[k]) for k in keys if d.get(k) not in (None, ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=PRIMARY_MODEL)
    ap.add_argument("--cases", help="comma-separated case IDs (default: all)")
    args = ap.parse_args()
    ids = args.cases.split(",") if args.cases else list(CASES)

    rows = []
    for cid in ids:
        case = CASES[cid]
        print(f"\n=== {cid} ({case['difficulty']}) - {case['payload']['transcript']}")
        exp = case["expected"]
        exp_txt = short(exp, ["machine", "priority", "cause_code", "part_needed"])
        try:
            r = run_fast(args.model, case)
        except Exception as e:  # keep going with the other cases
            print(f"  ERROR: {type(e).__name__}: {e}")
            rows.append((cid, exp_txt, f"error ({type(e).__name__})", "FAIL", "-"))
            continue
        for name, dt in r["timings"]:
            print(f"  {name:<18} {dt * 1000:9.1f} ms")
        t = r["ticket"]
        if t is None:
            print("  FAILED: " + r["raw"][:300])
            rows.append((cid, exp_txt, "model failed", "FAIL", f"{r['total']:.2f} s"))
            continue
        print(json.dumps(t, indent=2, ensure_ascii=False))
        ok, fails = check_ticket(t, exp)
        res_txt = short(t, ["machine", "priority", "error_code", "part_needed"])
        rows.append((cid, exp_txt, res_txt, "pass" if ok else "FAIL: " + "; ".join(fails), f"{r['total']:.2f} s"))

    print(f"\nModel: {args.model}\n\n| Case | Expected | Result | Pass/Fail | Time |\n|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(row) + " |")
    passed = sum(1 for r in rows if r[3] == "pass")
    print(f"\n{passed}/{len(rows)} passed")


if __name__ == "__main__":
    main()
