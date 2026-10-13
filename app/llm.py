"""Token Factory access: model discovery, fallback chain, validated JSON calls, replay cache.

Every successful model answer is cached in cache/ (git-ignored). Curated runs for the demo live in
replay/ (committed). REPLAY_MODE: off = live only, fallback (default) = live, replay if every model
fails, always = replay first (offline demo).
"""
import hashlib
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI

from .data import ROOT

load_dotenv(ROOT / ".env")
log = logging.getLogger("paperops.llm")

BASE_URL = os.getenv("RADEON_BASE_URL", "https://developer.amd.com.cn/radeon/api/v1")
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "MiMo-V2.6-Flash")
FALLBACK_MODELS = [m.strip() for m in os.getenv("FALLBACK_MODELS", "Qwen3.8-27B,DeepSeek-V4-Flash").split(",") if m.strip()]
REPLAY_MODE = os.getenv("REPLAY_MODE", "fallback")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
CACHE_DIR, REPLAY_DIR = ROOT / "cache", ROOT / "replay"

_client = None
_available = None          # model ids from GET /v1/models
_reasoning = {}            # model -> reasoning_effort that model accepts


def client():
    global _client
    if _client is None:
        key = os.getenv("RADEON_API_KEY")
        if not key:
            raise RuntimeError("RADEON_API_KEY is not set")
        # 1 SDK retry (429/5xx, honours Retry-After), then the next model in the chain takes over
        _client = OpenAI(api_key=key, base_url=BASE_URL, timeout=TIMEOUT, max_retries=1)
    return _client


def discover_models():
    """GET /v1/models once at startup; never rely on one hard-coded model."""
    global _available
    try:
        _available = [m.id for m in client().models.list().data]
    except Exception as e:  # keep running (replay mode) even if the API is down
        log.warning("model discovery failed: %s", e)
        _available = []
    return _available


def chain():
    wanted = [PRIMARY_MODEL, *FALLBACK_MODELS]
    if _available is None:
        discover_models()
    return [m for m in wanted if m in _available] or wanted


def _key(model, system, user):
    return hashlib.sha256(f"{model}\n{system}\n{user}".encode()).hexdigest()[:24]


def _cache_get(system, user):
    for d in (REPLAY_DIR, CACHE_DIR):
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            entry = json.loads(f.read_text(encoding="utf-8"))
            if entry.get("user") == user and entry.get("system_sha") == hashlib.sha256(system.encode()).hexdigest()[:16]:
                return entry
    return None


def _cache_put(model, system, user, content, seconds):
    CACHE_DIR.mkdir(exist_ok=True)
    entry = {"model": model, "user": user, "system_sha": hashlib.sha256(system.encode()).hexdigest()[:16],
             "content": content, "seconds": round(seconds, 3), "recorded": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (CACHE_DIR / f"{_key(model, system, user)}.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False),
                                                                encoding="utf-8")


def _call(model, system, user, max_tokens):
    effort = _reasoning.get(model, "none")
    kwargs = dict(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                  response_format={"type": "json_object"}, temperature=0, max_tokens=max_tokens)
    try:
        return client().chat.completions.create(reasoning_effort=effort, **kwargs)
    except APIStatusError as e:
        # GLM-5.3-Flash rejects "none" (only low/medium/high) -> remember and retry once
        if effort == "none" and "reasoning_effort" in str(e):
            _reasoning[model] = "low"
            return client().chat.completions.create(reasoning_effort="low", **kwargs)
        raise


def json_call(system, user, validate, max_tokens=400, models=None):
    """Returns (parsed, info). Tries each model in the chain; validate(parsed) raises ValueError on bad output."""
    attempts = []
    if REPLAY_MODE == "always" and (hit := _cache_get(system, user)):
        return json.loads(hit["content"]), {"model": hit["model"], "replay": True, "attempts": attempts}

    for model in models or chain():
        t0 = time.perf_counter()
        try:
            resp = _call(model, system, user, max_tokens)
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

    if REPLAY_MODE != "off" and (hit := _cache_get(system, user)):
        return json.loads(hit["content"]), {"model": hit["model"], "replay": True, "attempts": attempts}
    raise RuntimeError("All models failed: " + "; ".join(f"{a['model']}: {a['error']}" for a in attempts))
