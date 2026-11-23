#!/usr/bin/env python3
"""RC-03 acceptance: the research core (F1–F4, R1–R4) on a live docker-local arena.

Runs on an isolated Compose project (``nidavellir-rc``, loopback ports) built from
``compose/acceptance/nv06.yml`` + ``rc.yml``, with real PostgreSQL, Redis, API and
worker, against real arena containers built from the NV-02 reset fixture. One
sequence exercises each feature through its public API:

  F1 extend the time box        R1 hypothesis contract and probe gate (real exec)
  F2 carry-over to a redeploy   R2 duplicate detection on the same root cause
  F3 digest within its cap      R3 causality backed by real HTTP transactions
  F4 configurator deploy        R4 sweeps shelve the arena; an operator reopens it

  .venv/bin/python scripts/verify-research-core-live.py

No external target is contacted. The stack, its volumes and the arenas it created
are removed at the end. Evidence is written to docs/verification/ (gitignored) and
never overwritten.
"""
from __future__ import annotations

import json
# subprocess runs fixed docker argv only, never a shell.
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ("docker", "compose", "--project-directory", ".", "-p", "nidavellir-rc",
           "-f", "compose/acceptance/nv06.yml", "-f", "compose/acceptance/rc.yml")
API = "http://127.0.0.1:18017"
OPERATOR_KEY, AGENT_KEY, CONFIG_KEY = "rc-operator-key", "rc-agent-key", "rc-config-key"
AGENT, CONFIGURATOR = "rc-agent", "rc-config"
FIXTURE = "nidavellir/rc-fixture:acceptance"
SCENARIO = "rc-fixture"
ARENAS: list[str] = []


def run(*args, check=True):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,  # nosec B603
                            timeout=900, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"{args[:4]}: {result.stdout[-800:]} {result.stderr[-800:]}")
    return result


def api(method, path, body=None, *, key=OPERATOR_KEY, expected=(200, 201, 202)):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(API + path, data=data, method=method, headers={
        "X-API-Key": key, **({"Content-Type": "application/json"} if data else {})})
    try:
        # The API is this script's own stack on loopback.
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    payload = json.loads(raw) if raw else None
    if expected is not None and status not in expected:
        raise RuntimeError(f"{method} {path}: HTTP {status}: {raw[:600]!r}")
    return status, payload


def ok(method, path, body=None, **kw):
    return api(method, path, body, **kw)[1]


def refused(method, path, body=None, *, key, status, code=None):
    got, payload = api(method, path, body, key=key, expected=None)
    detail = (payload or {}).get("detail")
    assert got == status, (method, path, got, payload)
    if code:
        assert isinstance(detail, dict) and detail.get("code") == code, (path, detail)
    return detail


def wait(predicate, what, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (RuntimeError, OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for {what}")


def wait_status(arena, wanted, timeout=300):
    seen = {}

    def check():
        seen.update(ok("GET", f"/status/{arena}"))
        return seen if seen["status"] in wanted else None
    try:
        return wait(check, f"{arena} {wanted}", timeout=timeout)
    except RuntimeError as exc:
        logs = run(*COMPOSE, "logs", "--no-color", "--tail", "60", "worker", check=False)
        raise RuntimeError(f"{exc}; last status {seen.get('status')!r}, error "
                           f"{seen.get('error')!r}; worker log tail:\n{logs.stdout[-3000:]}") from exc


def deploy(key=OPERATOR_KEY):
    body = ok("POST", "/deploy", {"scenario": SCENARIO, "provider": "docker-local",
                                  "instance_id": f"rc-{uuid.uuid4().hex[:6]}"}, key=key)
    ARENAS.append(body["instance_id"])
    state = wait_status(body["instance_id"],
                        ("active", "failed", "error_destroying", "destroyed"))
    if state["status"] != "active":
        events = api("GET", f"/deployments/{body['instance_id']}/events", expected=None)[1]
        raise RuntimeError(f"arena ended {state['status']!r}: {json.dumps(events)[-3000:]}")
    return body


def contract(hid, budget=4):
    return {"id": hid, "source": "fix-diff", "provenance": "fixture state endpoint",
            "preconditions": ["foothold on the lab segment"],
            "invariant": "state is only changed by its owner",
            "source_sink": {"source": "GET /state", "sink": "fixture state store"},
            "expected_observable": "state document returned", "negative_control":
            "a reset returns the baseline", "dedup_key": "rc-state-read",
            "probe_budget": budget, "stop_condition": "two consistent responses"}


def http(arena, path, hid, params=None):
    body = ok("POST", f"/arenas/{arena}/http/request",
              {"node": "selected", "path": path, "params": params or {},
               "hypothesis_id": hid}, key=AGENT_KEY)
    assert body["status"] == 200 and body["transaction_digest"].startswith("sha256:"), body
    return body["transaction_digest"]


def cleanup():
    for arena in ARENAS:
        api("DELETE", f"/destroy/{arena}", expected=None)
    for arena in ARENAS:
        try:
            wait_status(arena, ("destroyed", "failed", "error_destroying"))
        except RuntimeError:
            pass
    for arena in ARENAS:
        ids = run("docker", "ps", "-aq", "--filter", f"label=nidavellir.lab_id={arena}",
                  check=False).stdout.split()
        if ids:
            run("docker", "rm", "-f", *ids, check=False)
    run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)


def main() -> int:
    tag = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "-" + uuid.uuid4().hex[:8]
    output = ROOT / "docs" / "verification" / f"research-core-live-{tag}.json"
    report: dict = {"schema": "nidavellir/research-core-live/v1", "checks": {}}
    checks = report["checks"]
    try:
        run("docker", "build", "-t", FIXTURE, "cyber-range/fixtures/nv02-reset")
        run(*COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        run(*COMPOSE, "up", "-d", "--build", "--wait", "postgres", "redis", "orchestrator",
            "worker", "beat")
        wait(lambda: ok("GET", "/health", key="").get("status") == "ok", "health")
        run(*COMPOSE, "exec", "-T", "orchestrator", "python", "-c",
            "from database import Database; from auth import hash_api_key; db=Database(); "
            f"db.create_api_key(hash_api_key('{OPERATOR_KEY}'),'rc-operator','operator'); "
            f"db.create_api_key(hash_api_key('{AGENT_KEY}'),'{AGENT}','agent'); "
            f"db.create_api_key(hash_api_key('{CONFIG_KEY}'),'{CONFIGURATOR}','agent')")
        fixture_id = run("docker", "image", "inspect", FIXTURE, "--format",
                         "{{.Id}}").stdout.strip()
        ok("POST", "/scenarios", {"id": SCENARIO, "spec": {
            "schema": "nidavellir/v3", "name": "RC-03 research core fixture",
            "requires": {"provider_class": "container", "egress": "none", "mirror": "off"},
            "network": {"segments": [{"name": "lab"}]},
            "nodes": [
                {"name": "selected", "role": "victim", "image": fixture_id,
                 "segments": ["lab"], "ports": [8080], "environment": {"NODE_ID": "selected"}},
                {"name": "foothold", "role": "attacker", "image": fixture_id,
                 "segments": ["lab"], "entrypoint": True},
            ]}})

        first = deploy()["instance_id"]
        # F2 setup: persistent grants that should follow the scenario to a redeploy.
        for name, stance in ((AGENT, "attacker"), (CONFIGURATOR, "configurator")):
            ok("POST", f"/arenas/{first}/bindings",
               {"agent_name": name, "stance": stance, "persistent": True})

        # F1: extend the time box.
        extended = ok("POST", f"/arenas/{first}/extend", {"seconds": 900})
        assert extended["action"] == "extended" and extended["expires_at"] > (
            extended["previous_expires_at"] or ""), extended
        checks["f1_extend"] = {"previous_expires_at": extended["previous_expires_at"],
                               "expires_at": extended["expires_at"]}

        # R1: research mode; probes must cite an open hypothesis with budget left.
        ok("POST", f"/arenas/{first}/research-mode", {"enabled": True, "reason": "RC-03 live"})
        exec_body = {"node": "foothold", "command": "id"}
        no_hyp = refused("POST", f"/arenas/{first}/exec", exec_body, key=AGENT_KEY,
                         status=422)
        ok("POST", f"/arenas/{first}/hypotheses", contract("H-rc-1", budget=4), key=AGENT_KEY)
        ran = ok("POST", f"/arenas/{first}/exec", {**exec_body, "hypothesis_id": "H-rc-1"},
                 key=AGENT_KEY)
        assert ran.get("exit_code", 0) == 0 and "uid=" in json.dumps(ran), ran
        trace = http(first, "/state", "H-rc-1")
        toggle = http(first, "/state", "H-rc-1", {"view": "owner"})
        control = http(first, "/state", "H-rc-1", {"build": "fixed"})
        spent = refused("POST", f"/arenas/{first}/exec",
                        {**exec_body, "hypothesis_id": "H-rc-1"}, key=AGENT_KEY, status=429,
                        code="probe_budget_exhausted")
        checks["r1_probe_gate"] = {"without_hypothesis": no_hyp, "probes_used": 4,
                                   "exhausted": spent["code"]}

        # R2 + R3: a finding backed by three recorded transactions; its duplicate.
        root = {"invariant": "state is only changed by its owner",
                "owner_lifetime": "state owned by the fixture process",
                "source": "GET /state on the selected node", "sink": "fixture state store",
                "missing_check": "no caller identity on read",
                "oracle": "state document returned to the foothold"}
        causality = {
            "trace": {"summary": "GET /state reaches the state store", "evidence_digest": trace},
            "fixed_build_control": {"summary": "fixed build query recorded", "kind":
                                    "fixed_build", "build": "fixture baseline",
                                    "evidence_digest": control},
            "toggle": {"summary": "owner view toggled", "control": "view",
                       "evidence_digest": toggle}}
        fake = {"trace": {"summary": "x", "evidence_digest": "sha256:" + "0" * 64}}
        bogus = refused("POST", f"/arenas/{first}/findings",
                        {"title": "fabricated", "root_cause": {**root, "sink": "other"},
                         "causality": fake}, key=AGENT_KEY, status=422)
        found = ok("POST", f"/arenas/{first}/findings",
                   {"title": "State readable from the foothold", "root_cause": root,
                    "causality": causality}, key=AGENT_KEY)["finding_id"]
        dup = ok("POST", f"/arenas/{first}/findings",
                 {"title": "Same bug, new title", "root_cause": root}, key=AGENT_KEY)["finding_id"]
        bare = ok("POST", f"/arenas/{first}/findings",
                  {"title": "No causality", "root_cause": {**root, "sink": "another store"}},
                  key=AGENT_KEY)["finding_id"]
        confirmed = ok("POST", f"/arenas/{first}/findings/{found}/verify",
                       {"verdict": "confirmed", "evidence_digest": trace})
        assert confirmed["verdict"] == "confirmed", confirmed
        dup_refused = refused("POST", f"/arenas/{first}/findings/{dup}/verify",
                              {"verdict": "confirmed", "evidence_digest": trace},
                              key=OPERATOR_KEY, status=409)
        bare_refused = refused("POST", f"/arenas/{first}/findings/{bare}/verify",
                               {"verdict": "confirmed", "evidence_digest": trace},
                               key=OPERATOR_KEY, status=422, code="causality_incomplete")
        checks["r2_duplicate"] = {"duplicate_confirm_refused": dup_refused}
        checks["r3_causality"] = {"confirmed": found, "fabricated_digest_refused": bogus,
                                  "incomplete_refused": bare_refused["code"]}

        # R4: sweeps; the findings above are yielded once, then two empty sweeps shelve.
        surfaces = ["/state", "/reset"]
        first_sweep = ok("POST", f"/arenas/{first}/sweeps", {
            "source": "fix-diff", "surfaces_planned": surfaces, "surfaces_reviewed": surfaces},
            key=AGENT_KEY)
        assert first_sweep["sweep"]["yield"] == 2, first_sweep["sweep"]
        ok("POST", f"/arenas/{first}/sweeps", {"source": "fuzz"}, key=AGENT_KEY)
        shelved = ok("POST", f"/arenas/{first}/sweeps", {"source": "fuzz"}, key=AGENT_KEY)
        assert shelved["shelved_by_this_sweep"] is True, shelved
        blocked = refused("POST", f"/arenas/{first}/hypotheses", contract("H-rc-2"),
                          key=AGENT_KEY, status=409, code="research_shelved")
        reopened = ok("POST", f"/arenas/{first}/research/reopen",
                      {"trigger": "new_commit", "detail": "RC-03 reopen"})
        assert reopened["status"] == "active", reopened
        checks["r4_saturation"] = {"first_sweep_yield": 2, "shelved": shelved["shelved"],
                                   "blocked": blocked["code"], "reopened": True}

        # F3: the digest stays within its cap and carries the research block.
        raw = urllib.request.urlopen(urllib.request.Request(  # nosec B310
            API + f"/arenas/{first}/digest", headers={"X-API-Key": AGENT_KEY}), timeout=30).read()
        digest = json.loads(raw)
        assert len(raw) <= 2048 and digest["research"]["mode"] is True, digest
        checks["f3_digest"] = {"bytes": len(raw), "research": digest["research"]}

        # F2: destroy, redeploy the same scenario; both persistent grants follow.
        ok("DELETE", f"/destroy/{first}")
        wait_status(first, ("destroyed",))
        second = deploy()
        carried = sorted(second.get("carried_over_bindings") or [])
        assert carried == sorted([AGENT, CONFIGURATOR]), second
        checks["f2_carry_over"] = {"second_arena": second["instance_id"], "carried": carried}

        # F4: the configurator deploys the allowlisted scenario itself; the attacker cannot.
        attacker_refused = refused("POST", "/deploy", {"scenario": SCENARIO,
                                                       "instance_id": "rc-attacker"},
                                   key=AGENT_KEY, status=403)
        third = deploy(key=CONFIG_KEY)
        checks["f4_configurator_deploy"] = {"arena": third["instance_id"],
                                            "attacker_refused": attacker_refused}
        report["status"] = "passed"
    except BaseException as exc:
        report["status"], report["error"] = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        raise
    finally:
        report["arenas"] = list(ARENAS)
        cleanup()
        leftovers = [a for a in ARENAS if run("docker", "ps", "-aq", "--filter",
                     f"label=nidavellir.lab_id={a}", check=False).stdout.strip()]
        report["leftover_arena_containers"] = leftovers
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            output.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(json.dumps({"evidence": str(output), "status": report.get("status")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
