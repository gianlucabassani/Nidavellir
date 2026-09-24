"""Resettable synthetic authorization target with a separate local effect log."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TOKENS = {"token-a-public": "A", "token-b-operator": "B"}
OBJECTS = {"A": "private-A", "B": "private-B"}
EFFECTS: dict[str, dict] = {}
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, value: dict) -> None:
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib callback
        path = urlsplit(self.path).path
        if path == "/health":
            self._send(200, {"seed": "nv06-v1", "ready": True})
            return
        if path.startswith("/oracle/") and self.server.server_port == 8081:
            request_id = path.removeprefix("/oracle/")
            with LOCK:
                item = EFFECTS.get(request_id)
            self._send(200 if item else 404, item or {"error": "unknown request"})
            return
        if self.server.server_port != 8080:
            self._send(404, {"error": "not found"})
            return
        parts = path.strip("/").split("/")
        if len(parts) != 2 or parts[0] not in {"objects", "protected"}:
            self._send(404, {"error": "not found"})
            return
        owner = parts[1]
        actor = TOKENS.get(self.headers.get("Authorization", "").removeprefix("Bearer "))
        request_id = self.headers.get("X-Request-ID", "")
        if not actor or owner not in OBJECTS or not request_id.isascii() or not request_id.isalnum() or len(request_id) > 64:
            self._send(400, {"error": "invalid request"})
            return
        disclosed = actor == owner or parts[0] == "objects"
        result = {
            "request_id": request_id, "actor": actor, "owner": owner,
            "status": 200 if disclosed else 403,
            "unauthorized_disclosure": disclosed and actor != owner,
            "control_ok": disclosed and actor == owner,
        }
        with LOCK:
            # An ID is single use, so a later control cannot overwrite evidence.
            if request_id in EFFECTS:
                self._send(409, {"error": "duplicate request ID"})
                return
            EFFECTS[request_id] = result
        self._send(result["status"], {"object": OBJECTS[owner]} if disclosed else {"error": "denied"})

    def log_message(self, _format, *_args):
        return


def main():
    observer = ThreadingHTTPServer(("127.0.0.1", 8081), Handler)
    threading.Thread(target=observer.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
