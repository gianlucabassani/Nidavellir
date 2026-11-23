#!/usr/bin/env python3
"""PF-01 U1 live check: can a locked arena node reach services on the Docker host?

Claim (review 2026-11-16): a locked node reaches host services through its bridge
gateway. This recreates both network types docker-local gives a locked arena, with
the provider's own options: an ``internal`` segment, and the no-masquerade ingress
bridge that a node publishing ports uses as its primary network. From a throwaway
container on each it probes TCP services listening on the host, at the bridge
gateway and at every non-loopback host address. A normal (masquerading) bridge is
probed the same way as a positive control. If the control reaches nothing, the
probe itself is broken and the run fails instead of passing. Open-egress arenas
use such a normal bridge, so the control also shows what they can reach.

  .venv/bin/python scripts/verify-pf01-live.py [--output docs/verification/pf01-u1.json]

Only local Docker objects labelled ``pf01=1`` are created, and they are removed at
the end. Host addresses are discovered at run time, and the evidence stays local.
"""
from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed docker argv
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cyber-range" / "services" / "scenario-orchestrator"))

from providers.docker_local import _NO_MASQUERADE  # noqa: E402

PROBE_IMAGE = "alpine:3.20"
PUBLIC_PROBE = "1.1.1.1:443"
MAX_HOST_PORTS = 6


def docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True,  # nosec B603
                            timeout=120, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {args[0]}: {result.stderr.strip()[-400:]}")
    return result.stdout.strip()


def host_targets() -> list[str]:
    """Host TCP listeners not bound to loopback, as ``address:port`` targets."""
    out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True,  # nosec B603 B607
                         check=True).stdout
    addresses: set[str] = set()
    ports: dict[str, set[int]] = {}
    for line in out.splitlines():
        local = line.split()[3]
        address, _, port = local.rpartition(":")
        address = address.strip("[]").split("%")[0]
        if address.startswith("127.") or address in ("::1", "::"):
            continue
        ports.setdefault(address, set()).add(int(port))
        addresses.add(address)
    targets = []
    for address in sorted(addresses):
        if ":" in address:
            continue  # IPv4 probes only; the arena bridges are IPv4
        for port in sorted(ports[address])[:MAX_HOST_PORTS]:
            targets.append(f"{address}:{port}")
    return targets


def probe(network: str, targets: list[str]) -> dict[str, bool]:
    script = "; ".join(
        f'if nc -z -w 3 {t.rsplit(":", 1)[0]} {t.rsplit(":", 1)[1]} 2>/dev/null; '
        f'then echo "{t} 1"; else echo "{t} 0"; fi' for t in targets)
    out = docker("run", "--rm", "--network", network, "--label", "pf01=1",
                 PROBE_IMAGE, "sh", "-c", script)
    return {line.split()[0]: line.split()[1] == "1" for line in out.splitlines() if line}


def main() -> int:
    parser = argparse.ArgumentParser()
    tag = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "-" + uuid.uuid4().hex[:8]
    parser.add_argument("--output", default=str(ROOT / f"docs/verification/pf01-u1-{tag}.json"))
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")

    suffix = uuid.uuid4().hex[:8]
    networks = {
        "internal_segment": (f"pf01-internal-{suffix}", ["--internal"]),
        "ingress_no_masquerade": (f"pf01-ingress-{suffix}",
                                  [arg for key, value in _NO_MASQUERADE.items()
                                   for arg in ("-o", f"{key}={value}")]),
        "control_normal_bridge": (f"pf01-control-{suffix}", []),
    }
    report: dict = {"schema": "nidavellir.pf01-u1.v1", "claim": "U1",
                    "docker": docker("version", "--format", "{{.Server.Version}}"),
                    "results": {}}
    created = []
    try:
        base_targets = host_targets() + [PUBLIC_PROBE]
        for label, (name, options) in networks.items():
            docker("network", "create", "--label", "pf01=1", *options, name)
            created.append(name)
            gateway = docker("network", "inspect", name, "--format",
                             "{{(index .IPAM.Config 0).Gateway}}")
            gateway_ports = [t.rsplit(":", 1)[1] for t in base_targets
                             if t != PUBLIC_PROBE][:MAX_HOST_PORTS]
            targets = [f"{gateway}:{p}" for p in dict.fromkeys(gateway_ports)] + base_targets
            reached = probe(name, targets)
            report["results"][label] = {
                "reachable": sorted(t for t, ok in reached.items() if ok),
                "probed": len(reached)}
        locked = [report["results"][k]["reachable"]
                  for k in ("internal_segment", "ingress_no_masquerade")]
        control = report["results"]["control_normal_bridge"]["reachable"]
        report["probe_valid"] = bool(control)
        report["locked_reaches_host"] = any(locked)
        report["open_egress_reaches"] = control
        report["status"] = ("invalid_probe" if not control
                            else "confirmed" if any(locked) else "refuted")
    finally:
        for name in created:
            docker("network", "rm", name, check=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"evidence": str(output), "status": report["status"]}))
    return 0 if report["status"] == "refuted" else 1


if __name__ == "__main__":
    sys.exit(main())
