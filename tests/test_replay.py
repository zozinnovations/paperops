"""No model answers: a recorded run stands in only for the same report, and the receipt always says so.

No API key and no network: the model list and the model calls are mocked. Runs in CI inside the Docker image.

Usage:  python -m unittest tests.test_replay -v
"""
import base64
import json
import unittest

from fastapi.testclient import TestClient

from app import escpos, llm, main, pipeline
from tests.test_fallback import ALL, T01, FakeClient, _503


class NoModelAnswers(unittest.TestCase):
    def setUp(self):
        self._saved = (llm._call, llm._cache_put, llm._available, llm.client, llm.REPLAY_MODE)
        llm.client = lambda: FakeClient(list(ALL))
        llm.discover_models(force=True)
        llm._cache_put = lambda *a, **k: None
        llm.REPLAY_MODE = "fallback"               # live first, replay only if no model answers

        def all_503(model, *a, **k):
            raise _503(model)
        llm._call = all_503
        llm._down.clear()

    def tearDown(self):
        llm._call, llm._cache_put, llm._available, llm.client, llm.REPLAY_MODE = self._saved
        llm._down.clear()

    def post(self, text):
        resp = TestClient(main.app).post("/api/ticket", data={"text": text})
        return [json.loads(line) for line in resp.text.splitlines() if line.strip()]

    def test_recorded_case_prints_marked_replay(self):
        result = self.post(T01)[-1]
        self.assertEqual(result["step"], "result", result)
        self.assertTrue(result["replay"])
        self.assertEqual(result["ticket"]["machine_id"], "HP-400")
        receipt = base64.b64decode(result["escpos"])
        self.assertIn(b"REPLAY - AI NOT REACHABLE", receipt)
        # footer, one line: names the recorded model
        self.assertIn(escpos._enc(f"Replay: {result['model']} · AMD Token Factory"), receipt)

    def test_new_report_prints_nothing(self):
        before = len(TestClient(main.app).get("/api/tickets").json())
        events = self.post("Robot five, wire feed stuck.")
        self.assertEqual(events[-1]["step"], "error", events[-1])
        self.assertEqual(events[-1]["message"], "The AI is not reachable right now. Please try again in a minute.")
        self.assertFalse(any(e["step"] in ("result", "clarify") for e in events))
        self.assertEqual(len(TestClient(main.app).get("/api/tickets").json()), before)

    def test_replay_never_for_another_machine(self):
        # a sample's recording (T01: HP-400, E-402) must not stand in for a report about another machine
        with self.assertRaises(llm.AllModelsFailed):
            list(pipeline.run("Robot five, wire feed stuck.", replay_for=T01))


if __name__ == "__main__":
    unittest.main(verbosity=2)
