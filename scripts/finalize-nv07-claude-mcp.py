#!/usr/bin/env python3
"""Verify and clean up one Claude Code MCP test, without issuing model calls."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_nv07_live", Path(__file__).with_name("verify-nv07-live.py"))
nv07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv07)


def main(setup_path: Path, result_path: Path) -> None:
    setup = json.loads(setup_path.read_text())
    result = json.loads(result_path.read_text())
    if setup["schema"] != "nidavellir/nv07-claude-mcp-setup/v1":
        raise RuntimeError("unexpected Claude MCP setup evidence")
    arena = setup["source_arena"]
    initial_events = nv07.fixture.api("GET", f"/deployments/{arena}/events")["events"]
    findings = [event["payload"] for event in initial_events if event["type"] == "finding"]
    if len(findings) != 1:
        raise RuntimeError("expected exactly one synthetic finding")
    validation = findings[0].get("validation") or {}
    if validation.get("verdict") != "confirmed":
        raise RuntimeError("independent validator did not confirm the finding")
    nv07.fixture.ARENAS.append(arena)
    nv07.fixture.cleanup_arenas()
    score_response = nv07.fixture.api("GET", f"/arenas/{arena}/score")
    score = score_response["score"]
    export = nv07.fixture.api("GET", f"/arenas/{arena}/eval-export")
    final_events = nv07.fixture.api("GET", f"/deployments/{arena}/events")["events"]
    final_validation = next((event["payload"].get("validation") or {}
        for event in final_events if event["type"] == "finding"), {})
    resources = nv07.fixture.inventory(arena)
    if any(resources.values()):
        raise RuntimeError(f"labelled resources remain: {resources}")
    evidence = {
        "schema": "nidavellir/nv07-claude-mcp-evidence/v1",
        "setup": setup_path.name,
        "arena": arena,
        "participant": {"client": "Claude Code", "model": "Haiku",
                         "turns": result.get("num_turns"),
                         "reported_cost_usd": result.get("total_cost_usd"),
                         "reported_usage": result.get("usage"),
                         "result_status": result.get("subtype")},
        "mcp_event_types": sorted({event["type"] for event in final_events}),
        "finding": {"id": findings[0].get("finding_id"),
                    "validation": {key: final_validation.get(key) for key in (
                        "verdict", "method", "reason_code", "action_digest",
                        "observation_digest", "control_digest")}},
        "score": {"value": score.get("value"), "answer": score.get("answer"),
                  "confirmed_findings": score_response.get("confirmed_findings"),
                  "points_earned": score_response.get("points_earned"),
                  "points_total": score_response.get("points_total")},
        "export_after_teardown": bool(export),
        "final_resources": resources,
    }
    path = setup_path.with_name(setup_path.stem.replace("-setup-", "-") + ".json")
    with path.open("x") as handle:
        handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    nv07.fixture.run(*nv07.fixture.COMPOSE, "down", "--volumes",
                     "--remove-orphans", check=False)
    print(f"Claude MCP evidence: {path}")
    print(f"Independent verdict: {final_validation.get('verdict')}; resources: {resources}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        raise SystemExit("usage: finalize-nv07-claude-mcp.py SETUP_JSON RESULT_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
