#!/usr/bin/env python3
"""Isolated real Docker-local REST/MCP configuration-introduction acceptance."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import base64
import importlib.util
import json
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("lineage_gate", ROOT / "scripts/verify-nv06-live.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
gate.COMPOSE = ("docker", "compose", "-p", "nidavellir-lineage", "-f", "docker-compose.nv06.yml",
                "-f", "docker-compose.configuration-lineage.yml")

MCP_PROGRAM = r'''
import anyio,json,os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/mcp") as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            assert "get_configuration_lineage" in {item.name for item in (await session.list_tools()).tools}
            result=await session.call_tool("get_configuration_lineage",arguments={
                "arena_id":os.environ["LINEAGE_ARENA"],"analysis_id":os.environ["LINEAGE_ANALYSIS"]})
            assert not result.isError,result
            value=result.structuredContent or json.loads(next(item.text for item in result.content if item.type=="text"))
            assert value["candidate_keys"]==["service.authorization.disabled"],value
            assert "evidence_digests" not in value
            print("LINEAGE_MCP="+json.dumps(value))
anyio.run(main)
'''


def main():
    tag = datetime.now(timezone.utc).strftime("%Y-%m-%d-") + uuid.uuid4().hex[:8]
    output = ROOT / f"docs/verification/configuration-lineage-live-{tag}.json"
    report = {"schema": "nidavellir/configuration-lineage-live/v1", "status": "running", "date": tag}
    with output.open("x") as handle:
        json.dump(report, handle)
    os.environ["LINEAGE_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    try:
        gate.run("docker", "build", "-f", "cyber-range/fixtures/config-lineage/Dockerfile",
                 "-t", "nidavellir/config-lineage:acceptance", ".")
        image = gate.run("docker", "image", "inspect", "nidavellir/config-lineage:acceptance",
                         "--format", "{{.Id}}").stdout.strip()
        base = gate.run("docker", "image", "inspect", "python:3.11.14-alpine",
                        "--format", "{{.Id}}").stdout.strip()
        gate.run(*gate.COMPOSE, "up", "-d", "--build", "postgres", "redis", "orchestrator", "worker", "agent-gateway")
        gate.wait("/health", lambda value: value.get("status") == "ok")
        gate.run(*gate.COMPOSE, "exec", "-T", "orchestrator", "python", "-c",
                 "from database import Database; from auth import hash_api_key; "
                 "db=Database(); k=hash_api_key('nv06-agent-key'); "
                 "db.create_api_key(k,'nv06-agent','agent') if db.get_api_key(k) is None else None")
        profile = json.loads((ROOT / "cyber-range/fixtures/config-lineage/profile.json").read_text())
        # This low-entropy synthetic value must never leave protected capture.
        secret = "lineage-private-fixture-value"
        scenario = {
            "schema": "nidavellir/v3", "name": "Configuration lineage fixture",
            "requires": {"provider_class": "container"},
            "network": {"segments": [{"name": "lab"}]},
            "nodes": [
                {"name": "target", "role": "victim", "image": image, "segments": ["lab"],
                 "ports": [8080], "environment": {"DISABLE_AUTH": "false", "SIGNING_SECRET": secret,
                                                      "DEBUG_MODE": "false"}},
                {"name": "attacker", "role": "attacker", "image": base,
                 "segments": ["lab"], "entrypoint": True, "command": "sleep infinity"}],
            "agents": [{"stance": "attacker", "node": "attacker"}],
            "vulnerabilities": [{"id": "authz-object", "title": "Cross-account object read",
                "cwe": "CWE-639", "node": "target", "validator": "authorization_effect",
                "validation_config": {"actor": "A", "owner": "B", "control_token": "token-b-operator"}}],
            "lifecycle": {"configuration_profile": profile,
                "seed": {"schema": "nidavellir/nv06-authz/v1", "effect_log": "empty"},
                "readiness": {"type": "http", "node": "target", "port": 8080, "path": "/health",
                    "expected_status": 200, "expected_state": {"seed": "nv06-v1", "ready": True},
                    "timeout_seconds": 20, "interval_seconds": 1}}}
        sid = "lineage-" + tag[-8:]
        snapshots, findings = [], []
        root_finding = None
        for index, enabled in enumerate(("false", "true", "true")):
            state = deepcopy(scenario)
            state["nodes"][0]["environment"]["DISABLE_AUTH"] = enabled
            if index == 2:
                state["nodes"][0]["environment"]["DISPLAY_THEME"] = "dark"
            gate.api("POST", "/scenarios", {"id": sid, "spec": state, "overwrite": index > 0})
            arena = gate.api("POST", "/deploy", {"scenario": sid, "instance_id": "lineage-state",
                "provider": "docker-local", "engagement_purpose": "research", "participant_mode": "agent",
                "engagement_time_box_seconds": 1800})["instance_id"]
            gate.ARENAS.append(arena)
            gate.wait(f"/status/{arena}", lambda value: value.get("status") == "active")
            if index < 2:
                reset = gate.api("POST", f"/arenas/{arena}/reset", {"idempotency_key": "lineage-reset-" + uuid.uuid4().hex}, expected=(202,))
                replacement = reset["replacement_id"]
                gate.ARENAS.append(replacement)
                operation = gate.wait(f"/reset-operations/{reset['operation_id']}", lambda value: value.get("status") in {"succeeded", "failed"})
                assert operation["status"] == "succeeded", operation
                arena = replacement
                # Reset retains the recipe/budget; explicitly retain the research intent.
                gate.run(*gate.COMPOSE, "exec", "-T", "orchestrator", "python", "-c",
                    "from database import Database; Database().record_event(" + repr(arena) +
                    ",'engagement_intent',{'purpose':'research'},actor='acceptance')")
            gate.bind(arena)
            snapshot = gate.api("POST", f"/arenas/{arena}/configuration-snapshots", {"stage": "runtime"}, expected=(201,))["snapshot"]
            assert secret not in json.dumps(snapshot) and "hmac-sha256:" not in json.dumps(snapshot)
            assert snapshot["completeness"]["status"] == "complete", snapshot["completeness"]
            snapshots.append(snapshot)
            action = gate.action(arena, "/objects/B", "lineage" + uuid.uuid4().hex)
            assert action["status"] == (403 if index == 0 else 200), action
            body = {"title": "Configuration enables cross-account disclosure", "cwe": "CWE-639",
                    "node": "target", "transaction_digests": [action["transaction_digest"]]}
            if root_finding:
                body["variant_of"] = root_finding
            finding = gate.api("POST", f"/arenas/{arena}/findings", body, key=gate.AGENT_KEY)
            root_finding = root_finding or finding["finding_id"]
            verdict = gate.validation(arena, finding["finding_id"])
            assert verdict["verdict"] == ("refuted" if index == 0 else "confirmed"), verdict
            findings.append({"arena_id": arena, "finding_id": finding["finding_id"], "verdict": verdict["verdict"]})
        body = {"subject_arena_id": snapshots[-1]["arena_id"],
                "snapshot_ids": [item["snapshot_id"] for item in snapshots],
                "research_key": root_finding, "publish_to": ["nv06-agent"]}
        analysis = gate.api("POST", "/configuration-lineage/analyze", body, expected=(201,))
        assert analysis["confidence"] == "proven", analysis
        assert analysis["earliest_known_vulnerable"] == snapshots[1]["snapshot_id"], analysis
        assert analysis["candidate_keys"] == ["service.authorization.disabled"], analysis
        report.update({"fixture_image": image, "snapshots": [{key: item[key] for key in (
            "arena_id", "snapshot_id", "snapshot_digest", "profile", "completeness")} for item in snapshots],
            "findings": findings, "analysis": analysis})
        arena = snapshots[-1]["arena_id"]
        budget_before = gate.api("GET", f"/arenas/{arena}/budget")
        mcp = gate.run(*gate.COMPOSE, "exec", "-T", "-e", f"LINEAGE_ARENA={arena}",
            "-e", f"LINEAGE_ANALYSIS={analysis['analysis_id']}", "agent-gateway", "python", "-c", MCP_PROGRAM).stdout
        assert "LINEAGE_MCP=" in mcp and secret not in mcp
        assert budget_before == gate.api("GET", f"/arenas/{arena}/budget")
        gate.api("GET", f"/arenas/{snapshots[0]['arena_id']}/configuration-lineage/{analysis['analysis_id']}",
                 key=gate.AGENT_KEY, expected=(404,))
        gate.api("GET", f"/arenas/{arena}/configuration-snapshots", key=gate.AGENT_KEY, expected=(403,))
        events = gate.api("GET", f"/deployments/{arena}/events", key=gate.AGENT_KEY)
        assert secret not in json.dumps(events) and "configuration_introduction" not in json.dumps(events)
        static = gate.api("POST", "/configuration-lineage/analyze", {**body,
            "subject_arena_id": snapshots[1]["arena_id"],
            "snapshot_ids": [item["snapshot_id"] for item in snapshots[:2]],
            "research_key": "unverified", "publish_to": []}, expected=(201,))
        assert static["confidence"] == "inferred"
        missing_history = gate.api("POST", "/configuration-lineage/analyze", {
            **body, "snapshot_ids": [snapshots[0]["snapshot_id"], snapshots[2]["snapshot_id"]],
            "publish_to": []}, expected=(201,))
        assert missing_history["confidence"] != "proven"
        gate.api("POST", f"/arenas/{arena}/setup/start", {"nodes": ["target"], "mode": "operator", "setup_egress": False})
        step = gate.api("POST", f"/arenas/{arena}/setup/step", {"node": "target", "command": "true",
            "configuration_step": "configure-auth"})
        assert step["exit_code"] == 0
        gate.api("POST", f"/arenas/{arena}/setup/finish", {})
        setup_snapshots = gate.api("GET", f"/arenas/{arena}/configuration-snapshots")["snapshots"]
        post_setup = next(item for item in setup_snapshots if item["stage"] == "post_setup")
        setup_fact = next(item for item in post_setup["effective"] if item["key"] == "service.setup.authorization.disabled")
        assert setup_fact["source_class"] == "setup" and setup_fact["source_ref"]["setup_event_id"]
        report["setup_provenance"] = True
        # Retain the third state's records but free its arena networks before
        # provisioning conservative cases. No unrelated host networks are pruned.
        gate.api("DELETE", f"/destroy/{snapshots[2]['arena_id']}", expected=(200, 202))
        gate.wait(f"/status/{snapshots[2]['arena_id']}", lambda value: value.get("status") == "destroyed")
        # Conservative cases use independently provisioned states, not hand-edited
        # verdicts. Every finding travels through the normal validator interface.
        def extra_case(state, label, *, reset_state=False):
            gate.api("POST", "/scenarios", {"id": sid, "spec": state, "overwrite": True})
            extra = gate.api("POST", "/deploy", {"scenario": sid, "instance_id": label,
                "provider": "docker-local", "engagement_purpose": "research", "participant_mode": "agent",
                "engagement_time_box_seconds": 1800})["instance_id"]
            gate.ARENAS.append(extra)
            gate.wait(f"/status/{extra}", lambda value: value.get("status") == "active")
            if reset_state:
                reset = gate.api("POST", f"/arenas/{extra}/reset", {"idempotency_key": "lineage-" + uuid.uuid4().hex}, expected=(202,))
                extra = reset["replacement_id"]
                gate.ARENAS.append(extra)
                operation = gate.wait(f"/reset-operations/{reset['operation_id']}", lambda value: value.get("status") in {"succeeded", "failed"})
                assert operation["status"] == "succeeded", operation
            gate.bind(extra)
            snapshot = gate.api("POST", f"/arenas/{extra}/configuration-snapshots", {"stage": "runtime"}, expected=(201,))["snapshot"]
            action = gate.action(extra, "/objects/B", "extra" + uuid.uuid4().hex)
            finding = gate.api("POST", f"/arenas/{extra}/findings", {
                "title": label, "cwe": "CWE-639", "node": "target", "variant_of": root_finding,
                "transaction_digests": [action["transaction_digest"]]}, key=gate.AGENT_KEY)
            verdict = gate.validation(extra, finding["finding_id"])
            result = gate.api("POST", "/configuration-lineage/analyze", {
                "subject_arena_id": extra, "snapshot_ids": [snapshots[0]["snapshot_id"], snapshot["snapshot_id"]],
                "research_key": root_finding}, expected=(201,))
            gate.api("DELETE", f"/destroy/{extra}", expected=(200, 202))
            gate.wait(f"/status/{extra}", lambda value: value.get("status") == "destroyed")
            return result, verdict

        multiple = deepcopy(scenario)
        multiple["nodes"][0]["environment"].update({"DISABLE_AUTH": "true", "DEBUG_MODE": "true"})
        multi, _ = extra_case(multiple, "simultaneous-changes", reset_state=True)
        assert multi["candidate_keys"] == ["service.authorization.disabled", "service.debug.enabled"], multi
        assert multi["causal_key"] is None
        failed_control = deepcopy(scenario)
        failed_control["nodes"][0]["environment"]["DISABLE_AUTH"] = "true"
        failed_control["vulnerabilities"][0]["validation_config"]["control_token"] = "invalid-control"
        failed, _ = extra_case(failed_control, "invalid-control")
        assert failed["confidence"] == "unknown", failed
        mutable = deepcopy(scenario)
        mutable["nodes"][0]["environment"]["DISABLE_AUTH"] = "true"
        mutable["nodes"][0]["image"] = "nidavellir/config-lineage:acceptance"
        gate.api("POST", "/scenarios", {"id": sid, "spec": mutable, "overwrite": True})
        mutable_denied = gate.api("POST", "/deploy", {"scenario": sid, "instance_id": "mutable-image",
            "provider": "docker-local", "engagement_purpose": "research", "participant_mode": "agent",
            "engagement_time_box_seconds": 1800}, expected=(422,))
        assert mutable_denied["status"] == 422
        mutable_result = {"confidence": "refused_unresolved_image"}
        conflicting = deepcopy(scenario)
        conflicting["nodes"][0]["environment"].update({"DISABLE_AUTH": "true", "READBACK_CONFLICT": "true"})
        conflict_result, _ = extra_case(conflicting, "conflicting-readbacks")
        assert conflict_result["confidence"] != "proven"
        missing_runtime = deepcopy(scenario)
        missing_runtime["nodes"][0]["environment"].update({"DISABLE_AUTH": "true", "READBACK_MISSING": "true"})
        missing_result, _ = extra_case(missing_runtime, "missing-active-value")
        assert missing_result["confidence"] != "proven"
        # A mutated writable layer invalidates a fresh proof even if Config.Env
        # and an old successful validation are unchanged.
        changed_arena = snapshots[1]["arena_id"]
        container = gate.run("docker", "ps", "-q", "--filter", f"label=nidavellir.lab_id={changed_arena}",
                             "--filter", "label=nidavellir.node=target").stdout.strip()
        assert container and "\n" not in container
        gate.run("docker", "exec", container, "python", "-c", "open('/tmp/lineage-mutation','w').write('changed')")
        mutated = gate.api("POST", "/configuration-lineage/analyze", {
            "subject_arena_id": changed_arena, "snapshot_ids": [item["snapshot_id"] for item in snapshots[:2]],
            "research_key": root_finding}, expected=(201,))
        assert mutated["confidence"] != "proven", mutated
        report["conservative_cases"] = {"simultaneous": multi["confidence"],
            "failed_control": failed["confidence"], "mutable": mutable_result["confidence"],
            "mutated_target": mutated["confidence"], "conflicting": conflict_result["confidence"],
            "missing_runtime": missing_result["confidence"], "missing_history": missing_history["confidence"]}
        gate.cleanup_arenas()
        retained = gate.api("GET", f"/configuration-lineage/analyses/{analysis['analysis_id']}")
        assert retained == analysis
        retained_agent = gate.api("GET", f"/arenas/{arena}/configuration-lineage/{analysis['analysis_id']}", key=gate.AGENT_KEY)
        assert retained_agent["candidate_keys"] == ["service.authorization.disabled"]
        assert retained_agent["delta"]["changes"][0]["before"]["value"] is False
        assert retained_agent["delta"]["changes"][0]["after"]["value"] is True
        assert secret not in json.dumps(retained_agent) and "hmac-sha256:" not in json.dumps(retained_agent)
        for item in snapshots:
            assert gate.api("GET", f"/arenas/{item['arena_id']}/configuration-snapshots/{item['snapshot_id']}") == item
        report.update({"status": "passed", "mcp": True, "post_teardown": True,
                       "static_downgrade": True, "budget_unchanged": True})
    except Exception as exc:
        report.update({"status": "failed", "error": str(exc)[:5000]})
        report["service_logs"] = gate.run(*gate.COMPOSE, "logs", "--tail", "45", "orchestrator", "worker", check=False).stdout[-12000:]
        raise
    finally:
        gate.cleanup_arenas()
        report["remaining"] = {arena: gate.inventory(arena) for arena in gate.ARENAS}
        gate.run(*gate.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(str(output))
        assert not any(count for inventory in report["remaining"].values() for count in inventory.values()), report["remaining"]


if __name__ == "__main__":
    main()
