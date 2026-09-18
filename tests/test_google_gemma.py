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
    """Imitates the Google API: lists models, answers 404 for unknown models, and
    replies with a "thought" part plus an answer wrapped in a ```json block."""
    available_models = ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]
    received = []  # (method, path, api key header, request body) of each request

    def do_GET(self):
        FakeGoogleApi.received.append(("GET", self.path, self.headers.get("x-goog-api-key"), None))
        models = [{"name": "models/gemini-x", "supportedGenerationMethods": ["generateContent"]}]
        models += [{"name": f"models/{name}", "supportedGenerationMethods": ["generateContent"]}
                   for name in FakeGoogleApi.available_models]
        self.reply(200, {"models": models})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeGoogleApi.received.append(("POST", self.path, self.headers.get("x-goog-api-key"), body))
        model = self.path.split("/")[-1].split(":")[0]
        if model not in FakeGoogleApi.available_models:
            self.reply(404, {"error": {"message": "model not found"}})
            return
        answer = '```json\n{"action": "ESCALATE_TO_SUPERVISOR", "reason": "Gas is rising.", "confidence": 0.8}\n```'
        parts = [{"text": "Let me think about the risk first...", "thought": True}, {"text": answer}]
        self.reply(200, {"candidates": [{"content": {"parts": parts}}]})

    def reply(self, status, data):
        content = json.dumps(data).encode("utf-8")
        self.send_response(status)
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

    def run_with_fake_google(self, model):
        FakeGoogleApi.received.clear()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_KEY}), \
             mock.patch.object(agent, "GOOGLE_API_BASE", self.base), \
             mock.patch.object(agent, "google_model_in_use", model):
            result = run_analysis(SAMPLE_SCENARIOS["compound"], "gemma")
            model_after = agent.google_model_in_use
        return result, model_after

    def test_google_answer_goes_through_the_safety_check(self):
        result, _ = self.run_with_fake_google("gemma-4-26b-a4b-it")

        method, path, key_header, body = FakeGoogleApi.received[0]
        self.assertEqual(path, "/v1beta/models/gemma-4-26b-a4b-it:generateContent")
        self.assertEqual(key_header, FAKE_KEY)   # sent as a header...
        self.assertNotIn(FAKE_KEY, path)         # ...never in the URL
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingLevel": "minimal"})

        self.assertIsNone(result["proposal"]["error"])
        self.assertNotIn("think", result["proposal"]["raw_output"])   # thought part ignored
        self.assertFalse(result["proposal"]["raw_output"].startswith("```"))
        self.assertEqual(result["gate"]["decision"], "ACCEPTED")
        self.assertEqual(result["final_decision"]["action"], "ESCALATE_TO_SUPERVISOR")

    def test_missing_model_is_replaced_by_an_available_gemma_model(self):
        result, model_after = self.run_with_fake_google("gemma-3-27b-it")  # no longer offered
        requests = [(method, path) for method, path, _, _ in FakeGoogleApi.received]
        self.assertEqual(requests[0], ("POST", "/v1beta/models/gemma-3-27b-it:generateContent"))
        self.assertEqual(requests[1][0], "GET")  # asks which models exist
        self.assertEqual(requests[2], ("POST", "/v1beta/models/gemma-4-31b-it:generateContent"))
        self.assertEqual(model_after, "gemma-4-31b-it")
        self.assertIsNone(result["proposal"]["error"])
        self.assertEqual(result["gate"]["decision"], "ACCEPTED")

    def test_no_gemma_model_available_is_reported_safely(self):
        with mock.patch.object(FakeGoogleApi, "available_models", []):
            result, _ = self.run_with_fake_google("gemma-3-27b-it")
        self.assertIn("no other Gemma model", result["proposal"]["error"])
        self.assertEqual(result["gate"]["decision"], "REJECTED")
        self.assertEqual(result["final_decision"]["action"], "ESCALATE_TO_SUPERVISOR")

    def test_code_fence_removal_only_removes_the_wrapper(self):
        self.assertEqual(agent.remove_code_fence('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(agent.remove_code_fence('{"a": 1}'), '{"a": 1}')
        self.assertEqual(agent.remove_code_fence("not json"), "not json")


if __name__ == "__main__":
    unittest.main()
