"""Shared pieces for the test scripts: data, tool functions, API client, ticket check."""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("REPLAY_MODE", "off")  # benchmarks must hit the live API, never the replay cache
load_dotenv(ROOT / ".env")

from app.data import (CASES, HISTORY, INVENTORY, MANUAL, check_inventory, recurring_faults,  # noqa: E402,F401
                      search_manual, stock_fields, words)

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
