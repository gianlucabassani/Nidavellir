#!/usr/bin/env python3
"""UI-R4 acceptance: source candidate review on an isolated Compose stack.

Works the UI-R4 acceptance checklist (TODO.md) with
real PostgreSQL, Redis, API, Celery worker, console and two MCP gateways (project
nidavellir-ui-r4, localhost-only ports, no Docker socket). No arena
is deployed.

  UI_R4_PINNED_REPO=/path/to/paperless-ngx \
  NV_PLAYWRIGHT_MODULE=/path/to/node_modules/playwright NV_CHROMIUM_PATH=/path/to/chromium \
  python3 scripts/verify-ui-r4-live.py

The pinned checkout is provisioned by the operator and mounted read-only; nothing
here clones or fetches it. The 2026-10-12 reference counts came from two capture
scopes, so two sessions are captured with the same split. A scratch repository is
built for the incomplete-scan checks. The stack and its volumes are removed at the
end. New evidence paths refuse overwrite.
"""
from __future__ import annotations

import gzip
import hashlib
import http.cookiejar
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("nv06_gate", ROOT / "scripts/verify-nv06-live.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
gate.COMPOSE = ("docker", "compose", "--project-directory", ".", "-p", "nidavellir-ui-r4",
                "-f", "compose/acceptance/nv06.yml", "-f", "compose/acceptance/ui-r4.yml")
gate.API = "http://127.0.0.1:18014"
WEB = "http://127.0.0.1:15014"
PASSWORD = "nv06-local-only"
OPERATOR_KEY = "ui-r4-operator-key"
SERVICES = ("orchestrator", "worker", "webui", "agent-gateway", "operator-gateway")

REFERENCE = ROOT / "docs/verification/research-quality-inventory-2026-10-12.json.gz"
PINNED_SHA = "6f7ed1d4a7f06c1373b84f8b606fd011e294c4b4"
PINNED_REF = "v3.3.0"
EXPECTED = {"bare-auth-view": 8, "bulk-permission": 5, "field-validation": 320,
            "half-composed-check": 17, "mutation-order": 693, "privilege-flags": 139,
            "template-context": 315, "unguarded-verb": 25, "unscoped-queryset": 2846}
# The two capture scopes of the 2026-10-12 inventory (scripts/verify-research-inventory.py).
SESSIONS = (
    ("two-directory scope", ["src/documents/", "src/paperless_mail/"],
     ["unscoped-queryset", "bare-auth-view", "bulk-permission", "half-composed-check",
      "unguarded-verb"]),
    ("default scope", None,
     ["field-validation", "privilege-flags", "template-context", "mutation-order"]),
)
FIXES = (("F1", "b010f65ae"), ("F2", "9e9fc6213"), ("F3", "06b2d5102"), ("F4", "afaf39e43"),
         ("F5", "65ca78e9e"), ("F6", "8aab34ea7"), ("F7", "8aab34ea7"), ("F8", "c28c532be"),
         ("F9", "81795bc93"))
ROUTE = "/research/review-sessions"
# No response field may claim absence, exhaustion or safety.
CLAIM = re.compile(r"absen|exhaust|safe|secure|clean|no_vuln|not_vulnerable", re.I)

MCP_PROGRAM = r'''
import anyio, json, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/mcp") as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            out = {"tools": sorted(tool.name for tool in (await session.list_tools()).tools)}
            args = {"session_id": os.environ["R4_SESSION"], "pattern": os.environ["R4_PATTERN"]}
            result = await session.call_tool("source_review_read", arguments=args)
            out["is_error"] = bool(result.isError)
            if not result.isError:
                value = result.structuredContent or json.loads(
                    next(item.text for item in result.content if item.type == "text"))
                out["keys"] = sorted(value)
                out["snapshot_digest"] = value["session"]["snapshot_digest"]
                out["sites"] = len(value["sites"]["sites"])
                out["next_offset"] = value["sites"]["next_offset"]
            print("R4_MCP=" + json.dumps(out))
anyio.run(main)
'''


STACK_ENV: dict[str, str] = {}  # the mount, label and key the stack currently runs with


def compose(*args, env=None, check=True):
    STACK_ENV.update(env or {})
    result = subprocess.run([*gate.COMPOSE, *args], cwd=ROOT, text=True, capture_output=True,
                            check=False, env={**os.environ, **STACK_ENV})
    if check and result.returncode:
        raise RuntimeError(f"compose {args}: {result.stdout[-1500:]} {result.stderr[-1500:]}")
    return result


def api(method, path, body=None, *, key=None, expected=(200,)):
    return gate.api(method, path, body, key=key or gate.KEY, expected=expected)


def status_of(method, path, body=None, *, key=None):
    """HTTP status only, for refusal checks."""
    key = key or gate.KEY
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(gate.API + path, data=data, method=method, headers={
        "X-API-Key": key, **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:  # nosec B310 - fixed local service
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def console_session():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = opener.open(WEB + "/login", timeout=10).read().decode()  # nosec B310
    token = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', page).group(1)
    opener.open(urllib.request.Request(WEB + "/login", data=urllib.parse.urlencode({
        "username": "admin", "password": PASSWORD, "csrf_token": token}).encode()),
        timeout=10)  # nosec B310
    return opener


def console_get(opener, path):
    with opener.open(WEB + "/api/console" + path, timeout=35) as response:  # nosec B310
        return json.loads(response.read())


def pages(fetch, session_id, pattern):
    """Follow next_offset from 0 to null; return every site in order."""
    sites, offset = [], 0
    while offset is not None:
        page = fetch(f"{ROUTE}/{session_id}/sites?pattern={pattern}&offset={offset}&limit=100")
        assert page["offset"] == offset
        sites.extend(page["sites"])
        assert page["next_offset"] is None or page["next_offset"] > offset
        offset = page["next_offset"]
    return sites


def fingerprint(session_ids):
    """Everything an operator can read back: summaries and every site with its history."""
    state = {}
    for session_id in session_ids:
        summary = api("GET", f"{ROUTE}/{session_id}")
        state[session_id] = {"summary": summary, "sites": {
            item["pattern"]: pages(lambda path: api("GET", path), session_id, item["pattern"])
            for item in summary["patterns"]}}
    text = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest(), state


def wait_captured(session_id, timeout=1800):
    started = time.monotonic()
    summary = gate.wait(f"{ROUTE}/{session_id}",
                        lambda value: value.get("capture_state") != "capturing", timeout)
    return summary, round(time.monotonic() - started, 1)


def up(repo, label, *services, key=""):
    compose("up", "-d", "--wait", *services, env={
        "UI_R4_REPO_DIR": str(repo), "UI_R4_REPO_LABEL": label,
        "UI_R4_SECRETS_ENCRYPTION_KEY": key})
    gate.wait("/health", lambda value: value.get("status") == "ok")


def browser(script, out, **env):
    result = subprocess.run(["node", script], cwd=ROOT, text=True, capture_output=True, check=False,
                            env={**os.environ, "NV_R4_WEB": WEB, "NV_R4_PASSWORD": PASSWORD,
                                 "NV_R4_OUT": str(out), **env})
    if result.returncode:
        raise RuntimeError(f"{script}: {result.stdout[-3000:]} {result.stderr[-1500:]}")


def mcp(service, session_id, pattern):
    output = compose("exec", "-T", "-e", f"R4_SESSION={session_id}", "-e", f"R4_PATTERN={pattern}",
                     service, "python", "-c", MCP_PROGRAM).stdout
    return json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                           if line.startswith("R4_MCP=")))


def event_counts():
    """Events per scope and type, read straight from PostgreSQL."""
    output = compose("exec", "-T", "postgres", "psql", "-U", "nidavellir", "-d", "nidavellir_nv06",
                     "-At", "-F", "\t", "-c",
                     "select lab_id, type, count(*) from events group by 1, 2 order by 1, 2").stdout
    return [line.split("\t") for line in output.splitlines() if line]


def production_state():
    """Names and start times of containers named nidavellir-* outside this project."""
    names = gate.run("docker", "ps", "--filter", "name=^nidavellir-", "--format",
                     "{{.Names}}", check=False).stdout.split()
    names = sorted(name for name in names if not name.startswith("nidavellir-ui-r4-"))
    if not names:
        return []
    started = gate.run("docker", "inspect", "--format", "{{.Name}} {{.State.StartedAt}}",
                       *names, check=False).stdout.split("\n")
    return sorted(line for line in started if line)


def scratch_repository(root: Path):
    """A repository that exceeds the grep cap, the file cap and the diff output cap."""
    def git(*args):
        subprocess.run(["git", "-C", str(root), "-c", "user.email=t@lab.invalid",
                        "-c", "user.name=lab", *args], check=True, capture_output=True)

    def write(name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    root.mkdir()
    git("init", "-q")
    views = ("class DocumentView:\n    permission_classes = (IsAuthenticated,)\n"
             "    def get(self, request):\n        return Document.objects.filter(pk=1)\n")
    write("src/documents/views.py", views)
    for index in range(6):  # 180 sites: four pages of 50
        write(f"src/documents/module_{index}.py", f"def load_{index}():\n" + "".join(
            f"    row{line} = Document.objects.get(pk={line})\n" for line in range(30)))
    write("src/documents/wide.py",
          "def wide():\n    value = Document.objects.filter(" + "field=1, " * 60 + ")\n")
    git("add", "-A")
    git("commit", "-q", "-m", "affected")
    git("tag", "affected-1")
    write("src/documents/views.py", views + "".join(
        f"        if not request.user.has_perm('p{i}'):\n            raise PermissionDenied()\n"
        for i in range(1500)))  # a fix whose diff exceeds the 64 KiB output cap
    git("add", "-A")
    git("commit", "-q", "-m", "Fix GHSA-demo: add permission checks")
    git("tag", "fixed-1")
    write("src/paperless/flags.py", "".join(  # over the 2 MiB grep cap and the 256 KiB file cap
        f"allowed_{i:05d} = request.user.is_superuser or request.user.is_staff  # line {i:05d}\n"
        for i in range(26000)))
    git("add", "-A")
    git("commit", "-q", "-m", "large file")


def reference_sites():
    with gzip.open(REFERENCE) as handle:
        reference = json.load(handle)
    result = {}
    for item in reference["current"]:
        assert item["ref"] == PINNED_SHA and item["total_matches_complete"]
        result[item["pattern"]] = {
            "scope": item["scope"], "retained": item["retained_sites"],
            "sites": {(site["file"], site["line"]) for page in item["pages"]
                      for site in page["data"]["sites"]}}
        assert len(result[item["pattern"]]["sites"]) == item["retained_sites"]
    assert {name: item["retained"] for name, item in result.items()} == EXPECTED
    return result


def main():
    pinned = Path(os.environ["UI_R4_PINNED_REPO"]).resolve()
    assert os.environ.get("NV_PLAYWRIGHT_MODULE"), "NV_PLAYWRIGHT_MODULE is required"
    head = subprocess.run(["git", "-C", str(pinned), "rev-parse", PINNED_REF + "^{commit}"],
                          check=True, capture_output=True, text=True).stdout.strip()
    assert head == PINNED_SHA, f"{PINNED_REF} resolves to {head}"
    tag = datetime.now(timezone.utc).strftime("%Y-%m-%d-") + uuid.uuid4().hex[:8]
    output = ROOT / f"docs/verification/ui-r4-live-{tag}.json"
    with output.open("x") as handle:
        json.dump({"status": "started", "date": tag}, handle)
    report = {"schema": "nidavellir/ui-r4-live/v1", "date": tag, "status": "running",
              "pinned": {"ref": PINNED_REF, "commit": PINNED_SHA, "reference": REFERENCE.name},
              "stack": "PostgreSQL 16, Redis 7, API, Celery worker, console, attacker and "
                       "operator MCP gateways; project nidavellir-ui-r4",
              "checks": {}}
    checks = report["checks"]
    reference = reference_sites()
    production = production_state()
    passphrase = "ui-r4-" + uuid.uuid4().hex + uuid.uuid4().hex
    secret = Fernet.generate_key().decode()
    workspace = tempfile.TemporaryDirectory(prefix="ui-r4-live-")
    work = Path(workspace.name)
    empty, scratch = work / "empty", work / "scratch"
    empty.mkdir()
    scratch_repository(scratch)
    try:
        compose("down", "--volumes", "--remove-orphans", check=False,
                env={"UI_R4_REPO_DIR": str(empty)})
        compose("build", env={"UI_R4_REPO_DIR": str(empty)})
        up(pinned, "paperless-ngx", "postgres", "redis", "orchestrator", "worker", "webui",
           key=secret)
        compose("exec", "-T", "orchestrator", "python", "-c",
                "from database import Database; from auth import hash_api_key; db=Database(); "
                "db.create_api_key(hash_api_key('nv06-agent-key'),'nv06-agent','agent'); "
                f"db.create_api_key(hash_api_key('{OPERATOR_KEY}'),'ui-r4-operator','operator')")
        up(pinned, "paperless-ngx", "agent-gateway", "operator-gateway", key=secret)
        # From here every REST call uses the operator-role key, not the admin one.
        gate.KEY = OPERATOR_KEY
        events_start = event_counts()
        assert not api("GET", "/deployments")

        # --- capture: two sessions, the two scopes of the reference inventory ----
        fix_links = [{"label": f"2026-10-12 {name}", "fix_ref": ref, "affected_ref": ref + "^",
                      "fixed_ref": ref} for name, ref in FIXES]
        ids, captures, totals = [], [], {}
        for name, scope, patterns in SESSIONS:
            body = {"name": f"Acceptance: {name}", "ref": PINNED_REF, "patterns": patterns,
                    "fix_links": fix_links}
            if scope:
                body["path_scope"] = scope
            created = api("POST", ROUTE, body, expected=(202,))
            summary, seconds = wait_captured(created["session_id"])
            assert summary["capture_state"] == "complete", summary
            assert summary["complete"] is True and summary["repo_label"] == "paperless-ngx"
            # A tag is recorded as requested; the session is pinned to the full SHA.
            assert summary["commit_sha"] == PINNED_SHA and summary["requested_ref"] == PINNED_REF
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", summary["snapshot_digest"])
            assert len(summary["fix_links"]) == len(FIXES)
            ids.append(created["session_id"])
            captures.append({"session_id": created["session_id"], "name": body["name"],
                             "path_scope": summary["path_scope"], "capture_seconds": seconds,
                             "snapshot_digest": summary["snapshot_digest"],
                             "repo_id": summary["repo_id"], "patterns": [
                                 {key: item[key] for key in (
                                     "pattern", "total_matches", "total_matches_complete",
                                     "retained_sites")} for item in summary["patterns"]]})
            for item in summary["patterns"]:
                assert item["total_matches_complete"] is True
                assert item["retained_sites"] == item["total_matches"]
                totals[item["pattern"]] = item["total_matches"]
                assert (scope or None) == reference[item["pattern"]]["scope"]
        report["sessions"] = captures
        # Compared, never adjusted: a difference fails the run.
        assert totals == EXPECTED, {"captured": totals, "reference": EXPECTED}
        assert sum(totals.values()) == 4368
        checks["counts_match_reference"] = {"captured": totals, "total": sum(totals.values())}

        # --- every retained site is reachable through REST and the console -------
        opener = console_session()
        paged, machine = {}, {}
        for session_id, (_, _, patterns) in zip(ids, SESSIONS):
            for pattern in patterns:
                rest = pages(lambda path: api("GET", path), session_id, pattern)
                proxied = pages(lambda path: console_get(opener, path), session_id, pattern)
                keys = [site["site_key"] for site in rest]
                assert len(keys) == EXPECTED[pattern] and len(set(keys)) == len(keys)
                assert [site["site_key"] for site in proxied] == keys
                assert {(site["file"], site["line"]) for site in rest} == reference[pattern]["sites"]
                for site in rest:  # machine status and reason beside the operator state
                    assert site["status"] and site["classification"]
                    assert site["review"]["state"] == "unreviewed"
                paged[pattern] = len(keys)
                machine.update({item["site_key"]: (
                    item["file"], item["line"], item["status"], item["classification"],
                    item["evidence"], item["evidence_clipped"]) for item in rest})
        checks["paging_rest_and_console"] = {
            "sites_per_pattern": paged, "duplicates": 0,
            "same_file_and_line_set_as_reference": True}

        # --- no field claims absence, exhaustion or safety -----------------------
        def field_names(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from field_names(item)
            elif isinstance(value, list):
                for item in value:
                    yield from field_names(item)
        first_page = api("GET", f"{ROUTE}/{ids[0]}/sites?pattern=unscoped-queryset")
        names = sorted({*field_names(api("GET", f"{ROUTE}/{ids[0]}")), *field_names(first_page),
                        *field_names(api("GET", ROUTE))})
        assert not [name for name in names if CLAIM.search(name)], names
        checks["no_absence_field"] = {"field_names_checked": len(names)}

        # --- boundaries -----------------------------------------------------------
        site = first_page["sites"][5]["site_key"]
        review = f"{ROUTE}/{ids[0]}/sites/{site}/review"
        agent = {
            "create": status_of("POST", ROUTE, {"name": "x", "ref": PINNED_REF,
                                                "patterns": ["bare-auth-view"]}, key=gate.AGENT_KEY),
            "list": status_of("GET", ROUTE, key=gate.AGENT_KEY),
            "summary": status_of("GET", f"{ROUTE}/{ids[0]}", key=gate.AGENT_KEY),
            "sites": status_of("GET", f"{ROUTE}/{ids[0]}/sites?pattern=unscoped-queryset",
                               key=gate.AGENT_KEY),
            "review": status_of("POST", review, {"state": "in_review"}, key=gate.AGENT_KEY),
            "fix_link": status_of("GET", f"{ROUTE}/{ids[0]}/fix-links/F1", key=gate.AGENT_KEY)}
        assert set(agent.values()) == {403}, agent
        # FR-04: the cross-arena feed is operator-only, so an agent key is refused.
        assert status_of("GET", "/events?limit=500", key=gate.AGENT_KEY) == 403
        operator_events = api("GET", "/events?limit=500")["events"]
        assert any(event["type"].startswith("source_") for event in operator_events)
        checks["agent_key_refused"] = {"statuses": agent, "source_review_events_visible_to_agent": 0,
                                       "global_event_feed_status": 403}

        attacker = mcp("agent-gateway", ids[0], "unscoped-queryset")
        operator = mcp("operator-gateway", ids[0], "unscoped-queryset")
        assert "source_review_read" not in attacker["tools"] and attacker["is_error"]
        assert [name for name in operator["tools"] if "review" in name] == ["source_review_read"]
        assert operator["keys"] == ["session", "sites"] and operator["sites"] == 50
        assert operator["snapshot_digest"] == captures[0]["snapshot_digest"]
        report["operator_tools"] = operator["tools"]
        checks["mcp"] = {"attacker_has_tool": False, "attacker_call_refused": True,
                         "operator_review_tools": ["source_review_read"],
                         "operator_read": {key: operator[key] for key in (
                             "keys", "sites", "next_offset", "snapshot_digest")}}

        # --- review state rules (REST, second session) ----------------------------
        target = pages(lambda path: api("GET", path), ids[1], "mutation-order")
        base = f"{ROUTE}/{ids[1]}/sites"
        refused = {
            "dismissed_without_note": status_of("POST", f"{base}/{target[0]['site_key']}/review",
                                                {"state": "dismissed"}),
            "dismissed_short_note": status_of("POST", f"{base}/{target[0]['site_key']}/review",
                                              {"state": "dismissed", "note": "too short"}),
            "unreviewed_posted": status_of("POST", f"{base}/{target[0]['site_key']}/review",
                                           {"state": "unreviewed"}),
            "candidate_unknown_finding": status_of(
                "POST", f"{base}/{target[0]['site_key']}/review",
                {"state": "candidate", "finding_id": "0123456789ab"}),
            "unknown_site": status_of("POST", f"{base}/{'a' * 64}/review", {"state": "in_review"})}
        assert refused == {"dismissed_without_note": 422, "dismissed_short_note": 422,
                           "unreviewed_posted": 422, "candidate_unknown_finding": 422,
                           "unknown_site": 404}, refused
        for index, (state, note) in enumerate((
                ("dismissed", "REST acceptance: dismissed with a sufficient note."),
                ("in_review", "REST acceptance: in review."),
                ("candidate", "REST acceptance: candidate."))):
            api("POST", f"{base}/{target[index]['site_key']}/review", {"state": state, "note": note})
        # A second entry on one site: history keeps both, the newest decides the state.
        api("POST", f"{base}/{target[3]['site_key']}/review", {"state": "in_review"})
        api("POST", f"{base}/{target[3]['site_key']}/review",
            {"state": "dismissed", "note": "REST acceptance: second entry on the same site."})
        checks["review_rules"] = refused

        # --- console journey over the 2,846-site pattern --------------------------
        journey = Path(str(output) + ".browser.json")
        browser("scripts/ui-r4-pinned-browser-check.cjs", journey, NV_R4_SESSION=ids[0],
                NV_R4_PATTERN="unscoped-queryset", NV_R4_TOTAL=str(EXPECTED["unscoped-queryset"]),
                NV_R4_SHA=PINNED_SHA, NV_R4_REF=PINNED_REF, NV_R4_MODE="journey")
        checks["browser_journey"] = json.loads(journey.read_text())
        journey.unlink()

        marked, before = fingerprint(ids)
        # Marking sites changed no machine field of any of the 4,368 sites.
        after_marking = {item["site_key"]: (
            item["file"], item["line"], item["status"], item["classification"],
            item["evidence"], item["evidence_clipped"])
            for state in before.values() for sites in state["sites"].values() for item in sites}
        assert after_marking == machine and len(machine) == sum(EXPECTED.values())
        checks["machine_fields_unchanged_by_review"] = {"sites_compared": len(machine)}
        for session_id in ids:
            counts = {}
            for sites in before[session_id]["sites"].values():
                for item in sites:
                    counts[item["review"]["state"]] = counts.get(item["review"]["state"], 0) + 1
            assert {"dismissed", "in_review", "candidate"} <= set(counts), counts
        second = next(item for item in before[ids[1]]["sites"]["mutation-order"]
                      if item["site_key"] == target[3]["site_key"])
        assert second["review"]["state"] == "dismissed" and second["review_history_total"] == 2
        report["state_fingerprint"] = marked

        def verify_browser(label):
            path = Path(str(output) + f".{label}.json")
            browser("scripts/ui-r4-pinned-browser-check.cjs", path, NV_R4_SESSION=ids[0],
                    NV_R4_PATTERN="unscoped-queryset", NV_R4_SHA=PINNED_SHA, NV_R4_REF=PINNED_REF,
                    NV_R4_MODE="verify")
            value = json.loads(path.read_text())
            path.unlink()
            return value["checks"]

        # --- reviewing changed nothing outside the review scopes -------------------
        grown = [row for row in event_counts() if row not in events_start]
        assert grown and all(row[0].startswith("source-review:") for row in grown), grown
        assert not api("GET", "/deployments")
        checks["only_review_scopes_changed"] = {
            "event_rows_added": [[row[1], int(row[2])] for row in grown],
            "arenas_deployed": 0}

        # --- restart the API and worker containers ---------------------------------
        compose("restart", "orchestrator", "worker")
        gate.wait("/health", lambda value: value.get("status") == "ok")
        assert fingerprint(ids)[0] == marked
        checks["restart_api_and_worker"] = {"state_identical": True,
                                            "browser": verify_browser("restart")}

        # --- one altered byte fails closed ------------------------------------------
        hexdigest = captures[0]["snapshot_digest"].split(":")[1]
        flip = ("from pathlib import Path; p=Path('/app/data/source-review-snapshots/%s/snapshot.json'); "
                "b=bytearray(p.read_bytes()); b[len(b)//2]^=1; p.write_bytes(bytes(b))" % hexdigest)
        compose("exec", "-T", "orchestrator", "python", "-c", flip)
        altered = {
            "summary": status_of("GET", f"{ROUTE}/{ids[0]}"),
            "sites": status_of("GET", f"{ROUTE}/{ids[0]}/sites?pattern=unscoped-queryset"),
            "fix_link": status_of("GET", f"{ROUTE}/{ids[0]}/fix-links/F1"),
            "review": status_of("POST", review, {"state": "in_review"}),
            "mcp_read_is_error": mcp("operator-gateway", ids[0], "unscoped-queryset")["is_error"],
            "other_session": status_of("GET", f"{ROUTE}/{ids[1]}")}
        compose("exec", "-T", "orchestrator", "python", "-c", flip)  # put the byte back
        restored_read = mcp("operator-gateway", ids[0], "unscoped-queryset")
        assert restored_read["is_error"] is False and restored_read["sites"] == 50
        altered["mcp_read_after_byte_restored_is_error"] = False
        assert altered == {"summary": 409, "sites": 409, "fix_link": 409, "review": 409,
                           "mcp_read_is_error": True, "other_session": 200,
                           "mcp_read_after_byte_restored_is_error": False}, altered
        assert fingerprint(ids)[0] == marked
        checks["one_byte_altered"] = altered

        # --- the checkout goes away --------------------------------------------------
        up(empty, "", "orchestrator", "worker", key=secret)
        assert fingerprint(ids)[0] == marked
        refused_create = status_of("POST", ROUTE, {"name": "No checkout", "ref": PINNED_REF,
                                                   "patterns": ["bare-auth-view"]})
        assert refused_create == 422
        assert len(api("GET", ROUTE)["sessions"]) == 2
        checks["checkout_removed"] = {"state_identical": True, "create_status": refused_create}

        # --- incomplete scans stay visible (scratch repository) ---------------------
        up(scratch, "scratch", "orchestrator", "worker", key=secret)
        scratch_dir = work / "browser"
        scratch_dir.mkdir()
        browser("scripts/ui-r4-browser-check.cjs", scratch_dir)
        scratch_browser = json.loads((scratch_dir / "ui-r4-browser-check.json").read_text())
        listed = api("GET", ROUTE)["sessions"]
        partial = next(item for item in listed if item["name"] == "Browser check: incomplete")
        summary = api("GET", f"{ROUTE}/{partial['session_id']}")
        assert summary["capture_state"] == "complete" and summary["complete"] is False
        flags = next(item for item in summary["patterns"] if item["pattern"] == "privilege-flags")
        assert flags["total_matches_complete"] is False and flags["truncation_notes"]
        assert len(summary["unresolved"]) > 1
        unparsed = api("GET", f"{ROUTE}/{partial['session_id']}/sites?pattern=privilege-flags"
                              "&classification=unparsed-source")
        assert unparsed["filtered_total"] > 0
        assert {item["status"] for item in unparsed["sites"]} == {"manual-review"}
        link = api("GET", f"{ROUTE}/{partial['session_id']}/fix-links/F1")
        assert summary["fix_links"][0]["counts_complete"] is False
        checks["incomplete_scan"] = {
            "complete": summary["complete"], "privilege_flags": {key: flags[key] for key in (
                "total_matches", "total_matches_complete", "retained_sites", "truncation_notes")},
            "unresolved": summary["unresolved"],
            "unparsed_source_sites": unparsed["filtered_total"],
            "fix_link_counts_complete": summary["fix_links"][0]["counts_complete"],
            "fix_link_fields": sorted(link),
            "browser": {"result": scratch_browser["result"], "checks": scratch_browser["checks"],
                        "reflow": scratch_browser["reflow"]}}
        assert fingerprint(ids)[0] == marked  # the pinned sessions under another checkout
        everything = [item["session_id"] for item in listed]
        final, _ = fingerprint(everything)

        # --- NV-10 backup, then a restore onto a clean instance ----------------------
        def maintenance(*args):
            return compose("run", "--rm", "--no-deps", "-v", f"{work}:/recovery",
                           "-e", "NIDAVELLIR_RECOVERY_PASSPHRASE", "orchestrator", *args)
        STACK_ENV.update(NIDAVELLIR_RECOVERY_PASSPHRASE=passphrase, UI_R4_REPO_DIR=str(empty),
                         UI_R4_REPO_LABEL="", UI_R4_SECRETS_ENCRYPTION_KEY=secret)
        compose("stop", *SERVICES)
        maintenance("python", "recovery.py", "backup", "/recovery/full.nvr", "--root", "/app")
        bundle = work / "full.nvr"
        bundle_sha256 = hashlib.sha256(bundle.read_bytes()).hexdigest()
        compose("down", "--volumes", "--remove-orphans")
        STACK_ENV["UI_R4_SECRETS_ENCRYPTION_KEY"] = ""
        compose("up", "-d", "--wait", "postgres", "redis")
        maintenance("python", "-c", "from database import Database; Database()")
        maintenance("python", "recovery.py", "restore", "/recovery/full.nvr", "--root", "/app")
        saved = maintenance("cat", "/app/keys/recovery.env").stdout.strip()
        assert saved.startswith("SECRETS_ENCRYPTION_KEY=")
        up(empty, "", *SERVICES, key=saved.split("=", 1)[1])
        restored = [item["session_id"] for item in api("GET", ROUTE)["sessions"]]
        assert restored == everything
        assert fingerprint(everything)[0] == final and fingerprint(ids)[0] == marked
        for capture in captures:
            assert api("GET", f"{ROUTE}/{capture['session_id']}")["snapshot_digest"] == \
                capture["snapshot_digest"]
        no_checkout = status_of("POST", ROUTE, {"name": "No checkout", "ref": PINNED_REF,
                                                "patterns": ["bare-auth-view"]})
        assert no_checkout == 422  # the restored instance really has no checkout
        checks["restore_on_clean_instance"] = {
            "bundle_sha256": bundle_sha256, "bundle_bytes": bundle.stat().st_size,
            "sessions": len(restored), "state_identical": True, "snapshot_digests_identical": True,
            "create_status_without_checkout": no_checkout, "browser": verify_browser("restore")}
        assert not api("GET", "/deployments")
        checks["only_review_scopes_changed"]["arenas_at_start_middle_and_end"] = 0
        report["status"] = "passed"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = type(exc).__name__ + ": " + str(exc)[:3000]
        raise
    finally:
        STACK_ENV.setdefault("UI_R4_REPO_DIR", str(empty))
        if report["status"] != "passed":
            logs = compose("logs", "--tail", "60", "orchestrator", "worker", check=False)
            report["logs"] = (logs.stdout + logs.stderr)[-6000:]
        compose("down", "--volumes", "--remove-orphans", check=False)
        left = gate.run("docker", "ps", "-a", "-q", "--filter",
                        "label=com.docker.compose.project=nidavellir-ui-r4", check=False).stdout.split()
        report["stack_removed"] = not left
        images = gate.run("docker", "image", "ls", "-q", "--filter",
                          "label=com.docker.compose.project=nidavellir-ui-r4", check=False).stdout.split()
        if images:
            gate.run("docker", "image", "rm", *sorted(set(images)), check=False)
        report["images_removed"] = not gate.run(
            "docker", "image", "ls", "-q", "--filter",
            "label=com.docker.compose.project=nidavellir-ui-r4", check=False).stdout.split()
        # Read-only look at the other compose project on this host: same containers,
        # none restarted while this ran.
        report["other_nidavellir_containers_unchanged"] = production == production_state()
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        workspace.cleanup()
        print(json.dumps({"evidence": str(output), "status": report["status"]}))


if __name__ == "__main__":
    main()
