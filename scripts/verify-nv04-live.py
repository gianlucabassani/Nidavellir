#!/usr/bin/env python3
"""Isolated Docker-local NV-04 budget and stop acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import http.cookiejar
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", "docker-compose.nv04.yml"]
API = "http://127.0.0.1:18004"
WEB = "http://127.0.0.1:15004"
KEY = "nv04-acceptance-key"
ARENAS = []


def run(*args, check=True):
    result = subprocess.run([*args], cwd=ROOT, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stdout[-4000:]} {result.stderr[-4000:]}")
    return result


def api(method, path, body=None, expected=(200,)):
    if method == "POST" and body is not None and (
        path.endswith("/stop") or path.endswith("/resume") or path.endswith("/clear")
        or path.endswith("/emergency-stop")
    ):
        body = {**body, "idempotency_key": body.get("idempotency_key") or uuid.uuid4().hex}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"X-API-Key": KEY, **({"Content-Type": "application/json"} if data else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:  # nosec B310 - local fixture
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
        time.sleep(.3)
    raise RuntimeError(f"timed out waiting for {path}: {last}")


def owned(arena):
    label = f"nidavellir.lab_id={arena}"
    return {kind: len(run("docker", *command, "-q", "--filter", f"label={label}").stdout.split())
            for kind, command in {
                "containers": ("ps", "-a"),
                "networks": ("network", "ls"),
                "volumes": ("volume", "ls"),
            }.items()}


def owned_job(job_id):
    label = f"nidavellir.poc_job={job_id}"
    return {kind: len(run("docker", *command, "-q", "--filter", f"label={label}").stdout.split())
            for kind, command in {
                "containers": ("ps", "-a"),
                "networks": ("network", "ls"),
                "volumes": ("volume", "ls"),
            }.items()}


def wait_helper(job_id, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if owned_job(job_id)["containers"]:
            return
        time.sleep(.1)
    raise RuntimeError(f"helper for {job_id} never appeared")


def http_action(arena):
    return api("POST", f"/arenas/{arena}/http/request",
               {"node": "selected", "path": "/state"}, expected=(200, 423, 429))


def console_stop(arena):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = opener.open(WEB + "/login", timeout=10).read().decode()  # nosec B310
    csrf = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page).group(1)
    login = urllib.parse.urlencode({"username": "admin", "password": "nv04-local-only",
                                    "csrf_token": csrf}).encode()
    opener.open(urllib.request.Request(WEB + "/login", data=login), timeout=10)  # nosec B310
    page = opener.open(WEB + f"/arena/{arena}", timeout=10).read().decode()  # nosec B310
    assert "Stop research" in page
    csrf = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page).group(1)
    payload = urllib.parse.urlencode({"csrf_token": csrf, "reason": "live console stop"}).encode()
    opener.open(urllib.request.Request(WEB + f"/arena/{arena}/stop", data=payload), timeout=15)  # nosec B310


MCP_PROGRAM = r'''
import anyio, json, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/mcp") as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            result = await session.call_tool("budget_status", arguments={"arena_id": os.environ["NV04_ARENA"]})
            assert not result.isError, result
            value = result.structuredContent or json.loads(next(
                item.text for item in result.content if item.type == "text"))
            print("NV04_BUDGET=" + json.dumps(value))
anyio.run(main)
'''


def mcp_budget(arena):
    output = run(*COMPOSE, "exec", "-T", "-e", f"NV04_ARENA={arena}",
                 "agent-gateway", "python", "-c", MCP_PROGRAM).stdout
    return json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                           if line.startswith("NV04_BUDGET=")))


def main():
    run("docker", "build", "-t", "nidavellir/nv04-fixture:acceptance",
        "cyber-range/fixtures/nv02-reset")
    fixture_id = run("docker", "image", "inspect", "nidavellir/nv04-fixture:acceptance",
                     "--format", "{{.Id}}").stdout.strip()
    run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
    run(*COMPOSE, "up", "-d", "--build", "poc-runner-image", "postgres", "redis",
        "orchestrator", "worker", "beat", "webui", "agent-gateway")
    wait("/health", lambda result: result.get("status") == "ok")
    scenario = {
        "schema": "nidavellir/v3", "name": "NV-04 budget fixture",
        "requires": {"provider_class": "container", "egress": "none", "mirror": "off"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{"name": "selected", "role": "victim", "image": fixture_id,
                   "segments": ["lab"], "ports": [8080]}],
        "lifecycle": {"readiness": {"type": "http", "node": "selected", "port": 8080,
                                    "path": "/state", "expected_status": 200,
                                    "timeout_seconds": 20}},
    }
    api("POST", "/scenarios", {"id": "nv04-fixture", "spec": scenario})
    for name in ("nv04-main", "nv04-other"):
        result = api("POST", "/deploy", {"scenario": "nv04-fixture", "instance_id": name,
                                           "provider": "docker-local",
                                           "engagement_time_box_seconds": 1200})
        ARENAS.append(result["instance_id"])
        wait(f"/status/{result['instance_id']}",
             lambda value: value.get("status") == "active", 120)

    main_id, other_id = ARENAS

    register = ("from database import Database; from auth import hash_api_key; "
                "Database().create_api_key(hash_api_key('nv04-agent-key'),'nv04-agent','agent')")
    run(*COMPOSE, "exec", "-T", "orchestrator", "python", "-c", register)
    api("POST", f"/arenas/{main_id}/bindings", {"agent_name": "nv04-agent", "stance": "attacker"})
    before = mcp_budget(main_id)
    assert before["policy"]["remaining"] > 0
    http_action(main_id)
    after = mcp_budget(main_id)  # a second gateway process observes the persisted count
    assert after["policy"]["remaining"] == before["policy"]["remaining"] - 1

    cap = after["policy"]["spent"] + 1
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    api("POST", f"/arenas/{main_id}/budget/policy",
        {"action_cap": cap, "deadline": deadline, "reason": "one slot race"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        race = list(pool.map(http_action, [main_id, main_id]))
    assert len([value for value in race if "http_status" not in value]) == 1, race
    assert len([value for value in race if value.get("http_status") == 429]) == 1, race
    assert api("GET", f"/arenas/{main_id}/budget")["policy"]["remaining"] == 0

    # A queued PoC reserves without executing. Cancellation releases it.
    api("POST", f"/arenas/{main_id}/budget/policy",
        {"action_cap": cap + 3, "deadline": deadline, "reason": "stop fixture"})
    run(*COMPOSE, "stop", "worker")
    queued = api("POST", f"/arenas/{main_id}/poc-jobs", {
        "source": "print('never executed')\n", "timeout_seconds": 10,
        "idempotency_key": f"nv04-queued-{uuid.uuid4().hex}",
    }, expected=(202,))["job"]
    assert api("GET", f"/arenas/{main_id}/budget")["policy"]["reserved"] == 1
    api("POST", f"/arenas/{main_id}/poc-jobs/{queued['id']}/cancel", {})
    assert api("GET", f"/arenas/{main_id}/budget")["policy"]["remaining"] == 3
    run(*COMPOSE, "up", "-d", "worker")

    # A claimed PoC keeps its charge and is cancelled by the console stop.
    job = api("POST", f"/arenas/{main_id}/poc-jobs", {
        "source": "while True: pass\n", "timeout_seconds": 10,
        "idempotency_key": f"nv04-{uuid.uuid4().hex}",
    }, expected=(202,))["job"]
    wait(f"/arenas/{main_id}/poc-jobs/{job['id']}",
         lambda value: value["job"]["state"] == "running", 20)
    console_stop(main_id)
    terminal = wait(f"/arenas/{main_id}/poc-jobs/{job['id']}",
                    lambda value: value["job"]["state"] not in {"queued", "running"}, 40)["job"]
    assert terminal["cleanup_state"] == "complete", terminal
    wait(f"/arenas/{main_id}/budget", lambda value: value["arena"]["state"] == "stopped", 40)
    assert http_action(main_id)["http_status"] == 423
    assert "http_status" not in http_action(other_id)  # arena stop is scoped
    assert api("GET", f"/arenas/{main_id}/budget")["policy"]["spent"] == cap + 1
    api("POST", f"/arenas/{main_id}/resume", {"reason": "verified live drain"})

    # Stop competes with job admission under the same durable gate.
    api("POST", f"/arenas/{main_id}/budget/policy", {
        "action_cap": cap + 6, "deadline": deadline, "reason": "stop race and recovery",
    })

    def submit_racing():
        return api("POST", f"/arenas/{main_id}/poc-jobs", {
            "source": "while True: pass\n", "timeout_seconds": 10,
            "idempotency_key": f"nv04-race-{uuid.uuid4().hex}",
        }, expected=(202, 409))

    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted_future = pool.submit(submit_racing)
        stopped_future = pool.submit(api, "POST", f"/arenas/{main_id}/stop",
                                     {"reason": "admission race"})
        racing_job = submitted_future.result()
        stopped_future.result()
    if "job" in racing_job:
        race_terminal = wait(f"/arenas/{main_id}/poc-jobs/{racing_job['job']['id']}",
                             lambda value: value["job"]["state"] not in {"queued", "running"}, 40)["job"]
        assert race_terminal["cleanup_state"] in {"complete", "not_started"}
        assert not any(owned_job(racing_job["job"]["id"]).values())
    else:
        assert racing_job["http_status"] == 409
    wait(f"/arenas/{main_id}/budget", lambda value: value["arena"]["state"] == "stopped", 40)
    api("POST", f"/arenas/{main_id}/resume", {"reason": "admission race drained"})

    # A dead worker cannot replay a claimed helper. Stop stays latched until
    # the replacement worker's reaper verifies labelled cleanup.
    interrupted = api("POST", f"/arenas/{main_id}/poc-jobs", {
        "source": "while True: pass\n", "timeout_seconds": 10,
        "idempotency_key": f"nv04-interrupted-{uuid.uuid4().hex}",
    }, expected=(202,))["job"]
    wait(f"/arenas/{main_id}/poc-jobs/{interrupted['id']}",
         lambda value: value["job"]["state"] == "running", 20)
    wait_helper(interrupted["id"])
    run(*COMPOSE, "kill", "worker")
    api("POST", f"/arenas/{main_id}/stop", {"reason": "worker died during stop"})
    run(*COMPOSE, "up", "-d", "worker", "beat")
    interrupted_result = wait(f"/arenas/{main_id}/poc-jobs/{interrupted['id']}",
                              lambda value: value["job"]["state"] not in {"queued", "running"}
                              and value["job"]["cleanup_state"] == "complete", 90)["job"]
    assert interrupted_result["state"] in {"failed", "cancelled"}
    assert not any(owned_job(interrupted["id"]).values())
    wait(f"/arenas/{main_id}/budget", lambda value: value["arena"]["state"] == "stopped", 40)
    api("POST", f"/arenas/{main_id}/resume", {"reason": "worker cleanup verified"})

    # HTTP and browser use the same durable worker jobs as PoC. Stop while
    # their requests are in flight, then verify every submitted helper drains.
    existing_jobs = len(api("GET", f"/arenas/{main_id}/poc-jobs")["jobs"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        browser_call = pool.submit(api, "POST", f"/arenas/{main_id}/browser/visit",
                                   {"node": "selected", "path": "/state", "wait_ms": 5000},
                                   (200, 502, 423))
        http_call = pool.submit(api, "POST", f"/arenas/{main_id}/http/request",
                                {"node": "selected", "path": "/state"},
                                (200, 502, 423))
        wait(f"/arenas/{main_id}/poc-jobs",
             lambda value: len(value["jobs"]) >= existing_jobs + 2
             and any(job["state"] in {"queued", "running"}
                     for job in value["jobs"][:2]), 20)
        api("POST", f"/arenas/{main_id}/stop", {"reason": "HTTP and browser drain"})
        browser_call.result()
        http_call.result()
    wait(f"/arenas/{main_id}/budget", lambda value: value["arena"]["state"] == "stopped", 40)
    helper_jobs = api("GET", f"/arenas/{main_id}/poc-jobs")["jobs"][:2]
    assert all(job["state"] not in {"queued", "running"}
               and job["cleanup_state"] in {"complete", "not_started"}
               and not any(owned_job(job["id"]).values()) for job in helper_jobs), helper_jobs
    api("POST", f"/arenas/{main_id}/resume", {"reason": "HTTP/browser cleanup verified"})

    api("POST", "/system/emergency-stop", {"reason": "live system stop"})
    assert http_action(other_id)["http_status"] == 423
    run(*COMPOSE, "restart", "orchestrator", "worker", "agent-gateway")
    wait("/health", lambda value: value.get("status") == "ok", 90)
    assert http_action(other_id)["http_status"] == 423
    wait("/system/emergency-stop", lambda value: value["state"] == "stopped", 40)
    api("POST", "/system/emergency-stop/clear", {"reason": "verified live clear"})
    assert "http_status" not in http_action(other_id)

    api("POST", f"/arenas/{other_id}/budget/policy", {
        "action_cap": 1000,
        "deadline": (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat(),
        "reason": "wall-clock expiry fixture",
    })
    run(*COMPOSE, "stop", "worker")
    expiring = api("POST", f"/arenas/{other_id}/poc-jobs", {
        "source": "print('deadline prevented execution')\n", "timeout_seconds": 10,
        "idempotency_key": f"nv04-expiry-{uuid.uuid4().hex}",
    }, expected=(202,))["job"]
    time.sleep(4)
    run(*COMPOSE, "up", "-d", "worker")
    expired_job = wait(f"/arenas/{other_id}/poc-jobs/{expiring['id']}",
                       lambda value: value["job"]["state"] not in {"queued", "running"}, 40)["job"]
    assert expired_job["state"] == "cancelled" and expired_job["cleanup_state"] == "not_started"
    assert http_action(other_id)["http_status"] == 423
    refused = api("POST", f"/arenas/{main_id}/budget/policy", {
        "action_cap": 1000, "deadline": deadline, "reason": "unsupported accounting",
        "token_cap": 1000,
    }, expected=(422,))
    assert refused["http_status"] == 422
    before_jobs = len(api("GET", f"/arenas/{main_id}/poc-jobs")["jobs"])
    capped_job = api("POST", f"/arenas/{main_id}/poc-jobs", {
        "source": "print('must not execute')\n", "idempotency_key": uuid.uuid4().hex,
        "cost_budget_usd": 0.10,
    }, expected=(422,))
    assert capped_job["http_status"] == 422
    assert len(api("GET", f"/arenas/{main_id}/poc-jobs")["jobs"]) == before_jobs

    for arena in ARENAS:
        api("DELETE", f"/destroy/{arena}")
        wait(f"/status/{arena}", lambda value: value.get("status") == "destroyed", 120)
    inventory = {arena: owned(arena) for arena in ARENAS}
    assert all(not any(resources.values()) for resources in inventory.values()), inventory
    evidence = {
        "schema": "nidavellir/nv04-live/v1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "docker_server": run("docker", "version", "--format", "{{.Server.Version}} ").stdout.strip(),
        "fixture_image": fixture_id, "arenas": ARENAS,
        "mcp_before": before["policy"]["remaining"],
        "mcp_after": after["policy"]["remaining"],
        "race": [value.get("http_status", 200) for value in race],
        "stopped_job": {"id": job["id"], "state": terminal["state"],
                        "cleanup": terminal["cleanup_state"]},
        "queued_cancel": {"id": queued["id"], "state": "cancelled", "refunded": True},
        "expired_job": {"id": expiring["id"], "state": expired_job["state"]},
        "stop_admission_race": racing_job.get("http_status", 202),
        "interrupted_stop": {"id": interrupted["id"],
                             "state": interrupted_result["state"],
                             "cleanup": interrupted_result["cleanup_state"]},
        "http_browser_drained": [job["id"] for job in helper_jobs],
        "system_epoch": api("GET", "/system/emergency-stop")["epoch"],
        "token_cap_refused": True, "cost_capped_job_refused": True,
        "final_resources": inventory,
    }
    destination = ROOT / "docs" / "verification" / f"nv04-live-{datetime.now():%Y-%m-%d}.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logs = run(*COMPOSE, "logs", "--no-color", "--tail", "200", check=False)
        print(logs.stdout[-12000:])
        raise
    finally:
        run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        # A failed assertion can bypass the normal arena destroy path. Reclaim
        # only resources labeled with arena IDs created by this verifier.
        for arena in ARENAS:
            selector = f"label=nidavellir.lab_id={arena}"
            for kind in ("ps", "network ls", "volume ls"):
                command = kind.split()
                if kind == "ps":
                    command.extend(("-aq", "--filter", selector))
                else:
                    command.extend(("-q", "--filter", selector))
                resources = run("docker", *command, check=False).stdout.split()
                if resources:
                    remove = {"ps": ("rm", "-f"), "network ls": ("network", "rm"),
                              "volume ls": ("volume", "rm")}[kind]
                    run("docker", *remove, *resources, check=False)
