#!/usr/bin/env python3
"""Loopback-only client for an authenticated, fixed-destination TCP lease.

Requires the pinned `websockets` package. The API key is read from the
environment and sent only in a WebSocket header, never in the URL.
"""
import argparse
import os
import socket
import threading
from urllib.parse import urlsplit

from websockets.sync.client import connect


def _serve(client, uri, key):
    try:
        with client, connect(uri, additional_headers={"X-API-Key": key},
                             max_size=16384, open_timeout=10) as tunnel:
            done = threading.Event()

            def upload():
                try:
                    while not done.is_set():
                        data = client.recv(16384)
                        if not data:
                            break
                        tunnel.send(data)
                except (OSError, RuntimeError):
                    pass
                finally:
                    done.set()
                    tunnel.close()

            sender = threading.Thread(target=upload, daemon=True)
            sender.start()
            try:
                for message in tunnel:
                    if isinstance(message, bytes):
                        client.sendall(message)
            finally:
                done.set()
    except (OSError, RuntimeError) as exc:
        print(f"forward connection closed: {exc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", required=True)
    parser.add_argument("--forward", required=True)
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    key = os.getenv("NIDAVELLIR_API_KEY")
    if not key:
        parser.error("set NIDAVELLIR_API_KEY in the environment")
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be in 1..65535")
    parsed = urlsplit(args.api_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
        parser.error("--api-url must be an HTTP(S) origin without credentials")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    uri = (f"{scheme}://{parsed.netloc}/arenas/{args.arena}/forwards/"
           f"{args.forward}/connect")
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", args.listen_port))
        listener.listen(1)
        print(f"listening on 127.0.0.1:{args.listen_port} for {args.forward}")
        while True:
            client, _ = listener.accept()
            _serve(client, uri, key)


if __name__ == "__main__":
    main()
