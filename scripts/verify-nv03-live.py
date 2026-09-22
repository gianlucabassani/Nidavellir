#!/usr/bin/env python3
"""Isolated Docker-local acceptance for NV-03 confined PoC execution."""
from __future__ import annotations

import base64
import hashlib
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
COMPOSE = ["docker", "compose", "-f", "docker-compose.nv03.yml"]
API = "http://127.0.0.1:18003"
WEB = "http://127.0.0.1:15003"
HEADERS = {"X-API-Key": "nv03-acceptance-key"}
TERMINAL = {"succeeded", "failed", "timed_out", "cancelled"}
ARENAS: list[str] = []


def run(*args, check=True):
    result = subprocess.run(
        [*args], cwd=ROOT, check=False, text=True, capture_output=True
    )
    if check and result.returncode:
        raise RuntimeError(
            f"acceptance subprocess failed ({result.returncode}): "
            f"{result.stdout[-8000:]}\n{result.stderr[-8000:]}"
        )
    return result


def api(method, path, payload=None, expected=(200,)):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        API + path, data=data, method=method,
        headers={**HEADERS, **({"Content-Type": "application/json"} if data else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            body = json.loads(response.read() or b"{}")
            if response.status not in expected:
                raise RuntimeError(f"{method} {path}: HTTP {response.status}: {body}")
            return body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code in expected:
            return {"http_status": exc.code, "body": body}
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {body}") from exc


def wait_for(path, predicate, timeout=120):
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        try:
            last = api("GET", path)
            if predicate(last):
                return last
        except (OSError, RuntimeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {path}; last={last}")


def wait_arena(arena_id, wanted=("active",), timeout=120):
    return wait_for(
        f"/status/{arena_id}", lambda value: value.get("status") in wanted, timeout
    )


def wait_job(arena_id, job_id, timeout=120):
    return wait_for(
        f"/arenas/{arena_id}/poc-jobs/{job_id}",
        lambda value: (value.get("job") or {}).get("state") in TERMINAL,
        timeout,
    )["job"]


def wait_helper(job_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if owned(job_id=job_id)["containers"]:
            return
        time.sleep(0.1)
    raise RuntimeError(f"no live helper appeared for {job_id}")


def submit(arena_id, source, *, target="selected", timeout=6, key=None):
    response = api("POST", f"/arenas/{arena_id}/poc-jobs", {
        "source": source, "target_node": target, "timeout_seconds": timeout,
        "memory_mb": 64, "cpu_millis": 250, "pids": 16,
        "idempotency_key": key or f"nv03-{uuid.uuid4().hex}",
    }, expected=(202,))
    return response["job"]


def output(arena_id, node, path="/state", **extra):
    return api("POST", f"/arenas/{arena_id}/http/request", {
        "node": node, "method": "GET", "path": path, **extra,
    })


def owned(arena_id=None, job_id=None):
    label = (
        f"nidavellir.poc_job={job_id}" if job_id
        else f"nidavellir.lab_id={arena_id}"
    )
    result = {}
    for kind, command in {
        "containers": ["docker", "ps", "-aq", "--filter", f"label={label}"],
        "networks": ["docker", "network", "ls", "-q", "--filter", f"label={label}"],
        "volumes": ["docker", "volume", "ls", "-q", "--filter", f"label={label}"],
    }.items():
        result[kind] = len([line for line in run(*command).stdout.splitlines() if line])
    return result


def cleanup_arena_resources(arena_id):
    """Best-effort exact-label cleanup for acceptance failures; never prune."""
    label = f"nidavellir.lab_id={arena_id}"
    containers = run(
        "docker", "ps", "-aq", "--filter", f"label={label}", check=False
    ).stdout.split()
    if containers:
        run("docker", "rm", "-f", *containers, check=False)
    for command in (
        ("docker", "network", "ls", "-q", "--filter", f"label={label}"),
        ("docker", "volume", "ls", "-q", "--filter", f"label={label}"),
    ):
        resources = run(*command, check=False).stdout.split()
        if resources:
            removal = "network" if command[1] == "network" else "volume"
            run("docker", removal, "rm", *resources, check=False)


def login_console():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = opener.open(WEB + "/login", timeout=10).read().decode()  # nosec B310
    token = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page)
    if not token:
        raise RuntimeError("console login CSRF token missing")
    body = urllib.parse.urlencode({
        "username": "admin", "password": "nv03-local-only",
        "csrf_token": token.group(1),
    }).encode()
    opener.open(urllib.request.Request(WEB + "/login", data=body), timeout=10)  # nosec B310
    return opener


def console_submit(arena_id):
    opener = login_console()
    page = opener.open(WEB + f"/arena/{arena_id}", timeout=10).read().decode()  # nosec B310
    if "poc-source" not in page or "Run confined" not in page:
        raise RuntimeError("console PoC authoring surface missing")
    token = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page)
    payload = json.dumps({
        "source": "print('console-poc-ok')\n", "target_node": None,
        "timeout_seconds": 3, "memory_mb": 64, "pids": 16,
        "idempotency_key": f"console-{uuid.uuid4().hex}",
    }).encode()
    request = urllib.request.Request(
        WEB + f"/api/arenas/{arena_id}/poc-jobs", data=payload, method="POST",
        headers={"Content-Type": "application/json", "X-CSRFToken": token.group(1)},
    )
    result = json.loads(opener.open(request, timeout=20).read())  # nosec B310
    cancel_payload = json.dumps({
        "source": "while True: pass\n", "target_node": None, "timeout_seconds": 10,
        "idempotency_key": f"console-cancel-{uuid.uuid4().hex}",
    }).encode()
    second = urllib.request.Request(
        WEB + f"/api/arenas/{arena_id}/poc-jobs", data=cancel_payload, method="POST",
        headers={"Content-Type": "application/json", "X-CSRFToken": token.group(1)},
    )
    cancelled_id = json.loads(opener.open(second, timeout=20).read())["job"]["id"]  # nosec B310
    cancel_url = WEB + f"/api/arenas/{arena_id}/poc-jobs/{cancelled_id}/cancel"
    try:
        opener.open(urllib.request.Request(cancel_url, data=b"{}", method="POST"), timeout=10)  # nosec B310
        raise AssertionError("console cancellation accepted missing CSRF")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    opener.open(urllib.request.Request(  # nosec B310
        cancel_url, data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-CSRFToken": token.group(1)},
    ), timeout=10).read()
    assert wait_job(arena_id, cancelled_id)["state"] == "cancelled"
    return result["job"]["id"]


MCP_PROGRAM = r'''
import anyio, json, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

arena = os.environ["NV03_ARENA"]
other = os.environ["NV03_OTHER"]
foreign = os.environ["NV03_FOREIGN_JOB"]

def value(result):
    assert not result.isError, result
    return result.structuredContent or json.loads(next(
        item.text for item in result.content if item.type == "text"
    ))

async def terminal(session, job_id):
    for _ in range(100):
        status = value(await session.call_tool("poc_status", arguments={
            "arena_id": arena, "job_id": job_id,
        }))["job"]
        if status["state"] not in {"queued", "running"}:
            return value(await session.call_tool("poc_result", arguments={
                "arena_id": arena, "job_id": job_id,
            }))["job"]
        await anyio.sleep(.2)
    raise AssertionError("MCP job did not terminate")

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/mcp") as streams:
        read, write = streams[:2]
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            required = {"submit_poc", "poc_status", "poc_result", "cancel_poc"}
            assert required <= names, (required, names)
            submitted = await session.call_tool("submit_poc", arguments={
                "arena_id": arena, "source": "print('mcp-poc-ok')\n",
                "target_node": None, "timeout_seconds": 3,
                "idempotency_key": "nv03-mcp-live-job",
            })
            assert not submitted.isError, submitted
            data = submitted.structuredContent
            if data is None:
                data = json.loads(next(item.text for item in submitted.content if item.type == "text"))
            job_id = (data.get("job") or {}).get("id")
            assert job_id, submitted
            finished = await terminal(session, job_id)
            assert finished["state"] == "succeeded", finished
            assert "mcp-poc-ok" in finished["result"]["stdout"]
            cancellation = value(await session.call_tool("submit_poc", arguments={
                "arena_id": arena, "source": "while True: pass\n",
                "timeout_seconds": 10, "idempotency_key": "nv03-mcp-cancel-job",
            }))["job"]["id"]
            value(await session.call_tool("cancel_poc", arguments={
                "arena_id": arena, "job_id": cancellation,
            }))
            assert (await terminal(session, cancellation))["state"] == "cancelled"
            denied = await session.call_tool("poc_status", arguments={
                "arena_id": other, "job_id": foreign,
            })
            assert denied.isError, denied
            print("NV03_MCP=" + json.dumps({
                "job_id": job_id, "cross_arena_denied": True,
                "status_result_cancel": True,
            }))

anyio.run(main)
'''


def main():
    run("docker", "build", "-t", "nidavellir/nv03-fixture:acceptance",
        "cyber-range/fixtures/nv02-reset")
    fixture_id = run(
        "docker", "image", "inspect", "nidavellir/nv03-fixture:acceptance",
        "--format", "{{.Id}}",
    ).stdout.strip()
    run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    run(*COMPOSE, "up", "-d", "--build", "poc-runner-image", "postgres", "redis",
        "orchestrator", "worker", "beat", "webui", "agent-gateway")
    wait_for("/health", lambda value: value.get("status") == "ok")

    scenario = {
        "schema": "nidavellir/v3", "name": "NV-03 confinement fixture",
        "requires": {"provider_class": "container", "egress": "none", "mirror": "off"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [
            {"name": "selected", "role": "victim", "image": fixture_id,
             "segments": ["lab"], "ports": [8080], "environment": {"NODE_ID": "selected"}},
            {"name": "decoy", "role": "victim", "image": fixture_id,
             "segments": ["lab"], "ports": [8080], "environment": {"NODE_ID": "decoy"}},
            {"name": "foothold", "role": "attacker", "image": fixture_id,
             "segments": ["lab"], "ports": [8080]},
        ],
        "lifecycle": {"readiness": {
            "type": "http", "node": "selected", "port": 8080, "path": "/state",
            "expected_status": 200, "expected_state": {"seed": "baseline", "value": 0},
            "timeout_seconds": 20, "interval_seconds": 1,
        }},
    }
    api("POST", "/scenarios", {"id": "nv03-fixture", "spec": scenario})
    ids = {}
    for arena_name in ("nv03-main", "nv03-other"):
        deployed = api("POST", "/deploy", {
            "scenario": "nv03-fixture", "instance_id": arena_name,
            "provider": "docker-local", "engagement_time_box_seconds": 1200,
        })
        arena_id = deployed["instance_id"]
        ids[arena_name] = arena_id
        ARENAS.append(arena_id)
        state = wait_arena(arena_id)
        if state.get("effective_provider") != "docker-local":
            raise RuntimeError(f"unexpected provider: {state}")

    main_id, other_id = ids["nv03-main"], ids["nv03-other"]
    main_state = api("GET", f"/status/{main_id}")
    other_state = api("GET", f"/status/{other_id}")
    outputs = main_state["outputs"]
    selected_ip = outputs["node_selected_private_ip"]
    decoy_ip = outputs["node_decoy_private_ip"]
    other_ip = other_state["outputs"]["node_selected_private_ip"]
    for arena_id in ARENAS:
        assert "baseline" in output(arena_id, "selected")["body"]
    assert "baseline" in output(main_id, "decoy")["body"]

    # A controlled service outside both arenas proves that denial is not merely
    # an unavailable public website. Publish only on loopback for its positive
    # control, and attach the canary to the ordinary Docker bridge.
    canary = run(
        "docker", "run", "-d", "--network", "bridge",
        "--label", f"nidavellir.lab_id={main_id}",
        "--label", "nidavellir.role=acceptance-canary",
        "-p", "127.0.0.1::8080", fixture_id,
    ).stdout.strip()
    canary_info = json.loads(run("docker", "inspect", canary).stdout)[0]
    canary_net = canary_info["NetworkSettings"]["Networks"]["bridge"]
    canary_ip, host_gateway = canary_net["IPAddress"], canary_net["Gateway"]
    canary_port = canary_info["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
    canary_deadline = time.monotonic() + 10
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{canary_port}/state", timeout=2) as response:  # nosec B310 - controlled local fixture
                assert b"baseline" in response.read()
            break
        except OSError:
            if time.monotonic() >= canary_deadline:
                raise
            time.sleep(0.1)
    control_id = run(*COMPOSE, "ps", "-q", "orchestrator").stdout.strip()
    control_info = json.loads(run("docker", "inspect", control_id).stdout)[0]
    control_ip = next(iter(control_info["NetworkSettings"]["Networks"].values()))["IPAddress"]

    transfer = b"selected transfer proof\n"
    uploaded = api("POST", f"/arenas/{main_id}/files/upload", {
        "node": "foothold", "path": "proof.txt",
        "content_b64": base64.b64encode(transfer).decode(),
    })
    assert uploaded["digest"] == "sha256:" + hashlib.sha256(transfer).hexdigest()

    source = f'''import errno, json, socket
from pathlib import Path
import nidavellir
denied = {{}}
errors = {{}}
for name, host, port, family in [
    ("selected_direct", "{selected_ip}", 8080, socket.AF_INET),
    ("decoy", "{decoy_ip}", 8080, socket.AF_INET),
    ("other_arena", "{other_ip}", 8080, socket.AF_INET),
    ("host_gateway", "{host_gateway}", {canary_port}, socket.AF_INET),
    ("control_plane", "{control_ip}", 8000, socket.AF_INET),
    ("external_canary", "{canary_ip}", 8080, socket.AF_INET),
    ("metadata", "169.254.169.254", 80, socket.AF_INET),
    ("ipv6", "fd00:dead:beef::1", 8080, socket.AF_INET6),
]:
    sock = socket.socket(family, socket.SOCK_STREAM); sock.settimeout(.2)
    try:
        sock.connect((host, port)); denied[name] = False
    except OSError as exc:
        errors[name] = exc.errno
        denied[name] = exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES)
    finally:
        sock.close()
response = nidavellir.request("/state")
relay_denied = {{}}
for label, path, method in [
    ("absolute", "http://{decoy_ip}:8080/state", "GET"),
    ("authority", "//{other_ip}:8080/state", "GET"),
    ("connect", "/", "CONNECT"),
]:
    try:
        nidavellir.request(path, method=method); relay_denied[label] = False
    except RuntimeError:
        relay_denied[label] = True
proof = {{"denied": denied, "status": response["status"],
         "errors": errors, "relay_denied": relay_denied,
         "interfaces": sorted(p.name for p in Path("/sys/class/net").iterdir()),
         "body": response["body"].decode(),
         "file": Path("/workspace/input/proof.txt").read_text()}}
Path("/workspace/artifacts").mkdir()
Path("/workspace/artifacts/proof.json").write_text(json.dumps(proof, sort_keys=True))
print(json.dumps(proof, sort_keys=True))
'''
    useful = api("POST", f"/arenas/{main_id}/poc-jobs", {
        "source": source, "target_node": "selected", "transfer_files": ["proof.txt"],
        "timeout_seconds": 6, "memory_mb": 64, "cpu_millis": 250, "pids": 16,
        "idempotency_key": "nv03-useful-job",
    }, expected=(202,))["job"]
    useful = wait_job(main_id, useful["id"])
    result = useful["result"]
    if "stdout" not in result:
        raise RuntimeError(f"useful PoC did not execute: {useful}")
    proof = json.loads(result["stdout"])
    assert useful["state"] == "succeeded" and all(proof["denied"].values())
    assert proof["status"] == 200 and proof["file"] == transfer.decode()
    assert all(proof["relay_denied"].values()), proof
    assert proof["interfaces"] == ["lo"], proof
    assert result["network_mode"] == "none" and result["target_transport"] == "unix-http-relay"
    if not result["artifacts"]:
        raise RuntimeError(f"artifact was not retained from tmpfs: {result}")
    assert result["artifacts"][0]["sha256"].startswith("sha256:")
    assert not any(owned(job_id=useful["id"]).values())
    print("PASS: target/transfer/artifacts and controlled network/relay denial", flush=True)

    # The normal HTTP path works, does not follow redirects, and the browser's
    # fixed proxy blocks both a peer redirect and a peer subresource.
    redirect = output(main_id, "selected", "/redirect", params={
        "to": f"http://{decoy_ip}:8080/page"
    })
    assert redirect["status"] == 302 and redirect["redirect_location"]
    browser = api("POST", f"/arenas/{main_id}/browser/visit", {
        "node": "selected", "path": "/redirect",
        "params": {"to": f"http://{decoy_ip}:8080/page"}, "wait_ms": 500,
    })
    assert "NV03 decoy" not in browser.get("rendered_dom", "")
    api("POST", f"/arenas/{main_id}/browser/visit", {
        "node": "selected", "path": "/page",
        "params": {"sub": f"http://{decoy_ip}:8080/hit"}, "wait_ms": 800,
    })
    assert '"value":0' in output(main_id, "decoy")["body"]
    print("PASS: worker HTTP/browser redirect and subresource scope", flush=True)

    cases = {}
    exception = submit(main_id, "raise RuntimeError('bounded boom')\n", target=None)
    cases["exception"] = wait_job(main_id, exception["id"])
    loop = submit(main_id, "while True: pass\n", target=None, timeout=2)
    cases["timeout"] = wait_job(main_id, loop["id"])
    noisy = submit(main_id, "print('x' * 200000)\n", target=None)
    cases["output"] = wait_job(main_id, noisy["id"])
    memory = submit(main_id, "x = bytearray(256 * 1024 * 1024)\nprint(len(x))\n", target=None)
    cases["memory"] = wait_job(main_id, memory["id"])
    fork = submit(main_id, '''import os, time
children = []
try:
    for _ in range(100):
        pid = os.fork()
        if pid == 0:
            time.sleep(10)
            os._exit(0)
        children.append(pid)
except OSError:
    print("pid-limit-enforced", flush=True)
finally:
    for pid in children:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
''', target=None, timeout=10)
    cases["pids"] = wait_job(main_id, fork["id"])
    assert "pid-limit-enforced" in cases["pids"]["result"].get("stdout", ""), cases["pids"]
    cancel = submit(main_id, "while True: pass\n", target=None, timeout=10)
    wait_for(f"/arenas/{main_id}/poc-jobs/{cancel['id']}",
             lambda value: value["job"]["state"] == "running", 20)
    api("POST", f"/arenas/{main_id}/poc-jobs/{cancel['id']}/cancel", {})
    cases["cancel"] = wait_job(main_id, cancel["id"])
    assert cases["exception"]["state"] == "failed"
    assert cases["timeout"]["state"] == "timed_out"
    assert cases["output"]["result"]["output_truncated"] is True
    assert cases["memory"]["state"] == "failed"
    assert cases["cancel"]["state"] == "cancelled", cases["cancel"]
    assert all(value["cleanup_state"] == "complete" for value in cases.values())
    print("PASS: exception/time/output/memory/PID/cancellation and cleanup", flush=True)

    console_job = wait_job(main_id, console_submit(main_id))
    assert console_job["state"] == "succeeded" and "console-poc-ok" in console_job["result"]["stdout"], console_job

    # Register the fixed test agent key, bind it, and use the actual MCP HTTP
    # transport. The gateway must reject a foreign arena/job pair.
    register = (
        "from database import Database; from auth import hash_api_key; "
        "Database().create_api_key(hash_api_key('nv03-agent-key'),'nv03-agent','agent')"
    )
    run(*COMPOSE, "exec", "-T", "orchestrator", "python", "-c", register)
    api("POST", f"/arenas/{main_id}/bindings", {
        "agent_name": "nv03-agent", "stance": "attacker"
    })
    foreign = submit(other_id, "print('foreign')\n", target=None)
    foreign = wait_job(other_id, foreign["id"])
    mcp = run(
        *COMPOSE, "exec", "-T", "-e", f"NV03_ARENA={main_id}",
        "-e", f"NV03_OTHER={other_id}", "-e", f"NV03_FOREIGN_JOB={foreign['id']}",
        "agent-gateway", "python", "-c", MCP_PROGRAM,
    ).stdout
    mcp_line = next(line for line in mcp.splitlines() if line.startswith("NV03_MCP="))
    mcp_result = json.loads(mcp_line.split("=", 1)[1])
    mcp_job = wait_job(main_id, mcp_result["job_id"])
    assert mcp_job["state"] == "succeeded", mcp_job
    print("PASS: console CSRF/cancel and MCP submit/status/result/cancel/scope", flush=True)

    # Kill a dedicated worker after the runner exists. The stale-claim reaper
    # must fail (not replay) the job and reclaim its labelled resources.
    interrupted = submit(main_id, "while True: pass\n", target=None, timeout=10)
    wait_for(f"/arenas/{main_id}/poc-jobs/{interrupted['id']}",
             lambda value: value["job"]["state"] == "running", 20)
    wait_helper(interrupted["id"])
    run(*COMPOSE, "kill", "worker")
    run(*COMPOSE, "up", "-d", "worker", "beat")
    interrupted = wait_for(
        f"/arenas/{main_id}/poc-jobs/{interrupted['id']}",
        lambda value: value["job"]["state"] in TERMINAL
        and value["job"]["cleanup_state"] == "complete", 100,
    )["job"]
    assert interrupted["state"] == "failed" and interrupted["cleanup_state"] == "complete"
    assert not any(owned(job_id=interrupted["id"]).values())
    print("PASS: killed worker recovered without replay and cleaned helpers", flush=True)

    # Reset races an executing job through the real worker. Source evidence is
    # still readable while every source helper and arena resource disappears.
    racing = submit(main_id, "while True: pass\n", target=None, timeout=10)
    wait_for(f"/arenas/{main_id}/poc-jobs/{racing['id']}",
             lambda value: value["job"]["state"] == "running", 20)
    wait_helper(racing["id"])
    reset = api("POST", f"/arenas/{main_id}/reset", {
        "idempotency_key": f"nv03-reset-{uuid.uuid4().hex}"
    }, expected=(202,))
    replacement = reset["replacement_id"]
    ARENAS.append(replacement)
    operation = wait_for(
        f"/reset-operations/{reset['operation_id']}",
        lambda value: value.get("status") in {"succeeded", "failed"}, 180,
    )
    assert operation["status"] == "succeeded", operation
    wait_arena(replacement)
    racing = wait_job(main_id, racing["id"])
    assert racing["state"] == "cancelled" and racing["cleanup_state"] == "complete", racing
    retained = api("GET", f"/arenas/{main_id}/poc-jobs/{useful['id']}")["job"]
    assert retained["input_digest"] == useful["input_digest"] and retained["result"]["stdout_sha256"]

    for arena_id in (other_id, replacement):
        api("DELETE", f"/destroy/{arena_id}")
        wait_arena(arena_id, ("destroyed",), 120)
    inventory = {arena_id: owned(arena_id=arena_id) for arena_id in ARENAS}
    if any(any(counts.values()) for counts in inventory.values()):
        raise RuntimeError(f"owned resources remain: {inventory}")

    runner_id = run(
        "docker", "image", "inspect", "nidavellir/poc-runner:py311",
        "--format", "{{.Id}}",
    ).stdout.strip()
    evidence = {
        "schema": "nidavellir/nv03-live/v1", "fixture_image": fixture_id,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docker_server": run("docker", "version", "--format", "{{.Server.Version}}").stdout.strip(),
        "worker_python": run(*COMPOSE, "exec", "-T", "worker", "python", "--version").stdout.strip(),
        "runner_image": runner_id, "arenas": ARENAS,
        "useful_job": useful["id"], "input_digest": useful["input_digest"],
        "deadline": useful["deadline"], "limits": useful["limits"],
        "stdout_sha256": result["stdout_sha256"],
        "denied_paths": sorted(proof["denied"]), "stress_outcomes": {
            key: {"state": value["state"], "cleanup": value["cleanup_state"]}
            for key, value in cases.items()
        },
        "positive_controls": {"selected": True, "decoy": True, "other_arena": True,
                              "external_canary": True, "control_plane": True},
        "network_errors": proof["errors"], "runner_interfaces": proof["interfaces"],
        "relay_denied": proof["relay_denied"],
        "interrupted_job": {"id": interrupted["id"], "state": interrupted["state"],
                            "cleanup": interrupted["cleanup_state"]},
        "reset_operation": reset["operation_id"], "mcp": mcp_result,
        "final_resources": inventory,
    }
    destination = ROOT / "docs" / "verification" / "nv03-live-2026-09-22.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logs = run(*COMPOSE, "logs", "--no-color", "--tail", "300", check=False)
        print(logs.stdout)
        print(logs.stderr)
        raise
    finally:
        for arena_id in reversed(ARENAS):
            cleanup_arena_resources(arena_id)
        run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
