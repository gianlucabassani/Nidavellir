"""
Issue #30: nothing publishes a port beyond loopback.

The orchestrator holds the host Docker socket (root-equivalent on the host), and
the dev and acceptance stacks accept keys that are public in this repository. A
port published on 0.0.0.0 hands that to anyone on the host's LAN, VPN or tailnet
while the stack runs. Every published port in every Compose file, as rendered by
`docker compose config` (interpolation and overrides applied), must bind
127.0.0.1.
"""
import json
import os
import shutil
# subprocess runs one fixed docker argv, never a shell.
import subprocess  # nosec B404
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI absent")

ENV = {**os.environ, "NV14_SECRETS_ENCRYPTION_KEY": "x", "UI_R4_REPO_DIR": str(ROOT),
       "REDIS_PASSWORD": "x" * 16, "POSTGRES_PASSWORD": "x" * 16,
       "NIDAVELLIR_API_KEY": "x" * 32, "WEBUI_PASSWORD": "x" * 16, "SECRET_KEY": "x" * 32,
       "SECRETS_ENCRYPTION_KEY": "x", "DATABASE_URL": "postgresql+psycopg://n:x@postgres/n"}

STACKS = {
    "dev": ["docker-compose.yml", "docker-compose.dev.yml"],
    "base": ["docker-compose.yml"],
    "prod": ["docker-compose.yml", "docker-compose.prod.yml"],
    **{f"acceptance-{p.stem}": [str(p.relative_to(ROOT))]
       for p in sorted((ROOT / "compose" / "acceptance").glob("nv0[2-6].yml"))},
    "acceptance-nv14": ["compose/acceptance/nv06.yml", "compose/acceptance/nv14.yml"],
    "acceptance-ui-r4": ["compose/acceptance/nv06.yml", "compose/acceptance/ui-r4.yml"],
}


def _publications(files):
    argv = ["docker", "compose", "--project-directory", str(ROOT)]
    for name in files:
        argv += ["-f", str(ROOT / name)]
    argv += ["--profile", "postgres", "--profile", "agent-gateway", "config",
             "--format", "json"]
    result = subprocess.run(argv, capture_output=True, text=True, env=ENV,  # nosec B603 B607
                            timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-800:]
    services = json.loads(result.stdout).get("services") or {}
    return [(service, port.get("host_ip"), port.get("published"))
            for service, spec in services.items() for port in spec.get("ports") or []]


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_every_published_port_binds_loopback(stack):
    exposed = [p for p in _publications(STACKS[stack]) if p[1] != "127.0.0.1"]
    assert not exposed, f"{stack} publishes beyond loopback: {exposed}"
