"""
Tests for reaching Gemma through the Google AI Studio API (used when hosted, e.g. on Vercel).

No real Google service or key is used: a small local server imitates the API's
response format, and a made-up test key is set only for the duration of each test.
"""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import agent  # noqa: E402
from pipeline import run_analysis  # noqa: E402
from sample_scenarios import SAMPLE_SCENARIOS  # noqa: E402

FAKE_KEY = "test-key-not-real"


class FakeGoogleApi(BaseHTTPRequestHandler):
    """Answers like the Google API, with a reply wrapped in a ```json block."""
    received = []  # (path, api key header) of each request

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        json.loads(self.rfile.read(length))
        FakeGoogleApi.received.append((self.path, self.headers.get("x-goog-api-key")))
        reply = '```json\n{"action": "ESCALATE_TO_SUPERVISOR", "reason": "Gas is rising.", "confidence": 0.8}\n```'
        content = json.dumps({"candidates": [{"content": {"parts": [{"text": reply}]}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


class GoogleGemmaTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogleApi)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/v1beta/models"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_key_makes_gemma_available(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_KEY}):
            available, message = agent.gemma_status()
        self.assertTrue(available)
        self.assertIn("Google AI Studio", message)

    def test_without_key_or_ollama_gemma_is_unavailable(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
             mock.patch.object(agent, "OLLAMA_URL", "http://127.0.0.1:9"):
            available, message = agent.gemma_status()
        self.assertFalse(available)
        self.assertIn("GEMINI_API_KEY", message)

    def test_google_answer_goes_through_the_safety_check(self):
        FakeGoogleApi.received.clear()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_KEY}), \
             mock.patch.object(agent, "GOOGLE_API_BASE", self.base):
            result = run_analysis(SAMPLE_SCENARIOS["compound"], "gemma")

        path, key_header = FakeGoogleApi.received[0]
        self.assertEqual(path, f"/v1beta/models/{agent.GOOGLE_GEMMA_MODEL}:generateContent")
        self.assertEqual(key_header, FAKE_KEY)   # sent as a header...
        self.assertNotIn(FAKE_KEY, path)         # ...never in the URL

        self.assertIsNone(result["proposal"]["error"])
        self.assertFalse(result["proposal"]["raw_output"].startswith("```"))
        self.assertEqual(result["gate"]["decision"], "ACCEPTED")
        self.assertEqual(result["final_decision"]["action"], "ESCALATE_TO_SUPERVISOR")

    def test_code_fence_removal_only_removes_the_wrapper(self):
        self.assertEqual(agent.remove_code_fence('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(agent.remove_code_fence('{"a": 1}'), '{"a": 1}')
        self.assertEqual(agent.remove_code_fence("not json"), "not json")


if __name__ == "__main__":
    unittest.main()
