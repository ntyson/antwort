"""Tiny HTTP health endpoint so Railway/web platforms keep the worker alive."""

from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/health", "/healthz"):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return  # silence access logs


def start_health_server() -> HTTPServer | None:
    """Bind to Railway's $PORT if set. Returns server or None."""
    port_raw = os.environ.get("PORT")
    if not port_raw:
        return None
    port = int(port_raw)
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, name="health", daemon=True)
    thread.start()
    log.info("Health server listening on :%s", port)
    return server
