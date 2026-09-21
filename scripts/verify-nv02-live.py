#!/usr/bin/env python3
"""Isolated live Docker acceptance for NV-02.

This script owns only the ``docker-compose.nv02.yml`` project and resources
labelled with the arena UUIDs it creates. It never prunes the daemon.
"""
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
COMPOSE = ["docker", "compose", "-f", "docker-compose.nv02.yml"]
API = "http://127.0.0.1:18000"
WEB = "http://127.0.0.1:15000"
HEADERS = {"X-API-Key": "nv02-acceptance-key"}
CREATED_ARENAS: list[str] = []


def run(*args, check=True):
    return subprocess.run(
        [*args], cwd=ROOT, check=check, text=True, capture_output=True
    )


def api(method, path, payload=None, expected=(200,)):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={**HEADERS, **({"Content-Type": "application/json"} if data else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310 - fixed local base URL
            body = json.loads(response.read() or b"{}")
            if response.status not in expected:
                raise RuntimeError(f"{method} {path}: HTTP {response.status}: {body}")
            return body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {body}") from exc


def wait_for(path, predicate, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = api("GET", path)
            if predicate(last):
                return last
        except (OSError, RuntimeError):
            pass
        time.sleep(1)
    raise RuntimeError(f"timed out waiting for {path}; last={last}")


def status(arena_id, wanted=("active",), timeout=90):
    return wait_for(
        f"/status/{arena_id}", lambda value: value.get("status") in wanted, timeout
    )


def reset(arena_id, suffix):
    response = api(
        "POST", f"/arenas/{arena_id}/reset",
        {"idempotency_key": f"nv02-{suffix}-{uuid.uuid4()}"}, expected=(202,),
    )
    replacement = response["replacement_id"]
    CREATED_ARENAS.append(replacement)
    operation = wait_for(
        f"/reset-operations/{response['operation_id']}",
        lambda value: value.get("status") in ("succeeded", "failed"),
        120,
    )
    if operation["status"] != "succeeded":
        raise RuntimeError(f"reset failed: {operation}")
    status(replacement)
    return replacement, operation


def console(arena_id):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = opener.open(WEB + "/login", timeout=10).read().decode()  # nosec B310 - fixed local URL
    token = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', login)
    if not token:
        raise RuntimeError("console login did not expose a CSRF token")
    body = urllib.parse.urlencode({
        "username": "admin", "password": "nv02-local-only",
        "csrf_token": token.group(1),
    }).encode()
    opener.open(urllib.request.Request(WEB + "/login", data=body), timeout=10)  # nosec B310 - fixed local URL
    page = opener.open(WEB + f"/arena/{arena_id}", timeout=10).read().decode()  # nosec B310 - fixed local URL
    return opener, page


def assert_console_record(arena_id):
    _, page = console(arena_id)
    if "Observed baseline" not in page or "Reset" not in page:
        raise RuntimeError("console lifecycle surface was not rendered")


def reset_via_console(arena_id):
    opener, page = console(arena_id)
    token = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page)
    if not token:
        raise RuntimeError("arena reset form did not expose a CSRF token")
    body = urllib.parse.urlencode({"csrf_token": token.group(1)}).encode()
    opener.open(
        urllib.request.Request(WEB + f"/reset/{arena_id}", data=body), timeout=20
    )  # nosec B310 - fixed local URL
    lifecycle = wait_for(
        f"/arenas/{arena_id}/lifecycle", lambda value: bool(value.get("resets")), 30
    )
    operation_id = lifecycle["resets"][0]["id"]
    operation = wait_for(
        f"/reset-operations/{operation_id}",
        lambda value: value.get("status") in ("succeeded", "failed"),
        120,
    )
    if operation["status"] != "succeeded":
        raise RuntimeError(f"console reset failed: {operation}")
    replacement = operation["replacement_id"]
    CREATED_ARENAS.append(replacement)
    status(replacement)
    return replacement, operation


def owned_resource_count(arena_id):
    filters = [f"label=nidavellir.lab_id={arena_id}"]
    counts = {}
    for kind, command in {
        "containers": ["docker", "ps", "-aq", "--filter", filters[0]],
        "networks": ["docker", "network", "ls", "-q", "--filter", filters[0]],
        "volumes": ["docker", "volume", "ls", "-q", "--filter", filters[0]],
        "images": ["docker", "image", "ls", "-q", "--filter", filters[0]],
    }.items():
        counts[kind] = len([line for line in run(*command).stdout.splitlines() if line])
    return counts


def main():
    run("docker", "build", "-t", "nidavellir/nv02-reset:acceptance",
        "cyber-range/fixtures/nv02-reset")
    image_id = run(
        "docker", "image", "inspect", "nidavellir/nv02-reset:acceptance",
        "--format", "{{.Id}}",
    ).stdout.strip()
    if not image_id.startswith("sha256:"):
        raise RuntimeError(f"fixture image was not content-addressed: {image_id}")

    run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    # Beat is intentionally held back until the interruption phase because this
    # fixture uses a zero-minute stuck threshold to exercise immediate recovery.
    run(
        *COMPOSE, "up", "-d", "--build",
        "postgres", "redis", "orchestrator", "worker", "webui",
    )
    wait_for("/health", lambda value: value.get("status") == "ok", 120)

    scenario = {
        "schema": "nidavellir/v3",
        "name": "NV-02 reset fixture",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{
            "name": "target", "role": "victim", "image": image_id,
            "segments": ["lab"], "ports": [8080],
        }],
        "lifecycle": {
            "seed": {"schema": "nidavellir/nv02-seed/v1", "value": 0},
            "readiness": {
                "type": "http", "node": "target", "port": 8080,
                "path": "/state", "expected_status": 200,
                "expected_state": {"seed": "baseline", "value": 0},
                "timeout_seconds": 20, "interval_seconds": 1,
            },
        },
    }
    api("POST", "/scenarios", {"id": "nv02-reset-fixture", "spec": scenario})
    deployment = api("POST", "/deploy", {
        "scenario": "nv02-reset-fixture", "instance_id": "nv02-live",
        "provider": "docker-local", "engagement_purpose": "calibration",
        "participant_mode": "operator", "engagement_time_box_seconds": 900,
    })
    source = deployment["instance_id"]
    CREATED_ARENAS.append(source)
    status(source)
    lifecycle = api("GET", f"/arenas/{source}/lifecycle")
    assert lifecycle["classification"]["runtime_reset"]["status"] == "eligible"
    baseline_digest = lifecycle["observation"]["observed_state_digest"]
    assert_console_record(source)

    mutation = api("POST", f"/arenas/{source}/http/request", {
        "node": "target", "method": "POST", "path": "/mutate",
    })
    assert '"value":1' in mutation["body"]
    transaction_digest = mutation["transaction_digest"]
    finding = api("POST", f"/arenas/{source}/findings/manual", {
        "title": "NV-02 retained mutation evidence", "node": "target",
        "evidence": "Synthetic reset acceptance only",
        "transaction_digests": [transaction_digest],
    })

    second, first_reset = reset_via_console(source)
    assert status(source, ("destroyed",))["status"] == "destroyed"
    state = api("POST", f"/arenas/{second}/http/request", {
        "node": "target", "method": "GET", "path": "/state",
    })
    assert '"value":0' in state["body"]
    second_lifecycle = api("GET", f"/arenas/{second}/lifecycle")
    assert second_lifecycle["observation"]["observed_state_digest"] == baseline_digest

    third, second_reset = reset(second, "second")
    assert api("GET", f"/arenas/{source}/http/transactions/{transaction_digest}")
    source_events = api("GET", f"/deployments/{source}/events")["events"]
    assert any(
        event.get("type") == "finding"
        and (event.get("payload") or {}).get("finding_id") == finding["finding_id"]
        for event in source_events
    )
    assert api("GET", f"/arenas/{third}/bindings") == {"bindings": []}
    assert_console_record(source)

    # Real worker interruption: kill the process after a deploy is claimed.
    slow = json.loads(json.dumps(scenario))
    slow["name"] = "NV-02 interrupted fixture"
    slow["lifecycle"]["readiness"]["expected_state"] = {"never": "matches"}
    slow["lifecycle"]["readiness"]["timeout_seconds"] = 60
    api("POST", "/scenarios", {"id": "nv02-interrupted", "spec": slow})
    interrupted = api("POST", "/deploy", {
        "scenario": "nv02-interrupted", "instance_id": "nv02-interrupted",
        "provider": "docker-local", "engagement_time_box_seconds": 900,
    })["instance_id"]
    CREATED_ARENAS.append(interrupted)
    status(interrupted, ("deploying",), 30)
    run(*COMPOSE, "kill", "worker")
    run(*COMPOSE, "up", "-d", "worker", "beat")
    status(interrupted, ("destroyed", "failed", "error_destroying"), 120)
    remaining_interrupted = owned_resource_count(interrupted)
    if any(remaining_interrupted.values()):
        raise RuntimeError(f"interrupted deploy leaked resources: {remaining_interrupted}")

    # Lost teardown delivery/restart: stop the worker before enqueue, then let the
    # broker plus reaper reconcile the durable `destroying` record after restart.
    run(*COMPOSE, "stop", "beat")
    teardown = api("POST", "/deploy", {
        "scenario": "nv02-reset-fixture", "instance_id": "nv02-teardown-interrupted",
        "provider": "docker-local", "engagement_time_box_seconds": 900,
    })["instance_id"]
    CREATED_ARENAS.append(teardown)
    status(teardown)
    run(*COMPOSE, "stop", "worker")
    api("DELETE", f"/destroy/{teardown}")
    assert status(teardown, ("destroying",), 10)["status"] == "destroying"
    run(*COMPOSE, "up", "-d", "worker", "beat")
    status(teardown, ("destroyed",), 120)
    remaining_teardown = owned_resource_count(teardown)
    if any(remaining_teardown.values()):
        raise RuntimeError(f"interrupted teardown leaked resources: {remaining_teardown}")

    # Tear down the final live replacement through the real worker and verify
    # that the provider reports no arena-labelled resources.
    api("DELETE", f"/destroy/{third}")
    status(third, ("destroyed",), 90)
    final_resources = {arena: owned_resource_count(arena) for arena in CREATED_ARENAS}
    if any(any(counts.values()) for counts in final_resources.values()):
        raise RuntimeError(f"owned resources remain: {final_resources}")

    result = {
        "fixture_image": image_id,
        "arenas": CREATED_ARENAS,
        "recipe_digest": lifecycle["recipe"]["recipe_digest"],
        "observed_state_digest": baseline_digest,
        "transaction_digest": transaction_digest,
        "finding_id": finding["finding_id"],
        "reset_operations": [first_reset["id"], second_reset["id"]],
        "interrupted_deploy_terminal_state": status(
            interrupted, ("destroyed", "failed", "error_destroying")
        )["status"],
        "interrupted_teardown_terminal_state": status(teardown, ("destroyed",))["status"],
        "final_resources": final_resources,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    finally:
        run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
