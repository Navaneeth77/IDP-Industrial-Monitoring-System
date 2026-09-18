"""
Tests for the Vercel serverless functions in api/.

Each file is loaded by its path (as Vercel does) and its "handler" class is
served on a free local port, then called over HTTP.
"""

import importlib.util
import json
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sample_scenarios import SAMPLE_SCENARIOS

API_DIR = Path(__file__).resolve().parent.parent / "api"


def load_handler(file_name):
    spec = importlib.util.spec_from_file_location(file_name[:-3], API_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.handler


def call(handler_class, path, body=None):
    """Serve the handler on a free port, send one request, return (status, JSON)."""
    class QuietHandler(handler_class):
        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}{path}", data=data,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    finally:
        httpd.shutdown()
        httpd.server_close()


class VercelApiTests(unittest.TestCase):

    def test_each_function_defines_a_request_handler(self):
        for file_name in ["config.py", "analyse.py"]:
            with self.subTest(file=file_name):
                self.assertTrue(issubclass(load_handler(file_name), BaseHTTPRequestHandler))

    def test_config_function(self):
        status, config = call(load_handler("config.py"), "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(list(config["presets"]), ["normal"])

    def test_analyse_function(self):
        body = {"inputs": SAMPLE_SCENARIOS["critical_gas"], "proposal_source": "mock_prohibited_shutdown"}
        status, result = call(load_handler("analyse.py"), "/api/analyse", body)
        self.assertEqual(status, 200)
        self.assertEqual(result["risk"]["category"], "CRITICAL")
        self.assertEqual(result["gate"]["decision"], "REJECTED")
        self.assertEqual(result["final_decision"]["action"], "RECOMMEND_EVACUATION_REVIEW")


if __name__ == "__main__":
    unittest.main()
