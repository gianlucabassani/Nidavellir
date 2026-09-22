"""Trusted fixed-destination HTTP relay over a Unix socket.

The untrusted runner has network_mode=none. This process alone joins the target
segment and accepts a bounded JSON protocol through a job-owned Unix socket.
"""
import argparse
import base64
import http.client
import json
import os
import socket
import ssl
import struct
import urllib.parse

MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 1024 * 1024
MAX_HEADERS = 32


def read_exact(conn, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = conn.recv(size - len(chunks))
        if not part:
            raise ValueError("truncated relay request")
        chunks.extend(part)
    return bytes(chunks)


def send(conn, payload):
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    conn.sendall(struct.pack("!I", len(encoded)) + encoded)


def handle(conn, args):
    size = struct.unpack("!I", read_exact(conn, 4))[0]
    if size > MAX_REQUEST:
        raise ValueError("relay request exceeds limit")
    req = json.loads(read_exact(conn, size))
    method = str(req.get("method", "GET")).upper()
    path = str(req.get("path", "/"))
    parsed = urllib.parse.urlsplit(path)
    if method == "CONNECT" or not method.isalpha() or len(method) > 32:
        raise ValueError("unsupported HTTP method")
    if not path.startswith("/") or path.startswith("//") or parsed.scheme or parsed.netloc:
        raise ValueError("path must be relative to the selected target")
    headers = req.get("headers") or {}
    if not isinstance(headers, dict) or len(headers) > MAX_HEADERS:
        raise ValueError("invalid request headers")
    clean_headers = {}
    for name, value in headers.items():
        name, value = str(name), str(value)
        if not name or any(ch in name + value for ch in "\r\n"):
            raise ValueError("invalid request header")
        if name.lower() in {"host", "connection", "proxy-authorization", "transfer-encoding"}:
            continue
        clean_headers[name] = value
    body = base64.b64decode(req.get("body_b64") or "", validate=True)
    if len(body) > MAX_REQUEST:
        raise ValueError("request body exceeds limit")
    if args.scheme == "https":
        upstream = http.client.HTTPSConnection(
            args.host, args.port, timeout=args.timeout,
            context=ssl._create_unverified_context(),  # nosec B323 - fixed lab target permits self-signed TLS
        )
    else:
        upstream = http.client.HTTPConnection(args.host, args.port, timeout=args.timeout)
    try:
        upstream.request(method, path, body=body or None, headers=clean_headers)
        response = upstream.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        truncated = len(raw) > MAX_RESPONSE
        raw = raw[:MAX_RESPONSE]
        send(conn, {
            "status": response.status,
            "reason": response.reason,
            "headers": dict(response.getheaders()),
            "body_b64": base64.b64encode(raw).decode(),
            "truncated": truncated,
        })
    finally:
        upstream.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--scheme", choices=("http", "https"), required=True)
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()
    try:
        os.unlink(args.socket)
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(args.socket)
    os.chmod(args.socket, 0o600)
    server.listen(8)
    while True:
        conn, _ = server.accept()
        with conn:
            try:
                handle(conn, args)
            except Exception as exc:
                send(conn, {"error": str(exc)[:500]})


if __name__ == "__main__":
    main()
