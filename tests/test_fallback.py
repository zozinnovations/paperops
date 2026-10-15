"""Gemma on the Token Factory answers 503 -> the fallback model still prints the ticket, fast.

No API key and no network: the model call is mocked. Runs in CI inside the Docker image.

Usage:  python -m unittest tests.test_fallback -v
"""
import json
import os
import time
import unittest
from types import SimpleNamespace

os.environ["REPLAY_MODE"] = "off"            # the live chain only, no recorded answers
os.environ.setdefault("RADEON_API_KEY", "test-key-not-used")

from fastapi.testclient import TestClient    # noqa: E402
from openai import InternalServerError       # noqa: E402

from app import llm, main                    # noqa: E402

GEMMA, MIMO = "Gemma-4-31B-IT", "MiMo-V2.6-Flash"
T01 = "Press three is stuck. Error E four oh two. The axis is running hot."
FAULT = {"machine_id": "HP-400", "error_code": "E-402", "cause": "Lubrication failure on main axis",
         "part": "Lubricating oil ISO VG 46", "symptoms": ["stuck", "axis running hot"],
         "evidence": "Press three is stuck. Error E four oh two. The axis is running hot."}


def _503(model):
    """The SDK's exception for an HTTP 503, without a real HTTP response object."""
    e = InternalServerError.__new__(InternalServerError)
    Exception.__init__(e, f"Error code: 503 - {model}: Service Unavailable")
    e.status_code, e.message, e.body = 503, "Service Unavailable", None
    return e


def _answer():
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(FAULT)))])


class GemmaUnavailable(unittest.TestCase):
    def setUp(self):
        self._saved = (llm._call, llm._cache_put, llm._available)
        llm._available = [f"self-dploy/{GEMMA}", MIMO, "GLM-5.3-Flash", "DeepSeek-V4.1-Flash"]
        llm._cache_put = lambda *a, **k: None   # never store mocked answers in cache/
        llm._down.clear()
        llm.LAST.update(model=None, replay=False)
        self.calls = []

    def tearDown(self):
        llm._call, llm._cache_put, llm._available = self._saved
        llm._down.clear()

    def mock(self, gemma):
        def fake_call(model, system, user, max_tokens, timeout, retries):
            self.calls.append((llm.base_name(model), time.perf_counter()))
            if llm.base_name(model) == GEMMA:
                return gemma(model)
            time.sleep(0.8)                       # a normal fallback answer
            return _answer()
        llm._call = fake_call

    def ticket(self):
        t0 = time.perf_counter()
        resp = TestClient(main.app).post("/api/ticket", data={"text": T01})
        events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        return events, time.perf_counter() - t0

    def test_503_prints_with_fallback_within_5_s(self):
        def gemma(model):
            raise _503(model)
        self.mock(gemma)
        events, seconds = self.ticket()
        result = events[-1]
        self.assertEqual(result["step"], "result", events[-3:])
        self.assertEqual(result["model"], MIMO)
        self.assertFalse(result["replay"])
        self.assertEqual(result["ticket"]["machine_id"], "HP-400")
        self.assertLess(seconds, 5, "the fallback must not wait for LLM_HEDGE_AFTER after a 503")
        # MiMo started right after the 503, not 5 s later
        started = dict(self.calls)
        self.assertLess(started[MIMO] - started[GEMMA], 1.0)
        # header badge: the model that answered, not Gemma
        status = TestClient(main.app).get("/api/status").json()
        self.assertEqual(status["last_model"], MIMO)
        self.assertTrue(status["primary_down"])

    def test_gemma_down_and_hanging_does_not_delay_fallback(self):
        # Gemma failed with 503 a moment ago; now it hangs instead of failing fast
        llm._down[GEMMA] = time.monotonic()

        def gemma(model):
            time.sleep(8)
            raise _503(model)
        self.mock(gemma)
        events, seconds = self.ticket()
        self.assertEqual(events[-1]["step"], "result")
        self.assertEqual(events[-1]["model"], MIMO)
        self.assertLess(seconds, 3, "while Gemma is down, the fallback starts together with it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
