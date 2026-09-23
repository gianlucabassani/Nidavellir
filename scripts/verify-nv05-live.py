#!/usr/bin/env python3
"""Isolated Docker-local NV-05 fixed TCP forward and manifest acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.cookiejar
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed


ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", "docker-compose.nv05.yml"]
API = "http://127.0.0.1:18005"
WEB = "http://127.0.0.1:15005"
KEY = "nv05-acceptance-key"
AGENT_KEY = "nv05-agent-key"
ARENAS = []


def run(*args, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stdout[-2500:]} {result.stderr[-2500:]}")
    return result


def api(method, path, body=None, *, key=KEY, expected=(200,)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "X-API-Key": key, **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310 - local fixture
            result = json.loads(response.read() or b"{}")
            assert response.status in expected, (method, path, result)
            return result
    except urllib.error.HTTPError as exc:
        result = {"http_status": exc.code, "body": exc.read().decode("utf-8", "replace")}
        if exc.code not in expected:
            raise RuntimeError(f"{method} {path}: {result}") from exc
        return result


def wait(path, predicate, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = api("GET", path)
            if predicate(last):
                return last
        except (OSError, RuntimeError) as exc:
            last = str(exc)
        time.sleep(.25)
    raise RuntimeError(f"timed out waiting for {path}: {last}")


def owned(forward_id=None, arena_id=None):
    label = (f"nidavellir.forward_id={forward_id}" if forward_id else
             f"nidavellir.lab_id={arena_id}")
    return len(run("docker", "ps", "-a", "-q", "--filter", f"label={label}").stdout.split())


def inventory(arena_id):
    label = f"nidavellir.lab_id={arena_id}"
    return {kind: len(run("docker", *command, "-q", "--filter",
                          f"label={label}").stdout.split())
            for kind, command in {
                "containers": ("ps", "-a"),
                "networks": ("network", "ls"),
                "volumes": ("volume", "ls"),
            }.items()}


def cleanup_arenas():
    """Reclaim this invocation's arenas even when an assertion aborts the gate."""
    for arena in ARENAS:
        try:
            if api("GET", f"/status/{arena}").get("status") != "destroyed":
                api("DELETE", f"/destroy/{arena}", expected=(200, 202))
                wait(f"/status/{arena}",
                     lambda value: value.get("status") == "destroyed", 30)
        except (OSError, RuntimeError, urllib.error.HTTPError):
            pass
        label = f"label=nidavellir.lab_id={arena}"
        containers = run("docker", "ps", "-a", "-q", "--filter", label,
                         check=False).stdout.split()
        if containers:
            run("docker", "rm", "-f", *containers, check=False)
        networks = run("docker", "network", "ls", "-q", "--filter", label,
                       check=False).stdout.split()
        if networks:
            run("docker", "network", "rm", *networks, check=False)
        volumes = run("docker", "volume", "ls", "-q", "--filter", label,
                      check=False).stdout.split()
        if volumes:
            run("docker", "volume", "rm", *volumes, check=False)


def uri(arena, forward_id):
    return f"ws://127.0.0.1:18005/arenas/{arena}/forwards/{forward_id}/connect"


def echo_over_forward(arena, forward_id, *, key=AGENT_KEY):
    with connect(uri(arena, forward_id), additional_headers={"X-API-Key": key},
                 open_timeout=15, close_timeout=2) as stream:
        stream.send(b"hello")
        response = stream.recv(timeout=10)
        assert response == b"NV05:hello", response
    return response


def loopback_client(arena, forward_id):
    command = ["python3", "scripts/nv-forward-client.py", "--arena", arena,
               "--forward", forward_id, "--listen-port", "18080",
               "--api-url", API]
    process = subprocess.Popen(command, cwd=ROOT, env={
        **os.environ, "NIDAVELLIR_API_KEY": AGENT_KEY},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"loopback client exited: {process.stderr.read()}")
            try:
                with socket.create_connection(("127.0.0.1", 18080), timeout=1) as conn:
                    conn.sendall(b"loopback")
                    conn.settimeout(10)
                    assert conn.recv(16384) == b"NV05:loopback"
                    return
            except OSError:
                time.sleep(.1)
        raise RuntimeError("loopback client did not accept a connection")
    finally:
        process.terminate()
        process.wait(timeout=5)


def console(arena):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = opener.open(WEB + "/login", timeout=10).read().decode()  # nosec B310
    csrf = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page).group(1)
    opener.open(urllib.request.Request(WEB + "/login", data=urllib.parse.urlencode({
        "username": "admin", "password": "nv05-local-only", "csrf_token": csrf,
    }).encode()), timeout=10)  # nosec B310
    page = opener.open(WEB + f"/arena/{arena}", timeout=10).read().decode()  # nosec B310
    assert "Runtime capabilities" in page and "internal" in page
    csrf = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page).group(1)
    form = urllib.parse.urlencode({"csrf_token": csrf, "foothold": "jump",
                                   "service": "fixture:internal"}).encode()
    try:
        opener.open(urllib.request.Request(WEB + f"/arena/{arena}/forwards",
                                          data=urllib.parse.urlencode({
                                              "foothold": "jump", "service": "fixture:internal",
                                          }).encode()), timeout=15)  # nosec B310
    except urllib.error.HTTPError as exc:
        assert exc.code == 400, exc.code
    else:
        raise AssertionError("console forward creation accepted missing CSRF token")
    opener.open(urllib.request.Request(WEB + f"/arena/{arena}/forwards", data=form),
                timeout=15)  # nosec B310
    opened = api("GET", f"/arenas/{arena}/forwards")["forwards"][0]
    assert opened["state"] == "open"
    form = urllib.parse.urlencode({"csrf_token": csrf}).encode()
    opener.open(urllib.request.Request(
        WEB + f"/arena/{arena}/forwards/{opened['id']}/revoke", data=form),
        timeout=15)  # nosec B310
    assert api("GET", f"/arenas/{arena}/forwards/{opened['id']}")["state"] == "revoked"
    return opened["id"]


MCP_PROGRAM = r'''
import anyio, json, os, uuid
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    arena = os.environ["NV05_ARENA"]
    async with streamablehttp_client("http://127.0.0.1:9000/mcp") as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            async def call(name, arguments):
                result = await session.call_tool(name, arguments=arguments)
                assert not result.isError, (name, result)
                return result.structuredContent or json.loads(next(
                    item.text for item in result.content if item.type == "text"))
            manifest = await call("runtime_capabilities", {"arena_id": arena})
            assert manifest["operations"]["forward"]["state"] == "ready"
            lease = await call("open_forward", {
                "arena_id": arena, "foothold": "jump", "target": "fixture",
                "service_id": "internal", "idempotency_key": uuid.uuid4().hex})
            status = await call("forward_status", {"arena_id": arena,
                                                    "forward_id": lease["id"]})
            assert status["state"] == "open"
            revoked = await call("revoke_forward", {"arena_id": arena,
                                                    "forward_id": lease["id"]})
            assert revoked["state"] == "revoked"
            print("NV05_MCP=" + json.dumps({"manifest": manifest["schema"],
                                           "forward_id": lease["id"]}))
anyio.run(main)
'''


def mcp_surface(arena):
    output = run(*COMPOSE, "exec", "-T", "-e", f"NV05_ARENA={arena}",
                 "agent-gateway", "python", "-c", MCP_PROGRAM).stdout
    return json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                           if line.startswith("NV05_MCP=")))


def main():
    run("docker", "build", "-t", "nidavellir/nv05-fixture:acceptance",
        "cyber-range/fixtures/nv05-internal")
    fixture_id = run("docker", "image", "inspect", "nidavellir/nv05-fixture:acceptance",
                     "--format", "{{.Id}}").stdout.strip()
    run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    run(*COMPOSE, "up", "-d", "--build", "poc-runner-image", "postgres", "redis",
        "orchestrator", "worker", "beat", "webui", "agent-gateway")
    wait("/health", lambda value: value.get("status") == "ok")
    scenario = {
        "schema": "nidavellir/v3", "name": "NV-05 internal fixture",
        "requires": {"provider_class": "container", "egress": "none", "mirror": "off"},
        "network": {"segments": [{"name": "research"}, {"name": "private"}]},
        "nodes": [
            {"name": "jump", "role": "attacker", "entrypoint": True,
             "image": fixture_id, "command": "sleep infinity", "segments": ["research"]},
            {"name": "fixture", "role": "victim", "image": fixture_id,
             "segments": ["research", "private"], "ports": [],
             "forward_services": [{"id": "internal", "port": 8123}]},
            {"name": "peer", "role": "victim", "image": fixture_id,
             "segments": ["private"], "ports": [],
             "forward_services": [{"id": "peer", "port": 8123}]},
        ],
        "lifecycle": {"readiness": {"type": "http", "node": "fixture", "port": 8080,
                                    "path": "/health", "expected_status": 200,
                                    "timeout_seconds": 20}},
    }
    api("POST", "/scenarios", {"id": "nv05-fixture", "spec": scenario})
    for name in ("nv05-main", "nv05-other"):
        dep = api("POST", "/deploy", {"scenario": "nv05-fixture", "instance_id": name,
                                      "provider": "docker-local",
                                      "engagement_time_box_seconds": 1200})
        arena = dep["instance_id"]
        ARENAS.append(arena)
        wait(f"/status/{arena}", lambda value: value.get("status") == "active", 120)
    main_arena, other_arena = ARENAS
    register = ("from database import Database; from auth import hash_api_key; "
                "Database().create_api_key(hash_api_key('nv05-agent-key'),'nv05-agent','agent')")
    run(*COMPOSE, "exec", "-T", "orchestrator", "python", "-c", register)
    api("POST", f"/arenas/{main_arena}/bindings", {"agent_name": "nv05-agent",
                                                 "stance": "attacker"})
    second_key = "nv05-second-agent-key"
    second_register = ("from database import Database; from auth import hash_api_key; "
                       "Database().create_api_key(hash_api_key('nv05-second-agent-key'),"
                       "'nv05-second','agent')")
    run(*COMPOSE, "exec", "-T", "orchestrator", "python", "-c", second_register)
    api("POST", f"/arenas/{main_arena}/bindings", {"agent_name": "nv05-second",
                                                 "stance": "defender"})
    api("POST", "/scenarios", {"id": "nv05-mock-fixture", "spec": {
        **scenario, "name": "NV-05 mock capability fixture", "lifecycle": {}}})
    mock = api("POST", "/deploy", {"scenario": "nv05-mock-fixture",
                                     "instance_id": "nv05-mock", "provider": "mock",
                                     "engagement_time_box_seconds": 1200})["instance_id"]
    ARENAS.append(mock)
    wait(f"/status/{mock}", lambda value: value.get("status") == "active", 30)
    mock_manifest = api("GET", f"/arenas/{mock}/capabilities")
    assert mock_manifest["operations"]["forward"]["state"] == "unsupported"
    manifest = api("GET", f"/arenas/{main_arena}/capabilities", key=AGENT_KEY)
    assert manifest["operations"]["forward"]["state"] == "ready", manifest
    assert manifest["operations"]["token_cost_hard_cap"]["state"] == "unsupported"
    assert api("GET", f"/arenas/{other_arena}/capabilities", key=AGENT_KEY,
               expected=(403,))["http_status"] == 403
    assert "vulnerabilities" not in json.dumps(manifest)
    denied_manifest = api("GET", f"/arenas/{main_arena}/capabilities", key=second_key)
    assert denied_manifest["operations"]["forward"]["state"] == "unavailable"
    assert all(not target["forward_services"] for target in denied_manifest["targets"])
    mcp = mcp_surface(main_arena)
    assert mcp["manifest"] == manifest["schema"]
    base = {"foothold": "jump", "target": "fixture", "service_id": "internal",
            "lifetime_seconds": 30}
    for extra in ({"host": "127.0.0.1"}, {"host": "169.254.169.254"},
                  {"host": "8.8.8.8"}, {"host": "host.docker.internal"},
                  {"host": other_arena}, {"port": 8123},
                  {"target": "peer", "service_id": "peer"},
                  {"target": "fixture", "service_id": "other"}):
        assert api("POST", f"/arenas/{main_arena}/forwards", {
            **base, **extra, "idempotency_key": uuid.uuid4().hex},
            key=AGENT_KEY, expected=(422,))["http_status"] == 422
    assert api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex}, key=second_key,
        expected=(403,))["http_status"] == 403
    lease = api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex}, key=AGENT_KEY)
    forward_id = lease["id"]
    response = echo_over_forward(main_arena, forward_id)
    wait(f"/arenas/{main_arena}/forwards/{forward_id}",
         lambda value: value["cleanup_state"] == "complete")
    assert owned(forward_id=forward_id) == 0
    loopback_id = api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex}, key=AGENT_KEY)["id"]
    loopback_client(main_arena, loopback_id)
    wait(f"/arenas/{main_arena}/forwards/{loopback_id}",
         lambda value: value["cleanup_state"] == "complete")

    def new_lease(seconds=30):
        return api("POST", f"/arenas/{main_arena}/forwards", {
            **base, "lifetime_seconds": seconds,
            "idempotency_key": uuid.uuid4().hex}, key=AGENT_KEY)["id"]

    revoked_id = new_lease()
    with connect(uri(main_arena, revoked_id),
                 additional_headers={"X-API-Key": AGENT_KEY}, open_timeout=15) as stream:
        stream.send(b"revoke")
        assert stream.recv(timeout=10) == b"NV05:revoke"
        started = time.monotonic()
        api("POST", f"/arenas/{main_arena}/forwards/{revoked_id}/revoke", {})
        try:
            stream.recv(timeout=5)
        except ConnectionClosed:
            pass
        else:
            raise AssertionError("revoked stream remained open")
        revoke_seconds = time.monotonic() - started
        assert revoke_seconds < 5, revoke_seconds
    wait(f"/arenas/{main_arena}/forwards/{revoked_id}",
         lambda value: value["cleanup_state"] == "complete")
    assert owned(forward_id=revoked_id) == 0

    expired_id = new_lease(10)
    with connect(uri(main_arena, expired_id),
                 additional_headers={"X-API-Key": AGENT_KEY}, open_timeout=15) as stream:
        stream.send(b"expiry")
        assert stream.recv(timeout=10) == b"NV05:expiry"
        try:
            stream.recv(timeout=13)
        except ConnectionClosed:
            pass
        else:
            raise AssertionError("expired stream remained open")
    assert api("GET", f"/arenas/{main_arena}/forwards/{expired_id}")["state"] != "open"
    try:
        with connect(uri(main_arena, expired_id),
                     additional_headers={"X-API-Key": AGENT_KEY}, open_timeout=5):
            raise AssertionError("expired lease reconnected")
    except AssertionError:
        raise
    except Exception:
        pass  # the server rejected the pre-upgrade claim
    wait(f"/arenas/{main_arena}/forwards/{expired_id}",
         lambda value: value["cleanup_state"] == "complete")
    assert owned(forward_id=expired_id) == 0

    interrupted_id = new_lease()
    with connect(uri(main_arena, interrupted_id),
                 additional_headers={"X-API-Key": AGENT_KEY}, open_timeout=15) as stream:
        stream.send(b"worker")
        assert stream.recv(timeout=10) == b"NV05:worker"
        assert owned(forward_id=interrupted_id) == 1
        run(*COMPOSE, "kill", "worker")
        run(*COMPOSE, "up", "-d", "worker", "beat")
        try:
            stream.recv(timeout=15)
        except ConnectionClosed:
            pass
        else:
            raise AssertionError("worker-loss stream remained open")
    wait(f"/arenas/{main_arena}/forwards/{interrupted_id}",
         lambda value: value["cleanup_state"] == "complete", 45)
    assert owned(forward_id=interrupted_id) == 0
    run(*COMPOSE, "restart", "orchestrator", "agent-gateway")
    wait("/health", lambda value: value.get("status") == "ok", 30)
    assert mcp_surface(main_arena)["manifest"] == manifest["schema"]

    console_forward = console(main_arena)
    assert owned(forward_id=console_forward) == 0
    # Stop and binding controls make both creation and connection fail closed.
    api("POST", f"/arenas/{main_arena}/bindings/nv05-agent/pause", {})
    assert api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex}, key=AGENT_KEY,
        expected=(423,))["http_status"] == 423
    api("POST", f"/arenas/{main_arena}/bindings/nv05-agent/resume", {})
    stopping_id = new_lease()
    with connect(uri(main_arena, stopping_id),
                 additional_headers={"X-API-Key": AGENT_KEY}, open_timeout=15) as stream:
        stream.send(b"stop")
        assert stream.recv(timeout=10) == b"NV05:stop"
        stop = api("POST", f"/arenas/{main_arena}/stop", {
            "reason": "NV05 stop", "idempotency_key": uuid.uuid4().hex})
        try:
            stream.recv(timeout=5)
        except ConnectionClosed:
            pass
        else:
            raise AssertionError("stopped stream remained open")
    wait(f"/arenas/{main_arena}/forwards/{stopping_id}",
         lambda value: value["cleanup_state"] == "complete")
    assert owned(forward_id=stopping_id) == 0
    assert stop["status"]["arena"]["state"] in {"stopping", "stopped"}
    assert api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex}, key=AGENT_KEY,
        expected=(423,))["http_status"] == 423
    wait(f"/arenas/{main_arena}/budget",
         lambda value: value["arena"]["state"] == "stopped", 30)
    api("POST", f"/arenas/{main_arena}/resume", {
        "reason": "NV05 verified", "idempotency_key": uuid.uuid4().hex})
    with ThreadPoolExecutor(max_workers=2) as pool:
        racing_lease = new_lease()
        connect_future = pool.submit(echo_over_forward, main_arena, racing_lease)
        stop_future = pool.submit(api, "POST", f"/arenas/{main_arena}/stop", {
            "reason": "NV05 stream race", "idempotency_key": uuid.uuid4().hex})
        stop_future.result()
        try:
            connect_future.result()
        except Exception:
            pass  # a stop may win before stream admission
    wait(f"/arenas/{main_arena}/budget",
         lambda value: value["arena"]["state"] == "stopped", 30)
    wait(f"/arenas/{main_arena}/forwards/{racing_lease}",
         lambda value: value["state"] in {"revoked", "closed"} and
         value["cleanup_state"] == "complete", 30)
    assert owned(forward_id=racing_lease) == 0
    api("POST", f"/arenas/{main_arena}/resume", {
        "reason": "NV05 race verified", "idempotency_key": uuid.uuid4().hex})

    binding_id = new_lease()
    with connect(uri(main_arena, binding_id),
                 additional_headers={"X-API-Key": AGENT_KEY}, open_timeout=15) as stream:
        stream.send(b"binding")
        assert stream.recv(timeout=10) == b"NV05:binding"
        api("DELETE", f"/arenas/{main_arena}/bindings/nv05-agent")
        try:
            stream.recv(timeout=5)
        except ConnectionClosed:
            pass
        else:
            raise AssertionError("revoked binding left stream open")
    wait(f"/arenas/{main_arena}/forwards/{binding_id}",
         lambda value: value["cleanup_state"] == "complete")
    assert api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex}, key=AGENT_KEY,
        expected=(403,))["http_status"] == 403

    system_id = api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex})["id"]
    with connect(uri(main_arena, system_id),
                 additional_headers={"X-API-Key": KEY}, open_timeout=15) as stream:
        stream.send(b"system")
        assert stream.recv(timeout=10) == b"NV05:system"
        api("POST", "/system/emergency-stop", {
            "reason": "NV05 system stop", "idempotency_key": uuid.uuid4().hex})
        try:
            stream.recv(timeout=5)
        except ConnectionClosed:
            pass
        else:
            raise AssertionError("system stop left stream open")
    wait(f"/arenas/{main_arena}/forwards/{system_id}",
         lambda value: value["cleanup_state"] == "complete")
    run(*COMPOSE, "restart", "orchestrator", "agent-gateway")
    wait("/health", lambda value: value.get("status") == "ok", 30)
    wait("/system/emergency-stop", lambda value: value["state"] == "stopped", 30)
    api("POST", "/system/emergency-stop/clear", {
        "reason": "NV05 system cleanup verified", "idempotency_key": uuid.uuid4().hex})

    reset_lease = api("POST", f"/arenas/{main_arena}/forwards", {
        **base, "idempotency_key": uuid.uuid4().hex})["id"]
    reset = api("POST", f"/arenas/{main_arena}/reset", {
        "idempotency_key": uuid.uuid4().hex}, expected=(202,))
    replacement = reset["replacement_id"]
    ARENAS.append(replacement)
    reset_result = wait(f"/reset-operations/{reset['operation_id']}",
                        lambda value: value["status"] in {"succeeded", "failed"}, 120)
    assert reset_result["status"] == "succeeded", reset_result
    assert api("GET", f"/arenas/{main_arena}/forwards/{reset_lease}")["state"] == "revoked"
    assert owned(forward_id=reset_lease) == 0
    assert api("GET", f"/arenas/{replacement}/forwards")["forwards"] == []
    for arena in ARENAS:
        if api("GET", f"/status/{arena}").get("status") != "destroyed":
            api("DELETE", f"/destroy/{arena}", expected=(200, 202))
            wait(f"/status/{arena}", lambda value: value.get("status") == "destroyed", 90)
    final_inventory = {arena: inventory(arena) for arena in ARENAS}
    assert all(not any(resources.values()) for resources in final_inventory.values()), final_inventory
    evidence = {"schema": "nidavellir/nv05-live/v1",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "docker_server": run("docker", "version", "--format",
                                     "{{.Server.Version}}").stdout.strip(),
                "fixture_image": fixture_id, "arenas": ARENAS,
                "forward_id": forward_id, "response_bytes": len(response),
                "revoke_seconds": revoke_seconds,
                "expired_forward_id": expired_id,
                "interrupted_forward_id": interrupted_id,
                "stopped_forward_id": stopping_id,
                "racing_forward_id": racing_lease,
                "reset_lease_id": reset_lease,
                "console_forward_id": console_forward,
                "mcp_forward_id": mcp["forward_id"],
                "loopback_forward_id": loopback_id,
                "binding_revoked_forward_id": binding_id,
                "system_stopped_forward_id": system_id,
                "mock_provider_unsupported": True,
                "denied_dynamic_destinations": True,
                "final_resources": final_inventory}
    destination = ROOT / "docs" / "verification" / f"nv05-live-{datetime.now():%Y-%m-%d}.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_arenas()
        run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
