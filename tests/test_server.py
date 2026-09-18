"""
Tests of the web server and its JSON API, using a real server on a free port.
"""

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import server  # noqa: E402
from sample_scenarios import SAMPLE_SCENARIOS  # noqa: E402


class QuietHandler(server.RequestHandler):
    def log_message(self, *args):
        pass  # keep the test output readable


class ServerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)  # port 0 = any free port
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, body=None):
        """Send a GET (no body) or POST (with body). Returns (status, content)."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:  # an error response must be closed too
                return error.code, error.read()

    def test_frontend_files_are_served(self):
        for path in ["/", "/app.js", "/style.css"]:
            with self.subTest(path=path):
                status, content = self.request(path)
                self.assertEqual(status, 200)
                self.assertGreater(len(content), 0)

    def test_other_files_are_not_served(self):
        for path in ["/backend/server.py", "/../README.md", "/missing.html"]:
            with self.subTest(path=path):
                status, _ = self.request(path)
                self.assertEqual(status, 404)

    def test_config_offers_only_the_normal_preset(self):
        status, content = self.request("/api/config")
        config = json.loads(content)
        self.assertEqual(status, 200)
        self.assertEqual(list(config["presets"]), ["normal"])
        self.assertIn("available", config["gemma"])

    def test_analyse_returns_the_result(self):
        body = {"inputs": SAMPLE_SCENARIOS["compound"], "proposal_source": "mock_prohibited_permit"}
        status, content = self.request("/api/analyse", body)
        result = json.loads(content)
        self.assertEqual(status, 200)
        self.assertEqual(result["risk"]["category"], "HIGH")
        self.assertEqual(result["gate"]["decision"], "REJECTED")
        self.assertTrue(result["gate"]["plain_explanation"].startswith("Rejected because"))
        self.assertEqual(result["final_decision"]["action"], "ESCALATE_TO_SUPERVISOR")

    def test_history_is_no_longer_available(self):
        status, _ = self.request("/api/history")
        self.assertEqual(status, 404)

    def test_bad_requests_are_refused(self):
        bad_bodies = [
            {"proposal_source": "no_such_source"},
            {"proposal_source": "manual", "manual_proposal": 5},
            [1, 2, 3],
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                status, _ = self.request("/api/analyse", body)
                self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
