"""
Local dev server — serves the web/ frontend on port 8001.
Use alongside the FastAPI backend on port 8000.

For local testing:
  Terminal 1:  cd backend && python -m uvicorn main:app --port 8000 --reload
  Terminal 2:  python server.py
  Browser:     http://127.0.0.1:8001
"""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8001"))


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/health":
            payload = {
                "status": "ok",
                "service": "construction-scaler-local-server",
                "frontend": "connected",
                "backend": "use port 8000 for FastAPI",
            }
            data = json.dumps(payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()


def main() -> None:
    if not WEB_DIR.exists():
        raise SystemExit("web directory not found")

    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Frontend serving at http://{HOST}:{PORT}")
    print(f"Make sure FastAPI backend is running on http://{HOST}:8000")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
