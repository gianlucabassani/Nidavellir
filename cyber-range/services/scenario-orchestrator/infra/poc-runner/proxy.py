"""Fixed-destination browser proxy used by the trusted helper boundary."""
import argparse
import http.client
import select
import socket
import socketserver
import ssl
import urllib.parse

MAX_BODY = 1024 * 1024
MAX_HEADERS = 64


class Proxy(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(8193).decode("latin-1").rstrip("\r\n")
        parts = line.split(" ", 2)
        if len(parts) != 3:
            return
        method, raw_target, version = parts
        headers = {}
        for _ in range(MAX_HEADERS + 1):
            line = self.rfile.readline(65537)
            if line in (b"\r\n", b"\n", b""):
                break
            if len(line) > 65536 or len(headers) >= MAX_HEADERS:
                self.send_error(431)
                return
            name, separator, value = line.decode("latin-1").partition(":")
            if not separator:
                self.send_error(400)
                return
            headers[name.strip()] = value.strip()
        if method.upper() == "CONNECT":
            self._connect(raw_target)
            return
        parsed = urllib.parse.urlsplit(raw_target)
        if parsed.scheme not in ("http", "https") or not self._allowed(parsed.hostname, parsed.port):
            self.send_error(403)
            return
        length = int(headers.get("Content-Length", "0") or 0)
        if length < 0 or length > MAX_BODY:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length else None
        clean = {
            key: value for key, value in headers.items()
            if key.lower() not in {"host", "connection", "proxy-connection", "transfer-encoding"}
        }
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        kwargs = {"timeout": self.server.timeout}
        if parsed.scheme == "https":
            kwargs["context"] = ssl._create_unverified_context()  # nosec B323 - fixed lab target permits self-signed TLS
        upstream = connection_cls(self.server.target_host, self.server.target_port, **kwargs)
        try:
            upstream.request(method, path, body=body, headers=clean)
            response = upstream.getresponse()
            payload = response.read(MAX_BODY + 1)[:MAX_BODY]
            self.wfile.write(f"{version} {response.status} {response.reason}\r\n".encode("latin-1"))
            for name, value in response.getheaders()[:MAX_HEADERS]:
                if name.lower() not in {"connection", "transfer-encoding", "content-length"}:
                    self.wfile.write(f"{name}: {value}\r\n".encode("latin-1", "replace"))
            self.wfile.write(f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode())
            self.wfile.write(payload)
        finally:
            upstream.close()

    def _allowed(self, host, port):
        if port is None:
            port = 443 if self.server.target_scheme == "https" else 80
        return host == self.server.target_host and port == self.server.target_port

    def _connect(self, authority):
        host, separator, port = authority.rpartition(":")
        try:
            port = int(port) if separator else 443
        except ValueError:
            self.send_error(400)
            return
        if not self._allowed(host, port):
            self.send_error(403)
            return
        upstream = socket.create_connection(
            (self.server.target_host, self.server.target_port), self.server.timeout
        )
        try:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            sockets = (self.connection, upstream)
            while True:
                readable, _, _ = select.select(sockets, (), (), self.server.timeout)
                if not readable:
                    return
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        finally:
            upstream.close()

    def send_error(self, status):
        self.wfile.write(
            f"HTTP/1.1 {status} Denied\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--scheme", choices=("http", "https"), required=True)
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()
    server = socketserver.ThreadingTCPServer(("0.0.0.0", 8080), Proxy)  # nosec B104 - isolated container, no published port
    server.daemon_threads = True
    server.target_host = args.host
    server.target_port = args.port
    server.target_scheme = args.scheme
    server.timeout = args.timeout
    server.serve_forever()


if __name__ == "__main__":
    main()
