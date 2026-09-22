"""Tiny deterministic stateful HTTP fixture for NV-02 live reset acceptance."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

STATE = {"seed": "baseline", "value": 0}
NODE_ID = os.getenv("NODE_ID", "target")


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib callback name
        parsed = urlsplit(self.path)
        if parsed.path in ("/health", "/state"):
            self._send(200, STATE)
        elif parsed.path == "/hit":
            STATE["value"] += 1
            self._send(200, STATE)
        elif parsed.path == "/redirect":
            target = (parse_qs(parsed.query).get("to") or ["/state"])[0]
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif parsed.path == "/page":
            subresource = (parse_qs(parsed.query).get("sub") or ["/state"])[0]
            body = (
                f"<html><head><title>NV03 {NODE_ID}</title></head>"
                f'<body><img src="{subresource}"><p>selected fixture</p></body></html>'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
