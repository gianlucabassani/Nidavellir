"""Tiny deterministic stateful HTTP fixture for NV-02 live reset acceptance."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"seed": "baseline", "value": 0}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib callback name
        if self.path in ("/health", "/state"):
            self._send(200, STATE)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 - stdlib callback name
        if self.path != "/mutate":
            self._send(404, {"error": "not found"})
            return
        STATE["value"] += 1
        self._send(200, STATE)

    def log_message(self, _format, *_args):
        return


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
