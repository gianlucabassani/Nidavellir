"""Trusted single-destination TCP relay attached through the Docker stream.

The worker supplies a resolved arena-owned IP/port. This process has no DNS,
listener, proxy protocol, credentials or Docker access. Standard input and
output are the only data-plane connection to the worker.
"""
import os
import select
import socket
import sys
import time


def main():
    host, port = sys.argv[1], int(sys.argv[2])
    deadline = time.monotonic() + min(int(sys.argv[3]), 90)
    peer = socket.create_connection((host, port), timeout=5)
    peer.setblocking(False)
    total = 0
    try:
        while time.monotonic() < deadline and total < 2_097_152:
            readable, _, _ = select.select([0, peer], [], [], .25)
            if 0 in readable:
                chunk = os.read(0, 16384)
                if not chunk:
                    break
                peer.sendall(chunk)
                total += len(chunk)
            if peer in readable:
                chunk = peer.recv(16384)
                if not chunk:
                    break
                os.write(1, chunk)
                total += len(chunk)
    finally:
        peer.close()


if __name__ == "__main__":
    main()
