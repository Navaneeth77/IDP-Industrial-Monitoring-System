"""
Web server for the prototype, using only the Python standard library.

It serves the three frontend files and a small JSON API:

    GET  /api/config   the preset, field labels and whether Gemma is available
    POST /api/analyse  run the pipeline once and return the result

Start it from the project folder:   python3 backend/server.py
Then open http://127.0.0.1:8000 in a browser.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import agent
import scenario
from pipeline import run_analysis

HOST = "127.0.0.1"  # reachable from this computer only
PORT = int(os.environ.get("PORT", "8000"))
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_BODY_BYTES = 20_000

# The only files the server will send: URL path -> (file name, content type).
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def get_config():
    """Everything the page needs when it loads."""
    gemma_available, gemma_message = agent.gemma_status()
    return {
        "presets": scenario.PRESETS,
        "default_preset": scenario.DEFAULT_PRESET,
        "field_labels": scenario.FIELD_LABELS,
        "gemma": {"available": gemma_available, "message": gemma_message},
    }


class RequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/config":
            self.send_json(200, get_config())
        elif path in STATIC_FILES:
            file_name, content_type = STATIC_FILES[path]
            self.send_file(FRONTEND_DIR / file_name, content_type)
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/analyse":
            self.send_json(404, {"error": "Not found"})
            return

        body, error = self.read_json_body()
        if error:
            self.send_json(400, {"error": error})
            return

        # The page always uses Gemma. The other sources exist for the automated tests.
        source = body.get("proposal_source", "gemma")
        if source not in agent.PROPOSAL_SOURCES:
            self.send_json(400, {"error": f"Unknown proposal source: {source}"})
            return
        manual_text = body.get("manual_proposal", "")
        if not isinstance(manual_text, str):
            self.send_json(400, {"error": "manual_proposal must be text"})
            return

        try:
            result = run_analysis(body.get("inputs"), source, manual_text)
        except Exception as error:  # report unexpected errors instead of dropping the request
            self.send_json(500, {"error": f"Internal error: {error}"})
            return
        self.send_json(200, result)

    def read_json_body(self):
        """Return (body, None), or (None, error message) if the body is not usable."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "Invalid Content-Length header"
        if length <= 0 or length > MAX_BODY_BYTES:
            return None, "The request body is missing or too large"
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return None, "The request body is not valid JSON"
        if not isinstance(body, dict):
            return None, "The request body must be a JSON object"
        return body, None

    def send_json(self, status, data):
        content = json.dumps(data).encode("utf-8")
        self.send_bytes(status, content, "application/json; charset=utf-8")

    def send_file(self, file_path, content_type):
        self.send_bytes(200, file_path.read_bytes(), content_type)

    def send_bytes(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def main():
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    print(f"Zone 4 prototype running at http://{HOST}:{PORT}")
    print("Simulation only - no real equipment is connected. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
