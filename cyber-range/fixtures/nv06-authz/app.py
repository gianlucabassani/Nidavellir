"""Resettable synthetic authorization target with a separate local effect log."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LIBRARY = json.loads(Path(__file__).with_name("library-v1.json").read_text())
TOKENS = {token: account for account, token in LIBRARY["seed"]["accounts"].items()}
OBJECTS = LIBRARY["seed"]["objects"]
EFFECTS: dict[str, dict] = {}
LOCK = threading.Lock()


def classify_request(actor, owner, request_id):
    """Distinguishable shape errors for one object read (discovery affordance).

    Each failing clause names its own cause — an absent header must never look
    like a wrong credential — while revealing nothing about the verdict
    (whether A may read B's object). Returns (status, error), or (None, None)
    when the shape is valid and the effect is decided downstream. The
    single-use request-ID rule is evidence integrity, not a challenge
    mechanic, and stays enforced where the effect is recorded.
    """
    if not actor:
        return 401, "unknown or missing credentials"
    if owner not in OBJECTS:
        return 404, "unknown object"
    if not request_id.isascii() or not request_id.isalnum() or len(request_id) > 64:
        return 400, "X-Request-ID must be 1-64 alphanumeric characters"
    return None, None


def index_body():
    """The `/` index: resource family names and nothing else. No owner
    names, no hint that reading another account's object discloses
    anything — the verdict stays undiscoverable from here."""
    return {"resources": ["objects", "protected"]}


def openapi_body():
    """Minimal `/openapi.json`: the two object families with `{owner}`
    path parameters. No owners, no headers, no response shapes — the
    header contract and the disclosure rule stay discoverable only
    through probing."""
    return {
        "openapi": "3.0.0",
        "paths": {
            "/objects/{owner}": {"get": {"responses": {"200": {"description": "object"}}}},
            "/protected/{owner}": {"get": {"responses": {"200": {"description": "object"}}}},
        },
    }


def route(path, port):
    """Map (path, port) to a route name. Pure dispatch seam over the exact
    historical behaviour: health and oracle first, then the 8080 object
    surface (index, schema, two-segment object reads), everything else
    not found."""
    if path == "/health":
        return "health"
    if port == 8081:
        return "oracle" if path.startswith("/oracle/") else "not_found"
    if port != 8080:
        return "not_found"
    if path == "/":
        return "index"
    if path == "/openapi.json":
        return "openapi"
    parts = path.strip("/").split("/")
    if len(parts) != 2 or parts[0] not in {"objects", "protected"}:
        return "not_found"
    return "object"


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
        name = route(path, self.server.server_port)
        if name == "health":
            self._send(200, {"seed": "nv06-v1", "ready": True})
            return
        if name == "index":
            self._send(200, index_body())
            return
        if name == "openapi":
            self._send(200, openapi_body())
            return
        if name == "oracle":
            request_id = path.removeprefix("/oracle/")
            with LOCK:
                item = EFFECTS.get(request_id)
            self._send(200 if item else 404, item or {"error": "unknown request"})
            return
        if name == "not_found":
            self._send(404, {"error": "not found"})
            return
        parts = path.strip("/").split("/")
        owner = parts[1]
        actor = TOKENS.get(self.headers.get("Authorization", "").removeprefix("Bearer "))
        request_id = self.headers.get("X-Request-ID", "")
        status, error = classify_request(actor, owner, request_id)
        if status is not None:
            self._send(status, {"error": error})
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
