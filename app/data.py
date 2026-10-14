"""Demo data (data/*.json) and the lookups that run in code: manual, inventory, recurring faults."""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
load_dotenv(ROOT / ".env")


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


MANUAL = load("machines_manual.json")["machines"]
INVENTORY = load("erp_inventory.json")["parts"]
HISTORY = load("ticket_history.json")["tickets"]
CASES = {c["id"]: c for c in load("test_transcripts.json")["cases"]}

WINDOW_DAYS = 30


def demo_now():
    """The demo clock. All "last 30 days" / "3x in 12 days" logic counts from here, never from today's real
    date - otherwise the history would age out while the judges test the app. DEMO_NOW (ISO date or datetime)
    overrides it; by default it is the time of the latest history entry."""
    fixed = os.getenv("DEMO_NOW", "").strip()
    if fixed:
        now = datetime.fromisoformat(fixed)
        return now if now.tzinfo else now.replace(tzinfo=datetime.fromisoformat(HISTORY[-1]["ts"]).tzinfo)
    return max(datetime.fromisoformat(t["ts"]) for t in HISTORY)


def recent_history(days=WINDOW_DAYS):
    """History tickets within the window that ends at the demo clock."""
    now = demo_now()
    return [t for t in HISTORY if now - timedelta(days=days) <= datetime.fromisoformat(t["ts"]) <= now]


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower().replace("-", "")))


def search_manual(query):
    """Free-text manual search (tool for the agent variant)."""
    q = query.lower()
    qw = words(query)
    best, best_score = None, 0
    for m in MANUAL:
        names = [m["machine_id"], m["name"], *m["aliases"]]
        score = sum(3 for n in names if n.lower() in q)
        score += sum(1 for n in names if words(n) & qw)
        codes = []
        for e in m["error_codes"]:
            es = 5 if e["code"].lower() in q or e["code"].lower().replace("-", "") in q.replace("-", "") else 0
            es += len(words(" ".join([e["title"], *e["symptoms"]])) & qw)
            if es:
                codes.append((es, e))
            score += es
        if score > best_score:
            best, best_score = (m, codes), score
    if not best:
        return {"found": False, "message": "No machine matches this query. Do not invent machines or parts."}
    m, codes = best
    codes = [e for _, e in sorted(codes, key=lambda x: -x[0])[:2]] or m["error_codes"]
    return {
        "found": True,
        "machine_id": m["machine_id"],
        "name": m["name"],
        "location": m["location"],
        "lockout_procedure": m["lockout_procedure"],
        "error_codes": codes,
    }


def check_inventory(part_name):
    q = part_name.lower()
    exact = [p for p in INVENTORY if p["name"].lower() == q]
    for p in exact + INVENTORY:
        names = [p["name"], *p["aliases"]]
        if any(n.lower() in q or q in n.lower() for n in names):
            result = dict(p, found=True)
            if p["stock"] == 0 and p.get("alternative_sku"):
                result["alternative"] = next((a for a in INVENTORY if a["sku"] == p["alternative_sku"]), None)
            return result
    return {"found": False, "message": f"No part matching '{part_name}' in inventory."}


def recurring_faults(machine_id, code):
    """(count, calendar days from first to last occurrence, inclusive) in the 30 days up to the demo clock."""
    hits = sorted(t["ts"] for t in recent_history() if t["machine_id"] == machine_id and t["code"] == code)
    if not hits:
        return 0, 0
    span = (datetime.fromisoformat(hits[-1]).date() - datetime.fromisoformat(hits[0]).date()).days + 1
    return len(hits), span


def stock_fields(inv):
    """part / location / stock / note from a check_inventory result, preferring an in-stock alternative."""
    if not inv.get("found"):
        return {}
    part, note = inv, None
    reorder = inv.get("reorder") or {}
    reorder_txt = f"reorder {reorder.get('status', 'unknown')}" + (f", ETA {reorder['eta']}" if reorder.get("eta") else "")
    if inv["stock"] == 0 and inv.get("alternative"):
        part = inv["alternative"]
        note = f"Original out of stock: {inv['name']} ({reorder_txt}). Use approved alternative {part['name']}."
    elif inv["stock"] == 0:
        note = f"Out of stock, no alternative ({reorder_txt}) - escalate to shift supervisor and reorder now."
    out = {
        "part_needed": part["name"],
        "location": part["location"],
        "stock": f"{part['stock']} {part['unit']} available",
    }
    if note:
        out["note"] = note
    return out
