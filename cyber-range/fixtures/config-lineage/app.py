"""Configuration-controlled variant of the NV-06 calibration fixture."""
import os

import base_app


class Handler(base_app.Handler):
    def do_GET(self):  # noqa: N802
        if self.server.server_port == 8081 and self.path == "/oracle/configuration":
            values = {
                "DISABLE_AUTH": os.environ.get("DISABLE_AUTH") == "true",
                "AUTHORIZATION_MIRROR": (os.environ.get("DISABLE_AUTH") == "true") != (os.environ.get("READBACK_CONFLICT") == "true"),
                "DEBUG_MODE": os.environ.get("DEBUG_MODE") == "true",
                "SIGNING_SECRET": os.environ.get("SIGNING_SECRET", "")}
            if os.environ.get("READBACK_MISSING") == "true":
                values.pop("DEBUG_MODE")
            self._send(200, {"schema": "nidavellir/configuration-runtime/v1", "values": values})
            return
        if self.path.startswith("/objects/") and os.environ.get("DISABLE_AUTH") != "true":
            self.path = self.path.replace("/objects/", "/protected/", 1)
        return super().do_GET()


base_app.Handler = Handler

if __name__ == "__main__":
    base_app.main()
