"""Machine health: reports, downtime and top fault per machine over the last 30 days, plus a simple,
honest outlook ("trend-based estimate"), all counted on the demo clock (data.demo_now()).

Outlook rules
- the same fault >= 3 times with shrinking intervals -> "next <code> expected in ~N days"
  (last occurrence + the average of the last intervals)
- a part used for a recurring fault has stock 0 and is not reordered -> "<part> out of stock - reorder"
- a part of this machine is below its minimum stock -> "<part> below minimum stock"
- otherwise "ok"
Predictions use the maintenance history only: tickets created in the app count as reports, but repeated
demo runs must not shrink the intervals to zero.
"""
from collections import Counter
from datetime import datetime, timedelta

from .data import INVENTORY, MANUAL, arrives_text, demo_now, recent_history

_BY_SKU = {p["sku"]: p for p in INVENTORY}
_BY_NAME = {p["name"]: p for p in INVENTORY}


def _days(delta):
    return delta.total_seconds() / 86400


def _trend(code, times, now):
    """Outlook line if the fault is accelerating (>= 3 times, each interval shorter than the one before)."""
    if len(times) < 3:
        return None
    intervals = [_days(b - a) for a, b in zip(times, times[1:])]
    if not all(later < earlier for earlier, later in zip(intervals, intervals[1:])):
        return None
    recent = intervals[-3:]
    avg = sum(recent) / len(recent)
    due = _days(times[-1] + timedelta(days=avg) - now)
    pattern = " → ".join(f"{i:.0f}" for i in intervals)
    if due < 0.5:
        return {"level": "warn", "text": f"next {code} expected any day now (intervals {pattern} days)"}
    return {"level": "warn", "text": f"next {code} expected in ~{round(due)} days (intervals {pattern} days)"}


def _stock_lines(machine, history, codes_count):
    lines, flagged = [], set()
    # parts used for a recurring fault that are gone and not reordered
    for t in history:
        part = _BY_SKU.get(t.get("part_used") or "")
        if part and codes_count[t["code"]] >= 2 and part["stock"] == 0 and part["sku"] not in flagged:
            if (part.get("reorder") or {}).get("status") in (None, "not ordered"):
                lines.append({"level": "alert", "text": f"{part['name']} out of stock – reorder"})
                flagged.add(part["sku"])
    # every part this machine uses (manual + history) that is below its minimum stock
    names = {p["part"] for e in machine["error_codes"] for p in e["parts"]}
    names |= {_BY_SKU[t["part_used"]]["name"] for t in history if t.get("part_used") in _BY_SKU}
    for name in sorted(names):
        part = _BY_NAME.get(name)
        if part and part["stock"] < part["min_stock"] and part["sku"] not in flagged:
            reorder = part.get("reorder") or {}
            note = ""
            if reorder.get("status") == "ordered":
                note = "; already reordered" + (f" – {arrives_text(reorder['eta'])}" if reorder.get("eta") else "")
            lines.append({"level": "warn",
                          "text": f"{part['name']} below minimum stock ({part['stock']} of {part['min_stock']}{note})"})
            flagged.add(part["sku"])
    return lines


def machine_health(app_tickets=()):
    """app_tickets: tickets created in the app, as dicts with machine_id and error_code."""
    now = demo_now()
    history = recent_history()
    rows = []
    for m in MANUAL:
        hist = sorted((t for t in history if t["machine_id"] == m["machine_id"]), key=lambda t: t["ts"])
        new = [t for t in app_tickets if t.get("machine_id") == m["machine_id"] and t.get("error_code")]
        codes = Counter([t["code"] for t in hist] + [t["error_code"] for t in new])
        top = None
        if codes:
            code, n = max(codes.items(), key=lambda kv: (kv[1], max((t["ts"] for t in hist if t["code"] == kv[0]),
                                                                       default="")))
            top = {"code": code, "count": n}
        outlook = []
        for code in sorted({t["code"] for t in hist}):
            times = [datetime.fromisoformat(t["ts"]) for t in hist if t["code"] == code]
            if line := _trend(code, times, now):
                outlook.append(line)
        outlook += _stock_lines(m, hist, Counter(t["code"] for t in hist))
        rows.append({
            "machine_id": m["machine_id"], "name": m["name"],
            "reports": len(hist) + len(new), "new_reports": len(new),
            "downtime_min": sum(t.get("downtime_min") or 0 for t in hist),
            "top_fault": top,
            "outlook": outlook or [{"level": "ok", "text": "ok"}],
        })
    return {"as_of": now.isoformat(), "window_days": 30, "label": "trend-based estimate", "machines": rows}
