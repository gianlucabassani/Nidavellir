"""Internal-only NV-05 fixture: HTTP readiness and a persistent TCP echo."""
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Ready(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib callback
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, _format, *args):
        pass


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data = self.request.recv(16384)
            if not data:
                break
            self.request.sendall(b"NV05:" + data)


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


threading.Thread(target=lambda: TCPServer(("0.0.0.0", 8123), Echo).serve_forever(),
                 daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", 8080), Ready).serve_forever()
