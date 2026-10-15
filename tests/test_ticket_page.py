"""QR code -> mobile ticket page -> "Mark as fixed"; unknown machine receipt; one-line footer.

No API key and no network: the model calls are mocked. Runs in CI inside the Docker image.

Usage:  python -m unittest tests.test_ticket_page -v
"""
import base64
import json
import unittest

from fastapi.testclient import TestClient

from app import escpos, llm, main
from tests.test_fallback import ALL, FAULT, T01, FakeClient, _answer

UNKNOWN = {"machine_id": "UNKNOWN", "error_code": "", "cause": "", "part": "", "symptoms": ["dripping"],
           "evidence": "The paint line is dripping at the back left."}


class TicketPage(unittest.TestCase):
    def setUp(self):
        self._saved = (llm._call, llm._cache_put, llm._available, llm.client)
        llm.client = lambda: FakeClient(list(ALL))
        llm.discover_models(force=True)
        llm._cache_put = lambda *a, **k: None
        self.answer = FAULT
        llm._call = lambda *a, **k: _answer() if self.answer is FAULT else _json(self.answer)
        self.api = TestClient(main.app)

    def tearDown(self):
        llm._call, llm._cache_put, llm._available, llm.client = self._saved

    def ticket(self, text):
        events = [json.loads(line) for line in self.api.post("/api/ticket", data={"text": text}).text.splitlines()]
        return events[-1]

    def test_qr_page_marks_ticket_fixed(self):
        result = self.ticket(T01)
        tid = result["id"]
        self.assertTrue(result["ticket"]["qr_action_url"].endswith(f"/t/{tid}"))
        self.assertIn(b"Scan to close the ticket", base64.b64decode(result["escpos"]))

        page = self.api.get(f"/t/{tid}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Hydraulic press HP-400", page.text)
        self.assertIn("Mark as fixed", page.text)

        done = self.api.post(f"/t/{tid}/fixed")             # follows the 303 back to the page
        self.assertEqual(done.status_code, 200)
        self.assertIn("FIXED", done.text)
        self.assertNotIn("Mark as fixed", done.text)
        listed = next(t for t in self.api.get("/api/tickets").json() if t["id"] == tid)
        self.assertEqual(listed["status"], "fixed")
        self.assertEqual(self.api.get("/t/999999").status_code, 404)

    def test_unknown_machine_receipt(self):
        self.answer = UNKNOWN
        ev = self.ticket("The paint line is dripping at the back left.")
        self.assertEqual(ev["step"], "clarify")                # asks back, nothing printed
        printed = self.api.post(f"/api/drafts/{ev['draft']}/print").json()   # "Print anyway"
        text = " ".join(base64.b64decode(printed["escpos"]).decode("cp437").split())  # undo line wrapping
        self.assertIn("FIRST: PRESS E-STOP", text)
        self.assertIn("Report: 'The paint line is dripping at the back left.'", text)
        self.assertIn("Tell your shift lead the machine name and place.", text)
        self.assertNotIn("ask the technician", text)

    def test_footer_is_one_line(self):
        for model in ALL:
            for replay in (False, True):
                footer = f"Replay: {llm.base_name(model)} · AMD Token Factory" if replay else \
                    f"{llm.base_name(model)} · AMD Token Factory"
                self.assertLessEqual(len(footer), escpos.WIDTH, footer)


def _json(fault):
    from types import SimpleNamespace
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(fault)))])


if __name__ == "__main__":
    unittest.main(verbosity=2)
