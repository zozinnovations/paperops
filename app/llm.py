"""Token Factory access: model discovery, fallback chain, validated JSON calls, replay cache.

Every successful model answer is cached in cache/ (git-ignored). Curated runs for the demo live in
replay/ (committed). REPLAY_MODE: off = live only, fallback (default) = live, replay if every model
fails or the live attempts take longer than LLM_BUDGET seconds, always = replay first (offline demo).
"""
import hashlib
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "15"))       # per model request
# Gemma alone (15/15 cases, 1.5-3.3 s after the Token Factory fix); the fallbacks are only a safety net.
# LLM_RACE=2 starts Gemma and MiMo together again (first valid answer wins).
RACE = int(os.getenv("LLM_RACE", "1"))                  # the first N models of the chain start at once
HEDGE_AFTER = float(os.getenv("LLM_HEDGE_AFTER", "5"))  # the next fallback starts if none of them has answered by then
HEDGE_STEP = float(os.getenv("LLM_HEDGE_STEP", "3"))    # ... and each further fallback this much later
BUDGET = float(os.getenv("LLM_BUDGET", "16"))         # all live attempts together, when a replay answer exists
MAX_TOTAL = float(os.getenv("LLM_MAX_TOTAL", "30"))    # all live attempts together, without a replay answer
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


def base_name(model_id):
    """"self-dploy/Gemma-4-31B-IT" -> "Gemma-4-31B-IT": the endpoint may prefix the provider."""
    return model_id.rsplit("/", 1)[-1]


def _api_id(model):
    """The exact id the endpoint lists for a configured model (with or without provider prefix)."""
    for listed in _available or []:
        if listed == model or base_name(listed) == base_name(model):
            return listed
    return model


def chain():
    """Configured models that the Token Factory lists (matched with or without a provider prefix such as
    "self-dploy/"), as plain names. Never blocks a request on discovery: while the model list is unknown,
    use the configured chain and retry discovery in the background."""
    wanted = [PRIMARY_MODEL, *FALLBACK_MODELS]
    if _available is None:
        threading.Thread(target=discover_models, daemon=True).start()
        return wanted
    listed = {base_name(m) for m in _available}
    return [m for m in wanted if base_name(m) in listed] or wanted


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
    path = CACHE_DIR / f"{_key(model, system, user)}.json"
    try:  # keep the fastest recorded run: replay shows its original timing
        if json.loads(path.read_text(encoding="utf-8"))["seconds"] <= entry["seconds"]:
            return
    except (OSError, ValueError, KeyError):
        pass
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")


def _call(model, system, user, max_tokens, timeout, retries):
    api = client().with_options(timeout=timeout, max_retries=retries)
    effort = _reasoning.get(base_name(model), "none")
    kwargs = dict(model=_api_id(model), messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                  response_format={"type": "json_object"}, temperature=0, max_tokens=max_tokens)
    try:
        return api.chat.completions.create(reasoning_effort=effort, **kwargs)
    except APIStatusError as e:
        # GLM-5.3-Flash rejects "none" (only low/medium/high) -> remember and retry once
        if effort == "none" and "reasoning_effort" in str(e):
            _reasoning[base_name(model)] = "low"
            return api.chat.completions.create(reasoning_effort="low", **kwargs)
        raise


_FENCE = re.compile(r"\A\s*```[A-Za-z0-9_-]*[ \t]*\r?\n(.*?)\r?\n?[ \t]*```\s*\Z", re.DOTALL)


def strip_code_fence(content):
    """Gemma often wraps valid JSON in one Markdown code fence (```json ... ```). Remove exactly one
    surrounding fence; everything else is parsed strictly (no other repair)."""
    m = _FENCE.match(content)
    return m.group(1) if m else content


def _attempt(model, system, user, validate, max_tokens, deadline):
    """One model request: (parsed, content, seconds); raises on API error, timeout or invalid output."""
    t0 = time.perf_counter()
    try:
        resp = _call(model, system, user, max_tokens, timeout=max(1.0, min(TIMEOUT, deadline - t0)), retries=0)
    except RateLimitError as e:
        # the limit is per team key, so another model would hit it too: honour Retry-After once
        wait = float(e.response.headers.get("retry-after") or 2)
        if wait > deadline - time.perf_counter() - 2:
            raise
        log.warning("429 on %s, retrying after %.1f s", model, wait)
        time.sleep(wait)
        resp = _call(model, system, user, max_tokens,
                     timeout=max(1.0, min(TIMEOUT, deadline - time.perf_counter())), retries=0)
    content = resp.choices[0].message.content or ""
    parsed = json.loads(strip_code_fence(content))
    validate(parsed)
    return parsed, content, time.perf_counter() - t0


def json_call(system, user, validate, max_tokens=400, models=None, replay_for=None):
    """Returns (parsed, info). validate(parsed) raises ValueError on bad output.

    Hedged fallback chain as a safety net: Gemma starts alone (RACE=1). If it has not answered after
    HEDGE_AFTER seconds, MiMo starts too (Gemma keeps running, the first valid answer wins), then one more
    fallback every HEDGE_STEP seconds - or at once when every running request has failed. Only when no model
    has answered within the budget does a recorded run from replay/ step in.

    replay_for: the canonical text of a sample recording, so a sample replays even when Whisper's
    transcript differs slightly from the stored one."""
    attempts = []
    hit = _cache_get(system, [user, replay_for]) if REPLAY_MODE != "off" else None
    if REPLAY_MODE == "always" and hit:
        return json.loads(strip_code_fence(hit["content"])), _replay_info(hit, attempts)

    queue = list(models or chain())
    start = time.perf_counter()
    deadline = start + (BUDGET if hit else MAX_TOTAL)
    pool = ThreadPoolExecutor(max_workers=len(queue))
    running = {}                      # future -> (model, started)
    next_start = start
    try:
        while time.perf_counter() < deadline and (queue or running):
            now = time.perf_counter()
            if queue and (now >= next_start or not running):
                model = queue.pop(0)
                running[pool.submit(_attempt, model, system, user, validate, max_tokens, deadline)] = (model, now)
                launched = len(running) + len(attempts)
                next_start = now + (0 if launched < RACE else HEDGE_AFTER if launched == RACE else HEDGE_STEP)
                continue
            wake = min(deadline, next_start) if queue else deadline
            done, _ = wait(running, timeout=max(0.05, wake - now), return_when=FIRST_COMPLETED)
            for fut in done:
                model, started = running.pop(fut)
                try:
                    parsed, content, seconds = fut.result()
                except Exception as e:  # API error, timeout, invalid JSON or schema
                    attempts.append({"model": model, "error": f"{type(e).__name__}: {str(e)[:200]}",
                                     "seconds": round(time.perf_counter() - started, 2)})
                    log.warning("model %s failed: %s", model, attempts[-1]["error"])
                    continue
                _cache_put(model, system, user, content, seconds)
                total = time.perf_counter() - start
                others = [f"{a['model']} failed" for a in attempts] + [f"{m} still running" for m, _ in running.values()]
                log.info("answered by %s in %.1f s (%.1f s after start)%s", model, seconds, total,
                         f" - {', '.join(others)}" if others else "")
                return parsed, {"model": model, "replay": False, "attempts": attempts, "seconds": total,
                                "still_running": [m for m, _ in running.values()]}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # slower requests finish in the background, ignored

    attempts += [{"model": m, "error": "no answer within the time budget", "seconds": round(time.perf_counter() - t, 2)}
                 for m, t in running.values()]
    attempts += [{"model": m, "error": "not tried: time budget used up", "seconds": 0} for m in queue]
    if hit:
        log.warning("no live model answered in %.0f s - answering from replay (%s)", time.perf_counter() - start,
                    hit["model"])
        return json.loads(strip_code_fence(hit["content"])), _replay_info(hit, attempts)
    raise AllModelsFailed("All models failed: " + "; ".join(f"{a['model']}: {a['error']}" for a in attempts))


def _replay_info(hit, attempts):
    """Info for a replayed answer: the recorded run's own model time, not how long we waited."""
    return {"model": hit["model"], "replay": True, "attempts": attempts, "recorded_seconds": hit.get("seconds"),
            "recorded_at": hit.get("recorded")}
