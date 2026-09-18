"""
Vercel serverless function for GET /api/config.

Vercel runs this file on its own servers. It reuses the same request handler as
the local server (backend/server.py), so the logic exists only once.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from server import RequestHandler  # noqa: E402


class handler(RequestHandler):  # Vercel looks for a class named "handler"
    pass
