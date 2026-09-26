"""Synthetic single-use grant target with a private target-local ledger oracle."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

LIBRARY = json.loads(Path(__file__).with_name("library-v1.json").read_text())
TOKENS = {token: actor for actor, token in LIBRARY["seed"]["accounts"].items()}
GRANTS = {key: dict(value) for key, value in LIBRARY["seed"]["grants"].items()}
BALANCES = dict(LIBRARY["seed"]["balances"])
EFFECTS: dict[str, dict] = {}
LOCK = threading.Lock()
REQUEST_ID = re.compile(r"[A-Za-z0-9]{1,64}\Z")


def redeem(request_id: str, actor: str, grant: str, *, unsafe: bool) -> tuple[int, dict]:
    """Single point of truth for both public redemption and the healthy control."""
    with LOCK:
        if request_id in EFFECTS:
            return 409, {"error": "duplicate request ID"}
        record = GRANTS.get(grant)
        if not record or record["owner"] != actor:
            return 404, {"error": "grant not found"}
        before = record["redemptions"]
        credited = before == 0 or unsafe
        if credited:
            record["redemptions"] += 1
            BALANCES[actor] += 1
        status = 200 if credited else 409
        effect = {"request_id": request_id, "actor": actor, "grant": grant,
                  "prior_redemptions": before, "after_redemptions": record["redemptions"],
                  "status": status, "duplicate_credited": before > 0 and credited,
                  "balance_after": BALANCES[actor], "control_ok": before == 0 and credited}
        EFFECTS[request_id] = effect
        return status, {"credited": credited} if credited else {"error": "already redeemed"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, value: dict) -> None:
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib callback
        path = urlsplit(self.path).path
        if path == "/health":
            self.send_json(200, {"seed": "nv08-grants-v1", "ready": True})
            return
        if self.server.server_port == 8081 and path.startswith("/oracle/"):
            request_id = path.removeprefix("/oracle/")
            with LOCK:
                event = EFFECTS.get(request_id)
            self.send_json(200 if event else 404, event or {"error": "unknown request"})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 - stdlib callback
        path = urlsplit(self.path).path
        request_id = self.headers.get("X-Request-ID", "")
        if not REQUEST_ID.fullmatch(request_id):
            self.send_json(400, {"error": "invalid request ID"})
            return
        if self.server.server_port == 8081 and path == "/control":
            grant = "ctl" + request_id
            with LOCK:
                GRANTS[grant] = {"owner": "A", "redemptions": 0}
            status, _ = redeem(request_id, "A", grant, unsafe=False)
            with LOCK:
                event = EFFECTS.get(request_id)
            self.send_json(status, event or {"error": "control failed"})
            return
        if self.server.server_port != 8080:
            self.send_json(404, {"error": "not found"})
            return
        match = re.fullmatch(r"/grants/([A-Za-z0-9-]{1,32})/(redeem|redeem-unsafe)", path)
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        actor = TOKENS.get(token)
        if not match or actor is None:
            self.send_json(404, {"error": "not found"})
            return
        status, result = redeem(request_id, actor, match.group(1),
                                unsafe=match.group(2) == "redeem-unsafe")
        self.send_json(status, result)

    def log_message(self, _format, *_args):
        return


def main():
    observer = ThreadingHTTPServer(("127.0.0.1", 8081), Handler)
    threading.Thread(target=observer.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
