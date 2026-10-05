#!/usr/bin/env python3
"""Verify one BYO-agent MCP run, write evidence, tear down the isolated stack.

Never issues model calls. The client result file is written by the harness that
ran the agent; this script only reads the target's records.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_module(fixture: str):
    if fixture == "nv06":
        return _load("verify_nv07_live", "verify-nv07-live.py").fixture
    return _load("verify_nv09_live", "verify-nv09-live.py").fixture


def main(setup_path: Path, result_path: Path) -> None:
    setup = json.loads(setup_path.read_text())
    result = json.loads(result_path.read_text())
    if setup["schema"] != "nidavellir/byo-agent-mcp-setup/v1":
        raise RuntimeError("unexpected BYO-agent setup evidence")
    fixture = _fixture_module(setup["fixture"])
    arena = setup["source_arena"]
    events = fixture.api("GET", f"/deployments/{arena}/events")["events"]
    findings = [event["payload"] for event in events if event["type"] == "finding"]
    verdicts = [finding.get("validation") or {} for finding in findings]
    confirmed = [verdict for verdict in verdicts if verdict.get("verdict") == "confirmed"]
    fixture.ARENAS.append(arena)
    fixture.cleanup_arenas()
    score_response = fixture.api("GET", f"/arenas/{arena}/score")
    score = score_response["score"]
    export = fixture.api("GET", f"/arenas/{arena}/eval-export")
    final_events = fixture.api("GET", f"/deployments/{arena}/events")["events"]
    final_verdicts = [event["payload"].get("validation") or {}
                      for event in final_events if event["type"] == "finding"]
    resources = fixture.inventory(arena)
    if any(resources.values()):
        raise RuntimeError(f"labelled resources remain: {resources}")
    evidence = {
        "schema": "nidavellir/byo-agent-mcp-evidence/v1",
        "setup": setup_path.name,
        "fixture": setup["fixture"],
        "arena": arena,
        "participant": {
            "client": result.get("client"),
            "model": result.get("model"),
            "turns": result.get("turns"),
            "reported_usage": result.get("reported_usage"),
            "reported_cost_usd": result.get("reported_cost_usd"),
            "result_status": result.get("result_status"),
            "events_file": result.get("events_file"),
        },
        "transcript": result.get("transcript"),
        "findings": [{
            "id": finding.get("finding_id"),
            "validation": {key: verdict.get(key) for key in (
                "verdict", "method", "reason_code", "action_digest",
                "observation_digest", "control_digest")},
        } for finding, verdict in zip(findings, final_verdicts)],
        "confirmed_findings": len(confirmed),
        "score": {"value": score.get("value"), "answer": score.get("answer"),
                  "confirmed_findings": score_response.get("confirmed_findings"),
                  "points_earned": score_response.get("points_earned"),
                  "points_total": score_response.get("points_total")},
        "export_after_teardown": bool(export),
        "final_resources": resources,
    }
    path = setup_path.with_name(setup_path.stem.replace("-setup-", "-evidence-") + ".json")
    with path.open("x") as handle:
        handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    print(f"BYO-agent evidence: {path}")
    print(f"Confirmed findings: {len(confirmed)}; resources: {resources}")
    if not confirmed:
        raise RuntimeError("the agent produced no independently confirmed finding")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: finalize-byo-agent-mcp.py SETUP_JSON RESULT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
