"""Shared pieces for the test scripts: data, tool functions, API client, ticket check."""
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
load_dotenv(ROOT / ".env")


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


MANUAL = load("machines_manual.json")["machines"]
INVENTORY = load("erp_inventory.json")["parts"]
HISTORY = load("ticket_history.json")["tickets"]
CASES = {c["id"]: c for c in load("test_transcripts.json")["cases"]}

PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "MiMo-V2.6-Flash")
FALLBACK_MODELS = [m for m in os.getenv("FALLBACK_MODELS", "Qwen3.8-27B,DeepSeek-V4-Flash").split(",") if m]
REQUIRED = ["machine", "priority", "cause", "part_needed", "location", "steps"]


def make_client():
    api_key = os.getenv("RADEON_API_KEY")
    if not api_key:
        sys.exit("RADEON_API_KEY is not set - add it to paperops/.env")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("RADEON_BASE_URL", "https://developer.amd.com.cn/radeon/api/v1"),
        timeout=60,
        max_retries=2,  # SDK retries 429/5xx with backoff and honours Retry-After
    )


# --- Lookups (used as agent tools and directly by the fast variant) --------

def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower().replace("-", "")))


def search_manual(query):
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
    hits = [t for t in HISTORY if t["machine_id"] == machine_id and t["code"] == code]
    return len(hits)


def stock_fields(inv):
    """location / stock / part / note from a check_inventory result, preferring an in-stock alternative."""
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


# --- Ticket check ----------------------------------------------------------

def check_ticket(ticket, expected):
    """Returns (ok, list of failure strings)."""
    fails = [f"missing {k}" for k in REQUIRED if not ticket.get(k)]
    text = json.dumps(ticket, ensure_ascii=False).lower()
    for k, v in expected.items():
        if k == "first_step_contains":
            if v.lower() not in (ticket.get("steps") or [""])[0].lower():
                fails.append(f"steps[0] lacks '{v}'")
        elif k == "cause_code":
            if ticket.get("error_code") != v:
                fails.append(f"error_code: expected {v}, got {ticket.get('error_code')}")
        elif k == "must_contain":
            if v.lower() not in text:
                fails.append(f"lacks '{v}'")
        elif k == "must_not_contain":
            if v.lower() in text:
                fails.append(f"contains '{v}'")
        elif k == "note_contains":
            if v.lower() not in str(ticket.get("note", "")).lower():
                fails.append(f"note lacks '{v}'")
        elif k == "recurring_flag":
            if bool(ticket.get("recurring_fault")) != v:
                fails.append(f"recurring_fault expected {v}")
        elif k == "must_not_invent_part":
            if str(ticket.get("part_needed", "")).lower() not in ("none", ""):
                fails.append(f"invented part '{ticket.get('part_needed')}'")
        elif str(v).lower() not in str(ticket.get(k, "")).lower():
            fails.append(f"{k}: expected '{v}', got '{ticket.get(k)}'")
    return not fails, fails
