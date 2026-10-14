"""Token Factory access: model discovery, fallback chain, validated JSON calls, replay cache.

Every successful model answer is cached in cache/ (git-ignored). Curated runs for the demo live in
replay/ (committed). REPLAY_MODE: off = live only, fallback (default) = live, replay if every model
fails or the live attempts take longer than LLM_BUDGET seconds, always = replay first (offline demo).
"""
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI, RateLimitError

from .data import ROOT

load_dotenv(ROOT / ".env")
log = logging.getLogger("paperops.llm")

BASE_URL = os.getenv("RADEON_BASE_URL", "https://developer.amd.com.cn/radeon/api/v1")
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "Gemma-4-31B-IT")  # Gemma 4 on AMD GPUs
FALLBACK_MODELS = [m.strip() for m in os.getenv("FALLBACK_MODELS", "MiMo-V2.6-Flash,GLM-5.3-Flash,DeepSeek-V4.1-Flash").split(",") if m.strip()]
REPLAY_MODE = os.getenv("REPLAY_MODE", "fallback")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "15"))     # per model attempt; the next model in the chain is the retry
BUDGET = float(os.getenv("LLM_BUDGET", "12"))       # all live attempts together, when a replay answer exists
MAX_TOTAL = float(os.getenv("LLM_MAX_TOTAL", "30"))  # all live attempts together, without a replay answer
CACHE_DIR, REPLAY_DIR = ROOT / "cache", ROOT / "replay"

class AllModelsFailed(RuntimeError):
    pass


_client = None
_available = None          # model ids from GET /v1/models
# model -> reasoning_effort it accepts. Default "none" = thinking off (Gemma: reasoning is only on/off;
# MiMo/DeepSeek accept "none"); GLM-5.3-Flash only takes low/medium/high and is switched on first failure.
_reasoning = {"GLM-5.3-Flash": "low"}


def client():
    global _client
    if _client is None:
        key = os.getenv("RADEON_API_KEY")
        if not key:
            raise RuntimeError("RADEON_API_KEY is not set")
        # timeout and retries are set per call in _call()
        _client = OpenAI(api_key=key, base_url=BASE_URL, timeout=TIMEOUT, max_retries=1)
    return _client


_last_discovery = [0.0]


def discover_models():
    """GET /v1/models at startup (retried at most every 30 s while it fails); never rely on one hard-coded model."""
    global _available
    if _available is None and time.time() - _last_discovery[0] < 30:
        return []
    _last_discovery[0] = time.time()
    try:
        _available = [m.id for m in client().with_options(timeout=5, max_retries=0).models.list().data]
    except Exception as e:  # keep running (replay mode) even if the API is down; retry on the next request
        log.warning("model discovery failed: %s", e)
        _available = None
        return []
    return _available


def chain():
    """Configured models that the Token Factory lists. Never blocks a request on discovery: while the
    model list is unknown, use the configured chain and retry discovery in the background."""
    wanted = [PRIMARY_MODEL, *FALLBACK_MODELS]
    if _available is None:
        threading.Thread(target=discover_models, daemon=True).start()
        return wanted
    return [m for m in wanted if m in _available] or wanted


def _key(model, system, user):
    return hashlib.sha256(f"{model}\n{system}\n{user}".encode()).hexdigest()[:24]


def _cache_get(system, users):
    sha = hashlib.sha256(system.encode()).hexdigest()[:16]
    for d in (REPLAY_DIR, CACHE_DIR):
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            entry = json.loads(f.read_text(encoding="utf-8"))
            if entry.get("user") in users and entry.get("system_sha") == sha:
                return entry
    return None


def _cache_put(model, system, user, content, seconds):
    CACHE_DIR.mkdir(exist_ok=True)
    entry = {"model": model, "user": user, "system_sha": hashlib.sha256(system.encode()).hexdigest()[:16],
             "content": content, "seconds": round(seconds, 3), "recorded": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (CACHE_DIR / f"{_key(model, system, user)}.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False),
                                                                encoding="utf-8")


def _call(model, system, user, max_tokens, timeout, retries):
    api = client().with_options(timeout=timeout, max_retries=retries)
    effort = _reasoning.get(model, "none")
    kwargs = dict(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                  response_format={"type": "json_object"}, temperature=0, max_tokens=max_tokens)
    try:
        return api.chat.completions.create(reasoning_effort=effort, **kwargs)
    except APIStatusError as e:
        # GLM-5.3-Flash rejects "none" (only low/medium/high) -> remember and retry once
        if effort == "none" and "reasoning_effort" in str(e):
            _reasoning[model] = "low"
            return api.chat.completions.create(reasoning_effort="low", **kwargs)
        raise


def json_call(system, user, validate, max_tokens=400, models=None, replay_for=None):
    """Returns (parsed, info). Tries each model in the chain; validate(parsed) raises ValueError on bad output.

    replay_for: the canonical text of a sample recording, so a sample replays even when Whisper's
    transcript differs slightly from the stored one."""
    attempts = []
    hit = _cache_get(system, [user, replay_for]) if REPLAY_MODE != "off" else None
    if REPLAY_MODE == "always" and hit:
        return json.loads(hit["content"]), {"model": hit["model"], "replay": True, "attempts": attempts}

    # with a replay answer in reserve, a slow API must not keep judges waiting: cap all attempts at BUDGET
    deadline = time.perf_counter() + (BUDGET if hit else MAX_TOTAL)
    for model in models or chain():
        remaining = deadline - time.perf_counter()
        if remaining < 1:
            attempts.append({"model": model, "error": "skipped: time budget used up", "seconds": 0})
            break
        t0 = time.perf_counter()
        try:
            try:
                resp = _call(model, system, user, max_tokens, timeout=min(TIMEOUT, remaining), retries=0)
            except RateLimitError as e:
                # the limit is per team key, so the next model would hit it too: honour Retry-After once
                wait = float(e.response.headers.get("retry-after") or 2)
                if wait > deadline - time.perf_counter() - 2:
                    raise
                log.warning("429 on %s, retrying after %.1f s", model, wait)
                time.sleep(wait)
                resp = _call(model, system, user, max_tokens,
                             timeout=max(1.0, min(TIMEOUT, deadline - time.perf_counter())), retries=0)
            content = resp.choices[0].message.content or ""
            parsed = json.loads(content)
            validate(parsed)
        except Exception as e:  # API error, timeout, invalid JSON or schema -> next model
            attempts.append({"model": model, "error": f"{type(e).__name__}: {str(e)[:200]}",
                             "seconds": round(time.perf_counter() - t0, 2)})
            log.warning("model %s failed: %s", model, attempts[-1]["error"])
            continue
        dt = time.perf_counter() - t0
        _cache_put(model, system, user, content, dt)
        return parsed, {"model": model, "replay": False, "attempts": attempts, "seconds": dt}

    if hit:
        log.warning("live models failed or too slow - answering from replay (%s)", hit["model"])
        return json.loads(hit["content"]), {"model": hit["model"], "replay": True, "attempts": attempts}
    raise AllModelsFailed("All models failed: " + "; ".join(f"{a['model']}: {a['error']}" for a in attempts))
