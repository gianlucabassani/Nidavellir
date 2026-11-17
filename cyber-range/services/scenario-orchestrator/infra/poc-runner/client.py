"""PoC-side client installed in the immutable runner image as ``nidavellir``."""
import base64
import json
import socket
import struct
import time

_SOCKET = "/run/nidavellir/relay.sock"


def _read_exact(conn, size):
    data = bytearray()
    while len(data) < size:
        part = conn.recv(size - len(data))
        if not part:
            raise RuntimeError("target relay closed unexpectedly")
        data.extend(part)
    return bytes(data)


def request(path="/", method="GET", headers=None, body=None, timeout=15):
    """Send one HTTP request to the job's selected arena target only."""
    if isinstance(body, str):
        body = body.encode()
    payload = {
        "path": path, "method": method, "headers": headers or {},
        "body_b64": base64.b64encode(body or b"").decode(),
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        deadline = time.monotonic() + min(float(timeout), 5.0)
        while True:
            try:
                conn.connect(_SOCKET)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        conn.sendall(struct.pack("!I", len(encoded)) + encoded)
        size = struct.unpack("!I", _read_exact(conn, 4))[0]
        response = json.loads(_read_exact(conn, size))
    finally:
        conn.close()
    if response.get("error"):
        raise RuntimeError(response["error"])
    response["body"] = base64.b64decode(response.pop("body_b64"))
    return response
