#!/usr/bin/env python3
"""Synthetic SPA/BH-13 MCP slice; no model or external campaign connection."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_nv07_live", Path(__file__).with_name("verify-nv07-live.py"))
nv07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv07)
fixture = nv07.fixture
LIBRARY = json.loads((ROOT / "cyber-range/fixtures/nv09-spa/library-v1.json").read_text())
MANIFEST_SCHEMA = json.loads((ROOT / "cyber-range/fixtures/nv09-spa/manifest-v1.schema.json").read_text())
evaluation_id = None


def _digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _plan(path):
    # The only difference between builds is the controlled cross-account path.
    return [
        {"tool": "browser_visit", "args": {"node": "target", "path": "/",
            "params": {"account": "A"}, "wait_ms": 2000},
         "expect_dom": "Account A owns an object"},
        {"tool": "browser_visit", "args": {"node": "target", "path": "/",
            "params": {"account": "B"}, "wait_ms": 2000},
         "expect_dom": "Account B owns an object"},
        {"tool": "http_request", "args": {"node": "target", "path": path,
            "headers": {"Authorization": "Bearer token-a-public",
                        "X-Request-ID": "nv09cross1"}}},
        {"tool": "report_finding", "args": {"title": "Cross-account object read",
            "cwe": "CWE-639", "node": "target",
            "transaction_digests": ["$last_transaction_digest"]}},
    ]


def _prepare():
    started = time.monotonic()
    fixture.run("docker", "build", "-t", "nidavellir/nv09-spa:acceptance",
                "cyber-range/fixtures/nv09-spa")
    image_id = fixture.run("docker", "image", "inspect", "nidavellir/nv09-spa:acceptance",
                           "--format", "{{.Id}}").stdout.strip()
    fixture.run("docker", "pull", "python:3.11.14-alpine")
    base_id = fixture.run("docker", "image", "inspect", "python:3.11.14-alpine",
                          "--format", "{{.Id}}").stdout.strip()
    fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    fixture.run(*fixture.COMPOSE, "up", "-d", "--build", "postgres", "redis",
                "orchestrator", "worker", "webui", "agent-gateway")
    fixture.wait("/health", lambda data: data.get("status") == "ok")
    fixture.run(*fixture.COMPOSE, "exec", "-T", "orchestrator", "python", "-c",
        "from database import Database; from auth import hash_api_key; "
        "Database().create_api_key(hash_api_key('nv06-agent-key'),'nv06-agent','agent')")
    scenario = {
        "schema": "nidavellir/v3", "name": "NV-09 synthetic SPA authorization",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [
            {"name": "target", "role": "victim", "image": image_id,
             "segments": ["lab"], "ports": [8080]},
            {"name": "attacker", "role": "attacker", "image": base_id,
             "segments": ["lab"], "entrypoint": True, "command": "sleep infinity"}],
        "agents": [{"stance": "attacker", "node": "attacker"}],
        "vulnerabilities": [{"id": "nv09-authz-object", "title": "Cross-account object read",
            "cwe": "CWE-639", "node": "target", "points": 1,
            "validator": "authorization_effect", "validation_config": {
                "actor": "A", "owner": "B", "control_token": "token-b-operator"}}],
        "lifecycle": {"seed": LIBRARY["seed"], "readiness": {
            "type": "http", "node": "target", "port": 8080, "path": "/health",
            "expected_status": 200,
            "expected_state": {"seed": "nv09-spa-v1", "ready": True},
            "timeout_seconds": 20, "interval_seconds": 1}}}
    fixture.api("POST", "/scenarios", {"id": "nv09-spa", "spec": scenario})
    source = fixture.api("POST", "/deploy", {"scenario": "nv09-spa",
        "instance_id": "nv09-spa-source", "provider": "docker-local",
        "engagement_purpose": "calibration", "participant_mode": "agent",
        "engagement_time_box_seconds": 1800})["instance_id"]
    fixture.ARENAS.append(source)
    fixture.wait(f"/status/{source}", lambda data: data.get("status") == "active")
    challenge = fixture.api("POST", "/eval-challenges", {
        "name": "BH-13 synthetic SPA cross-account comparison", "version": "v1",
        "source_arena_id": source, "label": "calibration"}, expected=(201,))
    baseline_plan, candidate_plan = _plan("/objects/B"), _plan("/protected/B")
    assert [{**step, "args": {**step["args"], "path": "/objects/B"}}
            if i == 2 else step for i, step in enumerate(candidate_plan)] == baseline_plan
    good = fixture.api("POST", "/agent-builds", {"name": "bh13-effect-path",
        "version": "v1", "plan": baseline_plan}, expected=(201,))
    bad = fixture.api("POST", "/agent-builds", {"name": "bh13-denied-path",
        "version": "v1", "plan": candidate_plan}, expected=(201,))
    return (time.monotonic() - started, image_id, source, challenge, good, bad,
            baseline_plan, candidate_plan)


def _trial_proof(trial, side, challenge_id):
    arena_id = trial["arena_id"]
    events = fixture.api("GET", f"/deployments/{arena_id}/events")["events"]
    finding = next(e["payload"] for e in events if e["type"] == "finding" and
                   e["payload"].get("matched_vuln_id") == "nv09-authz-object")
    verdict = finding["validation"]
    assert verdict["verdict"] == ("confirmed" if side == "baseline" else "refuted")
    assert verdict["action_digest"] and verdict["observation_digest"] and verdict["control_digest"]
    for key in ("observation_digest", "control_digest"):
        assert fixture.api("GET", f"/arenas/{arena_id}/validation-evidence/{verdict[key]}")
    transcript = trial["result"]["transcript"]
    assert [step["tool"] for step in transcript] == [
        "browser_visit", "browser_visit", "http_request", "report_finding"]
    assert all(step["dom_sha256"] for step in transcript[:2])
    row = fixture.api("GET", f"/arenas/{arena_id}/eval-export")
    assert row["metadata"]["nv.leakage_label"] == "calibration"
    assert fixture.api("GET", f"/arenas/{arena_id}/score")
    return {"arena_id": arena_id, "challenge_id": challenge_id, "side": side,
        "starting_digest": trial["starting_digest"], "verdict": verdict["verdict"],
        "reason_code": verdict["reason_code"], "action_digest": verdict["action_digest"],
        "observation_digest": verdict["observation_digest"],
        "control_digest": verdict["control_digest"],
        "browser_dom_digests": [step["dom_sha256"] for step in transcript[:2]]}


def main():
    global evaluation_id
    setup_seconds, image_id, source, challenge, good, bad, good_plan, bad_plan = _prepare()
    suite = fixture.api("POST", "/eval-suites", {"name": "bh13-spa-three-pairs",
        "version": "v1", "challenge_ids": [challenge["id"]], "seeds": [1, 2, 3],
        "action_cap": 8, "deadline_seconds": 600}, expected=(201,))
    evaluation = fixture.api("POST", "/evaluations", {"suite_id": suite["id"],
        "baseline_id": good["id"], "candidate_id": bad["id"]}, expected=(202,))
    evaluation_id = evaluation["id"]
    record = fixture.wait(f"/evaluations/{evaluation_id}",
        lambda data: data.get("state") == "complete", timeout=1800)
    fixture.ARENAS.extend(t["arena_id"] for t in record["trials"] if t["arena_id"])
    assert len(record["trials"]) == 6 and all(t["state"] == "completed" for t in record["trials"])
    comparison = record["comparison"]
    assert comparison["matched_pairs"] == 3 and comparison["infrastructure_failed_pairs"] == 0
    assert comparison["evidence_scope"] == "calibration_or_unknown"
    by_challenge = comparison["by_challenge"][challenge["id"]]
    assert by_challenge["differences"]["verified"]["mean"] == -1
    assert by_challenge["matched_pairs"] == 3
    runs = {run["id"]: run for run in record["runs"]}
    proofs = [_trial_proof(t, runs[t["run_id"]]["side"], challenge["id"])
              for t in record["trials"]]
    fixture.api("DELETE", f"/destroy/{source}", expected=(200, 202))
    for arena in fixture.ARENAS:
        fixture.wait(f"/status/{arena}", lambda data: data.get("status") == "destroyed")
    # The evidence store and operator projection must still answer after teardown.
    for proof in proofs:
        assert fixture.api("GET", f"/arenas/{proof['arena_id']}/validation-evidence/"
                           f"{proof['observation_digest']}")
        assert fixture.api("GET", f"/arenas/{proof['arena_id']}/eval-export")
    resources = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
    assert not any(any(counts.values()) for counts in resources.values()), resources
    manifest = {"schema": MANIFEST_SCHEMA["$id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": {"scenario": "nv09-spa", "version": "v1", "image_digest": image_id,
                   "challenge_id": challenge["id"], "leakage_label": "calibration"},
        "builds": {"baseline": {"id": good["id"], "digest": good["digest"],
                               "driver": good["driver"], "tools": [s["tool"] for s in good_plan]},
                   "candidate": {"id": bad["id"], "digest": bad["digest"],
                                 "driver": bad["driver"], "tools": [s["tool"] for s in bad_plan]}},
        "seed": {"schema": LIBRARY["seed"]["schema"], "digest": _digest(LIBRARY["seed"]),
                 "accounts": ["A", "B"], "owned_object": "B"},
        "budget": {"action_cap": 8, "deadline_seconds": 600},
        "healthy_control": {"path": "/protected/B", "owner": "B",
                            "validator": challenge["validator_version"]},
        "participant_change": {"step": 3, "tool": "http_request", "field": "path",
                               "baseline": "/objects/B", "candidate": "/protected/B"},
        "target_effects": proofs,
        "provenance": {"source_arena_id": source, "recipe_digest": challenge["recipe_digest"],
                       "evaluation_id": evaluation_id, "suite_id": suite["id"],
                       "fixture_library_digest": _digest(LIBRARY),
                       "synthetic_only": True},
        "comparison": comparison,
        "setup": {"elapsed_seconds": round(setup_seconds, 2),
                  "manual_steps": ["run make verify-nv09-live"],
                  "reused": ["NV-07 durable paired trials", "NV-06 authorization validator",
                             "NV-02 replacement reset", "MCP browser and HTTP tools"],
                  "operator_decision": "Review whether this controlled workflow merits Bughunt attachment"},
        "final_resources": resources}
    jsonschema.validate(manifest, MANIFEST_SCHEMA)
    path = ROOT / "docs/verification" / (
        f"nv09-live-{datetime.now():%Y-%m-%d}-{uuid.uuid4().hex[:8]}.json")
    with path.open("x") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"NV-09 live manifest: {path}")


if __name__ == "__main__":
    try:
        main()
    finally:
        if evaluation_id:
            try:
                record = fixture.api("GET", f"/evaluations/{evaluation_id}")
                fixture.ARENAS.extend(t["arena_id"] for t in record["trials"]
                                      if t["arena_id"] and t["arena_id"] not in fixture.ARENAS)
            except (OSError, RuntimeError):
                pass
        fixture.cleanup_arenas()
        fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        leftovers = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
        if any(any(value.values()) for value in leftovers.values()):
            raise RuntimeError(f"NV-09 cleanup left labelled resources: {leftovers}")
