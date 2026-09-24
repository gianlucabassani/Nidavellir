#!/usr/bin/env python3
"""Isolated Docker-local NV-06 action/effect/control acceptance gate."""
from __future__ import annotations

import http.cookiejar
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ("docker", "compose", "-f", "docker-compose.nv06.yml")
API = "http://127.0.0.1:18006"
WEB = "http://127.0.0.1:15006"
KEY = "nv06-acceptance-key"
AGENT_KEY = "nv06-agent-key"
ARENAS: list[str] = []


def run(*args, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stdout[-1800:]} {result.stderr[-1800:]}")
    return result


def api(method, path, body=None, *, key=KEY, expected=(200,)):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers={
        "X-API-Key": key, **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:  # nosec B310 - fixed local service
            value = json.loads(response.read() or b"{}")
            assert response.status in expected, (path, response.status, value)
            return value
    except urllib.error.HTTPError as exc:
        value = {"status": exc.code, "body": exc.read().decode("utf-8", "replace")}
        if exc.code not in expected:
            raise RuntimeError(f"{method} {path}: {value}") from exc
        return value


def wait(path, predicate, timeout=120):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = api("GET", path)
            if predicate(last):
                return last
        except (OSError, RuntimeError) as exc:
            last = str(exc)
        time.sleep(.5)
    raise RuntimeError(f"timed out waiting for {path}: {last}")


def inventory(arena):
    label = f"label=nidavellir.lab_id={arena}"
    return {kind: len(run("docker", *command, "-q", "--filter", label,
                          check=False).stdout.split()) for kind, command in {
        "containers": ("ps", "-a"), "networks": ("network", "ls"),
        "volumes": ("volume", "ls"), "images": ("image", "ls"),
    }.items()}


def cleanup_arenas():
    """Reclaim only arenas created by this invocation, even after assertion failure."""
    for arena in ARENAS:
        try:
            state = api("GET", f"/status/{arena}").get("status")
            if state not in ("destroyed", "failed"):
                api("DELETE", f"/destroy/{arena}", expected=(200, 202))
                wait(f"/status/{arena}", lambda value: value.get("status") == "destroyed", 40)
        except (OSError, RuntimeError):
            pass
        label = f"label=nidavellir.lab_id={arena}"
        for command, remove in (
            (("ps", "-a"), ("rm", "-f")),
            (("network", "ls"), ("network", "rm")),
            (("volume", "ls"), ("volume", "rm")),
        ):
            ids = run("docker", *command, "-q", "--filter", label,
                      check=False).stdout.split()
            if ids:
                run("docker", *remove, *ids, check=False)


def console(arena, expected):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = opener.open(WEB + "/login", timeout=10).read().decode()  # nosec B310
    token = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page).group(1)
    opener.open(urllib.request.Request(WEB + "/login", data=urllib.parse.urlencode({
        "username": "admin", "password": "nv06-local-only", "csrf_token": token,
    }).encode()), timeout=10)  # nosec B310
    page = opener.open(WEB + f"/arena/{arena}#findings", timeout=15).read().decode()  # nosec B310
    assert expected in page and "Independent validation" in page
    return f"/arena/{arena}#findings"


MCP_PROGRAM = r'''
import anyio,json,os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/mcp") as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            result = await session.call_tool("report_finding", arguments={
                "arena_id": os.environ["NV06_ARENA"], "title": "A reads B private object",
                "cwe": "CWE-639", "node": "target", "path": "/objects/B",
                "poc": "GET /objects/B using account A",
                "transaction_digests": [os.environ["NV06_DIGEST"]]})
            assert not result.isError, result
            value = result.structuredContent or json.loads(next(
                item.text for item in result.content if item.type == "text"))
            assert set(value) == {"recorded", "finding_id"}, value
            print("NV06_MCP=" + json.dumps(value))
anyio.run(main)
'''


def mcp_report(arena, digest):
    output = run(*COMPOSE, "exec", "-T", "-e", f"NV06_ARENA={arena}",
                 "-e", f"NV06_DIGEST={digest}", "agent-gateway", "python", "-c",
                 MCP_PROGRAM).stdout
    return json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                           if line.startswith("NV06_MCP=")))


def bind(arena):
    api("POST", f"/arenas/{arena}/bindings", {"agent_name": "nv06-agent",
                                               "stance": "attacker"})


def action(arena, path, request_id):
    return api("POST", f"/arenas/{arena}/http/request", {
        "node": "target", "method": "GET", "path": path,
        "headers": {"Authorization": "Bearer token-a-public", "X-Request-ID": request_id},
    }, key=AGENT_KEY)


def finding(arena, digest=None):
    body = {"title": "A reads B private object", "cwe": "CWE-639",
            "node": "target", "path": "/objects/B", "poc": "Synthetic authorization proof"}
    if digest:
        body["transaction_digests"] = [digest]
    result = api("POST", f"/arenas/{arena}/findings", body, key=AGENT_KEY)
    assert set(result) == {"recorded", "finding_id"}, result
    return result


def validation(arena, finding_id):
    events = api("GET", f"/deployments/{arena}/events")['events']
    return next(e["payload"]["validation"] for e in events if e["type"] == "finding"
                and e["payload"]["finding_id"] == finding_id)


def main():
    run("docker", "build", "-t", "nidavellir/nv06-authz:acceptance",
        "cyber-range/fixtures/nv06-authz")
    image_id = run("docker", "image", "inspect", "nidavellir/nv06-authz:acceptance",
                   "--format", "{{.Id}}").stdout.strip()
    run("docker", "pull", "python:3.11.14-alpine")
    base_id = run("docker", "image", "inspect", "python:3.11.14-alpine",
                  "--format", "{{.Id}}").stdout.strip()
    assert image_id.startswith("sha256:") and base_id.startswith("sha256:")
    run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    run(*COMPOSE, "up", "-d", "--build", "postgres", "redis", "orchestrator",
        "worker", "webui", "agent-gateway")
    wait("/health", lambda value: value.get("status") == "ok")
    scenario = {
        "schema": "nidavellir/v3", "name": "NV-06 authorization fixture",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [
            {"name": "target", "role": "victim", "image": image_id,
             "segments": ["lab"], "ports": [8080]},
            {"name": "attacker", "role": "attacker", "image": base_id,
             "segments": ["lab"], "entrypoint": True, "command": "sleep infinity"},
        ],
        "agents": [{"stance": "attacker", "node": "attacker"}],
        "vulnerabilities": [{"id": "authz-object", "title": "Cross-account object read",
                             "cwe": "CWE-639", "node": "target", "points": 1,
                             "validator": "authorization_effect",
                             "validation_config": {"actor": "A", "owner": "B",
                                                   "control_token": "token-b-operator"}}],
        "lifecycle": {
            "seed": {"schema": "nidavellir/nv06-authz/v1", "accounts": ["A", "B"],
                     "objects_per_account": 1, "effect_log": "empty"},
            "readiness": {"type": "http", "node": "target", "port": 8080,
                          "path": "/health", "expected_status": 200,
                          "expected_state": {"seed": "nv06-v1", "ready": True},
                          "timeout_seconds": 20, "interval_seconds": 1},
        },
    }
    api("POST", "/scenarios", {"id": "nv06-authz-fixture", "spec": scenario})
    run(*COMPOSE, "exec", "-T", "orchestrator", "python", "-c",
        "from database import Database; from auth import hash_api_key; "
        "Database().create_api_key(hash_api_key('nv06-agent-key'),'nv06-agent','agent')")
    source = api("POST", "/deploy", {"scenario": "nv06-authz-fixture",
        "instance_id": "nv06-positive", "provider": "docker-local",
        "engagement_purpose": "calibration", "participant_mode": "agent",
        "engagement_time_box_seconds": 900})["instance_id"]
    ARENAS.append(source)
    wait(f"/status/{source}", lambda value: value.get("status") == "active")
    bind(source)
    assert api("POST", f"/arenas/{source}/exec", {"node": "target",
               "command": "cat /app/app.py"}, key=AGENT_KEY,
               expected=(403,))["status"] == 403
    lifecycle = api("GET", f"/arenas/{source}/lifecycle")
    assert lifecycle["classification"]["runtime_reset"]["status"] == "eligible"

    positive_action = action(source, "/objects/B", "nvpos" + uuid.uuid4().hex)
    assert positive_action["status"] == 200 and "private-B" in positive_action["body"]
    positive_finding = mcp_report(source, positive_action["transaction_digest"])
    pos = validation(source, positive_finding["finding_id"])
    assert pos["schema"] == "nidavellir/validation-verdict/v1"
    assert pos["verdict"] == "confirmed" and pos["reason_code"] == "unauthorized_read"
    assert pos["action_digest"] == positive_action["transaction_digest"]
    for digest in (pos["observation_digest"], pos["control_digest"]):
        assert api("GET", f"/arenas/{source}/validation-evidence/{digest}")["digest"] == digest
        assert api("GET", f"/arenas/{source}/validation-evidence/{digest}",
                   key=AGENT_KEY, expected=(403,))["status"] == 403
    assert api("GET", f"/arenas/{source}/score", key=AGENT_KEY,
               expected=(403,))["status"] == 403
    agent_events = api("GET", f"/deployments/{source}/events", key=AGENT_KEY)["events"]
    assert all("validation" not in (e.get("payload") or {}) for e in agent_events
               if e.get("type") == "finding")
    assert not any(e.get("type") == "finding_verification" for e in agent_events)
    assert api("GET", f"/arenas/{source}/score")["score"]["value"] == 1.0
    review_link = console(source, "unauthorized_read")

    reset = api("POST", f"/arenas/{source}/reset",
                {"idempotency_key": "nv06-reset-" + uuid.uuid4().hex}, expected=(202,))
    replacement = reset["replacement_id"]
    ARENAS.append(replacement)
    operation = wait(f"/reset-operations/{reset['operation_id']}",
                     lambda value: value.get("status") in ("succeeded", "failed"))
    assert operation["status"] == "succeeded", operation
    wait(f"/status/{replacement}", lambda value: value.get("status") == "active")
    assert api("GET", f"/arenas/{replacement}/lifecycle")["observation"][
        "observed_state_digest"] == lifecycle["observation"]["observed_state_digest"]
    bind(replacement)
    denied = action(replacement, "/protected/B", "nvneg" + uuid.uuid4().hex)
    assert denied["status"] == 403
    negative_finding = finding(replacement, denied["transaction_digest"])
    neg = validation(replacement, negative_finding["finding_id"])
    assert neg["verdict"] == "refuted" and neg["reason_code"] == "access_denied"
    control = api("GET", f"/arenas/{replacement}/validation-evidence/{neg['control_digest']}")
    assert control["evidence"]["data"]["control_ok"] is True
    unsupported = finding(replacement)
    uns = validation(replacement, unsupported["finding_id"])
    assert uns["verdict"] == "inconclusive" and uns["reason_code"] == "missing_action"
    score = api("GET", f"/arenas/{replacement}/score")
    assert score["confirmed_points"] == 0 and score["score"]["value"] == 0
    assert not score["score"]["metadata"]["solved"]
    console(replacement, "access_denied")

    failed = api("POST", "/deploy", {"scenario": "nv06-authz-fixture",
        "instance_id": "nv06-probe-failure", "provider": "docker-local",
        "engagement_purpose": "calibration", "participant_mode": "agent",
        "engagement_time_box_seconds": 900})["instance_id"]
    ARENAS.append(failed)
    wait(f"/status/{failed}", lambda value: value.get("status") == "active")
    bind(failed)
    prior = action(failed, "/objects/B", "nvfail" + uuid.uuid4().hex)
    target_id = run("docker", "ps", "-q", "--filter", f"label=nidavellir.lab_id={failed}",
                    "--filter", "label=nidavellir.node=target").stdout.strip()
    assert target_id
    run("docker", "stop", target_id)
    failure_finding = finding(failed, prior["transaction_digest"])
    fail_verdict = validation(failed, failure_finding["finding_id"])
    assert fail_verdict["verdict"] == "infrastructure_failure"
    assert api("GET", f"/arenas/{failed}/score")["confirmed_points"] == 0

    api("DELETE", f"/destroy/{replacement}", expected=(200, 202))
    api("DELETE", f"/destroy/{failed}", expected=(200, 202))
    for arena in ARENAS:
        wait(f"/status/{arena}", lambda value: value.get("status") == "destroyed")
    retained = api("GET", f"/arenas/{source}/validation-evidence/{pos['observation_digest']}")
    assert retained["digest"] == pos["observation_digest"]
    assert api("GET", f"/arenas/{source}/http/transactions/{positive_action['transaction_digest']}")
    assert api("GET", f"/arenas/{source}/score")["score"]["value"] == 1.0
    console(source, "unauthorized_read")
    resources = {arena: inventory(arena) for arena in ARENAS}
    assert not any(any(counts.values()) for counts in resources.values()), resources
    evidence = {
        "schema": "nidavellir/nv06-live-evidence/v1", "fixture_image": image_id,
        "recipe_digest": lifecycle["recipe"]["recipe_digest"],
        "observed_state_digest": lifecycle["observation"]["observed_state_digest"],
        "positive": {"arena": source, "finding_id": positive_finding["finding_id"],
                     "verdict": pos, "review_link": review_link},
        "negative": {"arena": replacement, "finding_id": negative_finding["finding_id"],
                     "verdict": neg},
        "unsupported": {"finding_id": unsupported["finding_id"], "verdict": uns},
        "probe_failure": {"arena": failed, "finding_id": failure_finding["finding_id"],
                          "verdict": fail_verdict},
        "reset_operation": operation["id"], "final_resources": resources,
    }
    path = ROOT / "docs/verification/nv06-live-2026-09-24.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_arenas()
        run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        leftovers = {arena: inventory(arena) for arena in ARENAS}
        if any(any(value.values()) for value in leftovers.values()):
            raise RuntimeError(f"NV-06 cleanup left labelled resources: {leftovers}")
