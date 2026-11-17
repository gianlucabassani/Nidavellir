#!/usr/bin/env python3
"""NV-14 acceptance: one finding traced across versions, and a reviewable bundle.

Calibration, not discovery: the target is the known CVE-2026-26012 on the pinned
Vaultwarden 1.35.2 fixture and its fix in 1.37.3, deployed fresh on Docker-local
by the existing live verifier's steps. Works the NV-14 acceptance checklist
on an isolated Compose
project (nidavellir-nv14, loopback ports), with real PostgreSQL, Redis, API,
worker and console.

  NV_PLAYWRIGHT_MODULE=/path/to/node_modules/playwright NV_CHROMIUM_PATH=/path/to/chromium \
  .venv/bin/python scripts/verify-nv14-live.py

No external target is contacted; the two pinned images are pulled from the
registry. Nothing is sent anywhere. The stack, its volumes, its images and the
arenas it created are removed at the end. New evidence paths refuse overwrite.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vw = _load("verify_vaultwarden_live", ROOT / "scripts/verify-vaultwarden-live.py")
gate = vw.fixture
gate.COMPOSE = ("docker", "compose", "--project-directory", ".", "-p", "nidavellir-nv14",
                "-f", "compose/acceptance/nv06.yml", "-f", "compose/acceptance/nv14.yml")
gate.API = "http://127.0.0.1:18015"
WEB = "http://127.0.0.1:15015"
PASSWORD = "nv06-local-only"
ADMIN_KEY = gate.KEY
OPERATOR_KEY = "nv14-operator-key"
SERVICES = ("orchestrator", "worker", "webui", "agent-gateway")
BASE = "/research/campaigns"
STACK_ENV: dict[str, str] = {}
# What a default bundle must never contain, whatever the target returned.
FORBIDDEN_KEYS = ("text_redacted", "body_redacted", "actor", "Authorization", "api_key")


def compose(*args, check=True):
    result = subprocess.run([*gate.COMPOSE, *args], cwd=ROOT, text=True, capture_output=True,
                            check=False, env={**os.environ, **STACK_ENV})
    if check and result.returncode:
        raise RuntimeError(f"compose {args}: {result.stdout[-1500:]} {result.stderr[-1500:]}")
    return result


def api(method, path, body=None, *, key=None, expected=(200,)):
    return gate.api(method, path, body, key=key or OPERATOR_KEY, expected=expected)


def status_of(method, path, body=None, *, key=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(gate.API + path, data=data, method=method, headers={
        "X-API-Key": key or OPERATOR_KEY, **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:  # nosec B310 - fixed local service
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def event_counts():
    output = compose("exec", "-T", "postgres", "psql", "-U", "nidavellir", "-d", "nidavellir_nv06",
                     "-At", "-F", "\t", "-c",
                     "select lab_id, type, count(*) from events group by 1, 2 order by 1, 2").stdout
    return [line.split("\t") for line in output.splitlines() if line]


def other_containers():
    """Names and start times of nidavellir-* containers outside this project and the gate."""
    names = gate.run("docker", "ps", "--filter", "name=^nidavellir-", "--format",
                     "{{.Names}}", check=False).stdout.split()
    names = sorted(name for name in names
                   if not name.startswith(("nidavellir-nv14-", "nidavellir-verify-")))
    if not names:
        return []
    started = gate.run("docker", "inspect", "--format", "{{.Name}} {{.State.StartedAt}}",
                       *names, check=False).stdout.split("\n")
    return sorted(line for line in started if line)


def keys_in(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys_in(item)


def state_of(campaign_ids):
    """Everything an operator can read back: summaries and every listed bundle."""
    state = {}
    for campaign_id in campaign_ids:
        summary = api("GET", f"{BASE}/{campaign_id}")
        state[campaign_id] = {"summary": summary, "bundles": {
            item["bundle_digest"]: api("GET", f"{BASE}/{campaign_id}/bundles/{item['bundle_digest']}")
            for row in summary["findings"] for item in row["bundles"]}}
    text = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest(), state


def main():
    assert os.environ.get("NV_PLAYWRIGHT_MODULE"), "NV_PLAYWRIGHT_MODULE is required"
    tag = datetime.now(timezone.utc).strftime("%Y-%m-%d-") + uuid.uuid4().hex[:8]
    output = ROOT / f"docs/verification/nv-14-live-{tag}.json"
    with output.open("x") as handle:
        json.dump({"status": "started", "date": tag}, handle)
    report = {"schema": "nidavellir/nv-14-live/v1", "date": tag, "status": "running",
              "label": "calibration: a known CVE on pinned versions, not a discovery",
              "cve": "CVE-2026-26012", "advisory": "GHSA-h265-g7rm-h337",
              "target": "vaultwarden/server", "pins": dict(vw.builder.PINS), "checks": {}}
    checks = report["checks"]
    production = other_containers()
    secret = Fernet.generate_key().decode()
    passphrase = "nv14-" + uuid.uuid4().hex + uuid.uuid4().hex
    STACK_ENV.update(NV14_SECRETS_ENCRYPTION_KEY=secret,
                     NIDAVELLIR_RECOVERY_PASSPHRASE=passphrase)
    workspace = tempfile.TemporaryDirectory(prefix="nv14-live-")
    work = Path(workspace.name)
    try:
        base_id = vw._base_image()
        compose("down", "--volumes", "--remove-orphans", check=False)
        compose("up", "-d", "--build", "--wait", "postgres", "redis", "orchestrator", "worker",
                "webui", "agent-gateway")
        gate.wait("/health", lambda data: data.get("status") == "ok")
        compose("exec", "-T", "orchestrator", "python", "-c",
                "from database import Database; from auth import hash_api_key; db=Database(); "
                "db.create_api_key(hash_api_key('nv06-agent-key'),'nv06-agent','agent'); "
                f"db.create_api_key(hash_api_key('{OPERATOR_KEY}'),'nv14-operator','operator')")

        # --- the pair: confirmed on 1.35.2, refuted on 1.37.3 (existing verifier steps) ---
        results, images, root = {}, {}, None
        for version in sorted(vw.builder.PINS):
            meta = vw.builder.build(version)
            images[version] = meta["image_id"]
            results[version] = vw._run_version(meta, base_id, variant_of=root)
            verdict = results[version]["verdict"]
            assert (verdict["verdict"], verdict["reason_code"]) == vw.EXPECTED[version], verdict
            root = root or results[version]["finding_id"]
        variant = results["1.37.3"]["finding_id"]
        arenas = {version: results[version]["arena"] for version in results}
        report["pair"] = {version: {
            "arena": results[version]["arena"], "finding_id": results[version]["finding_id"],
            "image_id": images[version], "verdict": results[version]["verdict"]["verdict"],
            "reason_code": results[version]["verdict"]["reason_code"]} for version in results}
        group = api("GET", f"/findings/{root}")
        assert group["comparison"]["outcome"] == "disappeared_under_controls", group
        events_before = event_counts()
        arena_events_before = {arena: len(api("GET", f"/deployments/{arena}/events?limit=500")["events"])
                               for arena in arenas.values()}
        budgets_before = {arena: api("GET", f"/arenas/{arena}/budget") for arena in arenas.values()}

        # --- one finding traced across versions ---------------------------------------
        created = api("POST", BASE, {"name": "Vaultwarden calibration: CVE-2026-26012",
                                     "product": "vaultwarden/server",
                                     "note": "Calibration of the campaign workflow on a known CVE."},
                      expected=(201,))
        campaign = created["campaign_id"]
        added = api("POST", f"{BASE}/{campaign}/findings", {"finding_id": variant})
        assert added["added"] is True and added["research_key"] == root
        for again in (root, variant):  # either member, a second time: nothing changes
            repeat = api("POST", f"{BASE}/{campaign}/findings", {"finding_id": again})
            assert repeat["added"] is False and len(repeat["campaign"]["findings"]) == 1
        row = api("GET", f"{BASE}/{campaign}")["findings"][0]
        assert [member["arena_id"] for member in row["members"]] == [arenas["1.35.2"], arenas["1.37.3"]]
        identities = row["identities"]

        def image_of(entries):
            return [entry["identity"]["images"]["target"]["image"] for entry in entries]

        assert image_of(identities["affected"]) == [images["1.35.2"]]
        assert image_of(identities["not_observed_under_controls"]) == [images["1.37.3"]]
        assert identities["unknown"] == []
        # No version that was not run is listed anywhere.
        listed = {image for entries in identities.values() for image in image_of(entries)}
        assert listed == set(images.values())
        assert row["comparison"]["outcome"] == "disappeared_under_controls"
        checks["one_row_for_two_arenas"] = {
            "rows": 1, "members": 2, "repeat_add_changed_nothing": True,
            "affected": image_of(identities["affected"]),
            "not_observed_under_controls": image_of(identities["not_observed_under_controls"]),
            "unknown": 0, "identities_listed": sorted(listed)}

        # --- disclosure state --------------------------------------------------------------
        disclosure = f"{BASE}/{campaign}/findings/{root}/disclosure"
        assert row["disclosure"]["state"] == "internal" and row["disclosure_history"] == []
        refused = {
            "regressed_without_note": status_of("POST", disclosure, {"state": "regressed"}),
            "internal_without_note": status_of("POST", disclosure, {"state": "internal"}),
            "unknown_state": status_of("POST", disclosure, {"state": "wontfix"}),
            "group_not_in_campaign": status_of(
                "POST", f"{BASE}/{campaign}/findings/{'0' * 12}/disclosure", {"state": "reported"})}
        assert refused == {"regressed_without_note": 422, "internal_without_note": 422,
                           "unknown_state": 422, "group_not_in_campaign": 404}, refused
        api("POST", disclosure, {"state": "reported", "reference": "GHSA-h265-g7rm-h337",
                                 "note": "Calibration entry: the advisory is already public."})
        after_fixed = api("POST", disclosure, {"state": "fixed", "note": "Fixed in 1.37.3."})
        row = after_fixed["findings"][0]
        history = row["disclosure_history"]
        assert [entry["state"] for entry in history] == ["fixed", "reported"]
        assert all(entry["actor"] == "nv14-operator" and entry["at"] for entry in history)
        assert row["state_supported_by_evidence"] is True
        assert after_fixed["unresolved"] == [after_fixed["unresolved"][-1]]  # standing note only

        # A finding seen on one version only: `fixed` is accepted, and shown as unsupported.
        lone = api("POST", f"/arenas/{arenas['1.35.2']}/findings/manual", {
            "title": "Single-version observation (calibration)", "cwe": "CWE-639",
            "node": "target"})["finding_id"]
        second = api("POST", BASE, {"name": "Calibration: single version",
                                    "product": "vaultwarden/server"}, expected=(201,))["campaign_id"]
        api("POST", f"{BASE}/{second}/findings", {"finding_id": lone})
        unsupported = api("POST", f"{BASE}/{second}/findings/{lone}/disclosure", {"state": "fixed"})
        lone_row = unsupported["findings"][0]
        assert lone_row["disclosure"]["state"] == "fixed"
        assert lone_row["state_supported_by_evidence"] is False
        assert lone_row["comparison"]["outcome"] == "unknown"
        assert any("marked fixed, but the recorded evidence outcome is unknown" in line
                   for line in unsupported["unresolved"])
        # State is per campaign: the pair's group elsewhere starts internal.
        api("POST", f"{BASE}/{second}/findings", {"finding_id": root})
        elsewhere = {item["research_key"]: item for item in
                     api("GET", f"{BASE}/{second}")["findings"]}
        assert elsewhere[root]["disclosure"]["state"] == "internal"
        checks["disclosure_state"] = {
            "refused": refused, "history": [entry["state"] for entry in history],
            "fixed_supported_by_evidence": True,
            "single_version_fixed": {"accepted": True, "supported": False,
                                     "outcome": lone_row["comparison"]["outcome"]},
            "state_is_per_campaign": True}

        # --- reviewable bundle -------------------------------------------------------------
        bundles = f"{BASE}/{campaign}/findings/{root}/bundles"
        made = api("POST", bundles, {}, expected=(201,))
        digest, bundle = made["bundle_digest"], made["bundle"]
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        assert not [key for key in keys_in(bundle) if key in FORBIDDEN_KEYS]
        text = json.dumps(bundle)
        # Nothing the fixture treats as secret or private may appear in a default bundle.
        secrets = {"nv14-operator", OPERATOR_KEY, ADMIN_KEY, gate.AGENT_KEY, "Bearer "}
        for version in results:
            evidence = results[version]["verdict"].get("evidence")
            if isinstance(evidence, str) and len(evidence) > 12:
                secrets.add(evidence)
        assert not [value for value in secrets if value in text]
        artifacts = [(member["finding_id"], kind, item) for member in bundle["members"]
                     for kind, item in member["artifacts"].items()]
        assert len(artifacts) == 6 and all(item["digest"] and item["resolved"] is True
                                           for _, _, item in artifacts), artifacts
        # Re-resolve every digest independently, through the per-arena evidence routes.
        resolved = {}
        for member in bundle["members"]:
            for kind, item in member["artifacts"].items():
                route = ("validation-evidence" if item["store"] == "validation-evidence"
                         else "http/transactions")
                resolved[f"{member['finding_id']}:{kind}"] = status_of(
                    "GET", f"/arenas/{member['arena_id']}/{route}/{item['digest']}")
        assert set(resolved.values()) == {200}, resolved
        assert all(member["poc"]["included"] is False for member in bundle["members"])
        assert bundle["disclosure"]["state"] == "fixed"
        assert bundle["disclosure"]["state_supported_by_evidence"] is True
        assert bundle["comparison"]["outcome"] == "disappeared_under_controls"
        assert api("GET", f"{BASE}/{campaign}/bundles/{digest}") == bundle
        assert api("POST", bundles, {}, expected=(201,))["bundle_digest"] == digest  # same state
        full = api("POST", bundles, {"include_poc": True, "include_evidence": True},
                   expected=(201,))
        full_text = json.dumps(full["bundle"])
        assert full["bundle_digest"] != digest and "body_redacted" in full_text
        assert "Bearer ey" not in full_text and OPERATOR_KEY not in full_text
        checks["bundle"] = {
            "default_bundle_digest": digest, "bytes": made["bytes"],
            "artifact_digests": len(artifacts), "all_resolved_in_bundle": True,
            "re_resolved_through_arena_routes": resolved,
            "default_has_no_poc_or_evidence_body": True,
            "same_state_same_digest": True,
            "opt_in_bundle_digest": full["bundle_digest"],
            "opt_in_bundle_has_redacted_evidence": True}

        # One altered byte fails closed; putting it back restores the read.
        flip = ("from pathlib import Path; p=Path('/app/data/disclosure-bundles/%s/bundle.json'); "
                "b=bytearray(p.read_bytes()); b[len(b)//2]^=1; p.write_bytes(bytes(b))"
                % digest.split(":")[1])
        compose("exec", "-T", "orchestrator", "python", "-c", flip)
        altered = {"read": status_of("GET", f"{BASE}/{campaign}/bundles/{digest}"),
                   "regenerate": status_of("POST", bundles, {}),
                   "other_bundle": status_of("GET", f"{BASE}/{campaign}/bundles/{full['bundle_digest']}"),
                   "summary": status_of("GET", f"{BASE}/{campaign}")}
        compose("exec", "-T", "orchestrator", "python", "-c", flip)
        assert altered == {"read": 409, "regenerate": 409, "other_bundle": 200, "summary": 200}, altered
        assert api("GET", f"{BASE}/{campaign}/bundles/{digest}") == bundle
        checks["one_byte_altered"] = altered

        # --- boundaries ----------------------------------------------------------------------
        agent = {
            "create": status_of("POST", BASE, {"name": "x", "product": "y"}, key=gate.AGENT_KEY),
            "list": status_of("GET", BASE, key=gate.AGENT_KEY),
            "summary": status_of("GET", f"{BASE}/{campaign}", key=gate.AGENT_KEY),
            "add": status_of("POST", f"{BASE}/{campaign}/findings", {"finding_id": root},
                             key=gate.AGENT_KEY),
            "disclosure": status_of("POST", disclosure, {"state": "reported"}, key=gate.AGENT_KEY),
            "bundle": status_of("POST", bundles, {}, key=gate.AGENT_KEY),
            "bundle_read": status_of("GET", f"{BASE}/{campaign}/bundles/{digest}",
                                     key=gate.AGENT_KEY)}
        assert set(agent.values()) == {403}, agent
        # FR-04: the cross-arena feed is operator-only, so an agent key is refused.
        assert status_of("GET", "/events?limit=500", key=gate.AGENT_KEY) == 403
        operator_events = api("GET", "/events?limit=500")["events"]
        hidden = {"research_campaign", "campaign_finding", "campaign_disclosure", "campaign_bundle"}
        assert hidden <= {event["type"] for event in operator_events}
        checks["agent_key_refused"] = {"statuses": agent, "campaign_events_visible_to_agent": 0,
                                       "global_event_feed_status": 403}

        # Only campaign scopes grew, apart from the one manual finding recorded above.
        grown = [row for row in event_counts() if row not in events_before]
        outside = [row for row in grown if not row[0].startswith("campaign:")]
        assert outside and all(row[0] == arenas["1.35.2"] and row[1] in (
            "finding", "finding_verification") for row in outside), outside
        assert {arena: api("GET", f"/arenas/{arena}/budget") for arena in arenas.values()} == budgets_before
        assert len(api("GET", f"/deployments/{arenas['1.37.3']}/events?limit=500")["events"]) == \
            arena_events_before[arenas["1.37.3"]]
        resources = {arena: gate.inventory(arena) for arena in gate.ARENAS}
        assert not any(any(counts.values()) for counts in resources.values()), resources
        checks["no_arena_or_budget_change"] = {
            "budgets_identical": True,
            "event_rows_outside_campaign_scopes": [[row[1], int(row[2])] for row in outside],
            "explained_by": "the single-version manual finding this run recorded on the 1.35.2 arena",
            "arena_resources": resources}

        # --- console journey on the real pair ------------------------------------------------
        browser_dir = work / "browser"
        browser_dir.mkdir()
        result = subprocess.run(["node", "scripts/ui-nv14-browser-check.cjs"], cwd=ROOT, text=True,
                                capture_output=True, check=False, env={
            **os.environ, "NV_14_WEB": WEB, "NV_14_PASSWORD": PASSWORD, "NV_14_FINDING": root,
            "NV_14_SINGLE": lone, "NV_14_OUT": str(browser_dir),
            "NV_14_NAME": "Vaultwarden calibration (console)",
            "NV_14_PRODUCT": "vaultwarden/server"})
        if result.returncode:
            raise RuntimeError(f"browser: {result.stdout[-3000:]} {result.stderr[-1500:]}")
        browsed = json.loads((browser_dir / "ui-nv14-browser-check.json").read_text())
        checks["browser"] = {"result": browsed["result"], "checks": browsed["checks"],
                             "reflow": browsed["reflow"], "bundle": browsed.get("bundle")}

        # --- NV-10 backup, then a restore onto a clean instance -------------------------------
        campaigns = [item["campaign_id"] for item in api("GET", BASE + "?limit=100")["campaigns"]]
        assert len(campaigns) == 3  # two here, one made by the console journey
        before, state = state_of(campaigns)
        bundle_digests = sorted(digest for item in state.values() for digest in item["bundles"])

        def maintenance(*args):
            return compose("run", "--rm", "--no-deps", "-v", f"{work}:/recovery",
                           "-e", "NIDAVELLIR_RECOVERY_PASSPHRASE", "orchestrator", *args)
        compose("stop", *SERVICES)
        maintenance("python", "recovery.py", "backup", "/recovery/full.nvr", "--root", "/app")
        archive = work / "full.nvr"
        archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        compose("down", "--volumes", "--remove-orphans")
        STACK_ENV["NV14_SECRETS_ENCRYPTION_KEY"] = ""
        compose("up", "-d", "--wait", "postgres", "redis")
        maintenance("python", "-c", "from database import Database; Database()")
        maintenance("python", "recovery.py", "restore", "/recovery/full.nvr", "--root", "/app")
        saved = maintenance("cat", "/app/keys/recovery.env").stdout.strip()
        assert saved.startswith("SECRETS_ENCRYPTION_KEY=")
        STACK_ENV["NV14_SECRETS_ENCRYPTION_KEY"] = saved.split("=", 1)[1]
        compose("up", "-d", "--wait", *SERVICES)
        gate.wait("/health", lambda data: data.get("status") == "ok")
        after, restored = state_of(campaigns)
        assert after == before
        assert sorted(digest for item in restored.values() for digest in item["bundles"]) == bundle_digests
        assert api("GET", f"/findings/{root}")["comparison"]["outcome"] == "disappeared_under_controls"
        checks["restore_on_clean_instance"] = {
            "archive_sha256": archive_sha256, "archive_bytes": archive.stat().st_size,
            "campaigns": len(campaigns), "bundles": len(bundle_digests), "state_identical": True,
            "bundle_digests_identical": True}
        report["state_fingerprint"] = before
        report["status"] = "passed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = type(exc).__name__ + ": " + str(exc)[:3000]
        raise
    finally:
        if report["status"] != "passed":
            logs = compose("logs", "--tail", "60", "orchestrator", "worker", check=False)
            report["logs"] = (logs.stdout + logs.stderr)[-6000:]
        gate.cleanup_arenas()
        compose("down", "--volumes", "--remove-orphans", check=False)
        project = "label=com.docker.compose.project=nidavellir-nv14"
        report["stack_removed"] = not gate.run(
            "docker", "ps", "-a", "-q", "--filter", project, check=False).stdout.split()
        images = gate.run("docker", "image", "ls", "-q", "--filter", project, check=False).stdout.split()
        if images:
            gate.run("docker", "image", "rm", *sorted(set(images)), check=False)
        report["images_removed"] = not gate.run(
            "docker", "image", "ls", "-q", "--filter", project, check=False).stdout.split()
        report["arena_resources_left"] = {arena: gate.inventory(arena) for arena in gate.ARENAS}
        report["other_nidavellir_containers_unchanged"] = production == other_containers()
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        workspace.cleanup()
        print(json.dumps({"evidence": str(output), "status": report["status"]}))


if __name__ == "__main__":
    main()
