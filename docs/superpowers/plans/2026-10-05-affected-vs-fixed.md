# Affected-versus-Fixed Finding Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link findings across arenas so a researcher sees, in one call, whether a confirmed effect is gone on a fixed target version under matched controls.

**Architecture:** Findings stay the only record: an optional `variant_of` on the write path stores a shared `research_key` in the finding event payload, and one operator-only read endpoint groups events by that key, joins each arena's lifecycle recipe for a whitelisted target identity, and derives an evidence-only outcome. No new tables, no migration, no validator changes.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy events table, Pydantic, MCP `FastMCP` gateway, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-affected-vs-fixed-design.md`

## Global Constraints

- Supported verification runtime is Python 3.11; the authoritative gate is `make release-check`.
- No database migration or new dependency in this plan.
- `GET /findings/{finding_id}` is operator-only; participant/agent principals receive 403.
- Target identity exposes only scenario name, provider, recipe digest and per-node image pins — never environment values, `validation_config`, markers or credentials.
- Do not change any validator's semantics; a variant is validated in its own arena exactly like any finding.
- Repo style: follow existing patterns, no new comments beyond matching surrounding code.

## Project integration

How the pieces fit the running platform:

**Write path (existing flows, one new field).** `POST /arenas/{id}/findings` (agent,
bound to the arena) and `POST /arenas/{id}/findings/manual` (operator) both parse
`FindingRequest` and call `api._record_finding`, the single choke point that matches
the hidden manifest, runs validators, and appends the `finding` event to the
append-only `events` table. This plan resolves `variant_of` inside `_record_finding`
*before* the event is written, so the extra keys ride the same event and the same
audit actor. Scoring, `_redact_findings_for_agent`, evaluation exports and the SSE
feed all read `finding` events; they ignore unknown payload keys, so nothing else
changes. Agent-facing event reads stay redacted exactly as today.

**Read path (new).** `GET /findings/{finding_id}` is the first cross-arena research
view. It scans `finding` events (the events table is already the audit spine and
retained across teardown by NV-10), resolves the group root, orders members, and
joins `db.get_lifecycle_recipe(arena_id)` for identity. Lifecycle recipes are
written at deploy time (`api._record_lifecycle_recipe`) and retained; an arena
without one (custom/SUT) yields `identity.known: false`. The recipe's `nodes[]`
entries already carry `image`, `image_pinned` and `source{repo,ref}`; only those
fields plus `scenario_name`, `effective_provider` and `recipe_digest` are projected
out. Environment values, `validation_config`, `target` and seeds never leave the
record.

**MCP path (new field).** The attacker-stance `report_finding` tool in
`gateway/server.py` calls `gateway/tools.py`, which calls
`gateway/rest_client.py`; all three gain the optional field and the REST client
sends it only when set (matching the existing optional-field pattern). An agent can
therefore file a variant from any harness that speaks MCP without a separate
operator step.

**Data compatibility.** Findings recorded before this feature have no
`research_key`; group resolution treats the requested id as the root and also
matches `finding_id == root`, so old findings group correctly. A missing
`validation` object is a normal case (unverified finding) and never an error.

**Out of scope (no code here):** auto-deploying variants, console surfacing (lives
on `ui/royal-command`), Git-diff variant hypotheses, fuzzing. The interface is the
foundation for those layers.

## Review Focus

1. `variant_of` points at a finding whose arena was destroyed or has no recipe → the group must still read from events and return `identity.known: false`, not error.
2. A member with no stored verdict (unverified finding) → reference missing verdict forces `unknown`; a variant missing one counts as `inconclusive` and does not force `unknown`.
3. Legacy findings recorded before this feature have no `research_key` → group resolution falls back to `finding_id == root`.
4. Duplicate 12-hex finding ids across arenas (rare) → `_find_finding_event` must pick the newest deterministically (`db.list_events` is newest-first).
5. An agent probing `variant_of` for another arena's id only learns existence (422 vs success) → accepted residual; the report response must not expose cross-arena content.

---

### Task 1: Link findings on the write path

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/api.py` (helper after `_finding_events` ~5062; `FindingRequest` ~5432; `_record_finding` ~5477)
- Create: `tests/test_finding_variants.py`

**Interfaces:**
- Consumes: `db.list_events(lab_id=None, limit=None, types=("finding",))` returning `{id, lab_id, ts, actor, type, payload}` newest-first; `HTTPException`; `Field`, `field_validator` (already imported at api.py:6); `re`.
- Produces: `FindingRequest.variant_of: str | None`; `_find_finding_event(finding_id: str) -> dict | None`; finding payload keys `variant_of: str | None` and `research_key: str` (own id for a plain finding, root id for a variant).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_finding_variants.py`:

```python
"""Affected-versus-fixed finding groups (NV-11)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import auth
from database import Database


@pytest.fixture()
def clients():
    db = Database()
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name="variant-operator", role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    return db, client


def _arena(db, name):
    db.create_deployment(name, name, name, provider="docker-local", actor="test")
    db.update_deployment(name, status="active", actor="test")
    return name


def _post_manual(operator, arena, title, variant_of=None):
    body = {"title": title, "cwe": "CWE-639", "node": "target"}
    if variant_of:
        body["variant_of"] = variant_of
    return operator.post(f"/arenas/{arena}/findings/manual", json=body)


def _finding_payloads(operator, arena):
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    return {e["payload"]["finding_id"]: e["payload"]
            for e in events if e["type"] == "finding"}


def test_manual_finding_links_variant_and_root(clients):
    db, operator = clients
    arena = _arena(db, "variant-root")
    root = _post_manual(operator, arena, "root claim").json()["finding_id"]
    variant = _post_manual(operator, arena, "variant claim", variant_of=root)
    assert variant.status_code == 200, variant.text
    payloads = _finding_payloads(operator, arena)
    assert payloads[root]["research_key"] == root
    assert payloads[root]["variant_of"] is None
    assert payloads[variant.json()["finding_id"]]["variant_of"] == root
    assert payloads[variant.json()["finding_id"]]["research_key"] == root


def test_unknown_variant_of_is_rejected(clients):
    db, operator = clients
    arena = _arena(db, "variant-unknown")
    assert _post_manual(operator, arena, "x", variant_of="0" * 12).status_code == 422
    assert _post_manual(operator, arena, "x", variant_of="not-a-finding").status_code == 422


def test_find_finding_event_prefers_newest(clients):
    db, _ = clients
    db.record_event("arena-old", "finding", {"finding_id": "abc123abc123", "title": "old"})
    db.record_event("arena-new", "finding", {"finding_id": "abc123abc123", "title": "new"})
    event = api._find_finding_event("abc123abc123")
    assert event["lab_id"] == "arena-new"
    assert event["payload"]["title"] == "new"


def test_variant_reference_succeeds_across_arenas_without_leaking(clients):
    db, operator = clients
    source = _arena(db, "variant-source")
    target = _arena(db, "variant-target")
    root = _post_manual(operator, source, "root claim").json()["finding_id"]
    response = _post_manual(operator, target, "variant claim", variant_of=root)
    assert response.status_code == 200
    assert set(response.json()) == {"recorded", "finding_id", "manual"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: FAIL — `variant_of` ignored/422-misparsed and `AttributeError: module 'api' has no attribute '_find_finding_event'`.

- [ ] **Step 3: Implement the write path in `api.py`**

Add after `_finding_events`:

```python
def _find_finding_event(finding_id: str) -> dict | None:
    """Newest finding event with this id across all arenas (events are newest-first)."""
    for event in db.list_events(limit=None, types=("finding",)):
        if (event.get("payload") or {}).get("finding_id") == finding_id:
            return event
    return None
```

`FindingRequest` gains the field and shape check:

```python
    variant_of: str | None = Field(default=None, max_length=32)

    @field_validator("variant_of")
    @classmethod
    def _variant_id_shape(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[0-9a-f]{12}", v):
            raise ValueError("variant_of must be a 12-hex finding id")
        return v
```

In `_record_finding`, immediately before `finding_id = uuid.uuid4().hex[:12]`, resolve
the link (raise 422 on unknown id); then add both keys to the recorded payload:

```python
    research_key = None
    if req.variant_of:
        referenced = _find_finding_event(req.variant_of)
        if referenced is None:
            raise HTTPException(status_code=422, detail="unknown variant_of finding")
        research_key = ((referenced.get("payload") or {}).get("research_key")
                        or req.variant_of)
```

```python
            "variant_of": req.variant_of,
            "research_key": research_key or finding_id,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add cyber-range/services/scenario-orchestrator/api.py tests/test_finding_variants.py
git commit -m "Link finding variants with variant_of and a research key"
```

---

### Task 2: Group read endpoint and evidence-derived outcome

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/api.py` (helpers after `_find_finding_event`; endpoint after `add_manual_finding` ~5677)
- Test: `tests/test_finding_variants.py`

**Interfaces:**
- Consumes: `db.get_lifecycle_recipe(arena_id)` recipe with `scenario_name`, `effective_provider`, `recipe_digest`, `nodes[]` (`name`, `image`, `image_pinned`, `source{repo,ref}`); `db.list_events`; `_find_finding_event`; `_require_operator`, `require_principal`, `HTTPException`.
- Produces: `_finding_target_identity(arena_id: str) -> dict`; `_finding_member_view(event: dict) -> dict`; `_finding_group_outcome(members: list[dict]) -> dict`; `GET /findings/{finding_id}` returning `nidavellir/finding-group/v1` exactly as the spec defines.

- [ ] **Step 1: Write the failing tests**

Extend `tests/test_finding_variants.py` with the recipe fixture and helper:

```python
SCENARIO = {
    "schema": "nidavellir/v3", "name": "variant-lab",
    "network": {"segments": [{"name": "lab"}]},
    "nodes": [{"name": "target", "role": "victim", "image": "sha256:" + "a" * 64,
               "segments": ["lab"], "ports": [80]}],
    "vulnerabilities": [{"id": "acl", "title": "x", "cwe": "CWE-639", "node": "target",
        "validator": "http_access_control",
        "validation_config": {"actor": "B", "owner": "A",
            "actor_headers": {"Authorization": "Bearer b"},
            "owner_headers": {"Authorization": "Bearer a"},
            "action": {"method": "GET", "path": "/x"},
            "control": {"method": "GET", "path": "/y"},
            "forbidden_marker": "m"}}],
    "lifecycle": {"readiness": {"type": "http", "node": "target", "port": 80,
                                "path": "/health", "expected_status": 200}},
}


def _arena_with_recipe(db, name):
    arena = _arena(db, name)
    api._record_lifecycle_recipe(
        name, scenario_name=name, scenario_config=SCENARIO,
        requested_provider="docker-local",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    return arena


def _record_verdict(db, arena, finding_id, *, verdict, reason,
                    variant_of=None, research_key=None, validator_version=1,
                    validator_id="http_access_control"):
    db.record_event(arena, "finding", {
        "finding_id": finding_id, "title": finding_id, "cwe": "CWE-639",
        "node": "target", "variant_of": variant_of, "research_key": research_key,
        "validation": {"verdict": verdict, "reason_code": reason,
                       "validator_id": validator_id,
                       "validator_version": validator_version,
                       "action_digest": "sha256:" + "a" * 64,
                       "observation_digest": "sha256:" + "b" * 64,
                       "control_digest": "sha256:" + "c" * 64},
    })
```

Tests:

```python
def test_group_outcome_disappeared_under_controls(clients):
    db, operator = clients
    vuln_arena = _arena_with_recipe(db, "group-vuln")
    fixed_arena = _arena_with_recipe(db, "group-fixed")
    _record_verdict(db, vuln_arena, "rootid000001", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000001")
    _record_verdict(db, fixed_arena, "varid0000001", verdict="refuted",
                    reason="access_denied", variant_of="rootid000001",
                    research_key="rootid000001")
    body = operator.get("/findings/rootid000001").json()
    assert body["schema"] == "nidavellir/finding-group/v1"
    assert body["research_key"] == "rootid000001"
    assert [m["arena_id"] for m in body["members"]] == [vuln_arena, fixed_arena]
    assert body["members"][0]["identity"]["known"] is True
    assert body["members"][0]["identity"]["images"]["target"]["image"] == "sha256:" + "a" * 64
    assert "validation_config" not in body["members"][0]["identity"]
    assert body["comparison"] == {
        "outcome": "disappeared_under_controls", "validator_comparable": True,
        "identity_match": "same_recipe",
        "counts": {"confirmed": 1, "refuted": 1, "inconclusive": 0,
                   "infrastructure_failure": 0}}


def test_group_outcome_still_observed(clients):
    db, operator = clients
    vuln_arena = _arena_with_recipe(db, "group-still")
    fixed_arena = _arena_with_recipe(db, "group-still2")
    _record_verdict(db, vuln_arena, "rootid000010", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000010")
    _record_verdict(db, fixed_arena, "varid0000010", verdict="confirmed",
                    reason="unauthorized_disclosure", variant_of="rootid000010",
                    research_key="rootid000010")
    assert operator.get("/findings/rootid000010").json()["comparison"]["outcome"] \
        == "still_observed"


def test_group_unknown_without_recipe_or_verdict(clients):
    db, operator = clients
    no_recipe = _arena(db, "group-norecipe")          # events only, no lifecycle recipe
    _record_verdict(db, no_recipe, "rootid000020", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000020")
    _record_verdict(db, no_recipe, "varid0000020", verdict="refuted",
                    reason="access_denied", variant_of="rootid000020",
                    research_key="rootid000020")
    assert operator.get("/findings/rootid000020").json()["comparison"]["outcome"] \
        == "unknown"
    recipe_arena = _arena_with_recipe(db, "group-noverdict")
    db.record_event(recipe_arena, "finding", {
        "finding_id": "rootid000021", "title": "unverified", "research_key": None})
    assert operator.get("/findings/rootid000021").json()["comparison"]["outcome"] \
        == "unknown"


def test_group_inconclusive_cases(clients):
    db, operator = clients
    arena_a = _arena_with_recipe(db, "group-inc-a")
    arena_b = _arena_with_recipe(db, "group-inc-b")
    _record_verdict(db, arena_a, "rootid000030", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000030")
    _record_verdict(db, arena_b, "varid0000030", verdict="refuted",
                    reason="access_denied", variant_of="rootid000030",
                    research_key="rootid000030", validator_version=2)
    assert operator.get("/findings/rootid000030").json()["comparison"]["outcome"] \
        == "inconclusive"
    _record_verdict(db, arena_b, "varid0000031", verdict="infrastructure_failure",
                    reason="probe_failed", variant_of="rootid000030",
                    research_key="rootid000030")
    assert operator.get("/findings/rootid000030").json()["comparison"]["outcome"] \
        == "inconclusive"


def test_group_legacy_root_and_access_control(clients):
    db, operator = clients
    arena = _arena_with_recipe(db, "group-legacy")
    db.record_event(arena, "finding", {"finding_id": "rootid000040",
                                       "title": "legacy root"})
    _record_verdict(db, arena, "varid0000040", verdict="refuted",
                    reason="access_denied", variant_of="rootid000040",
                    research_key="rootid000040")
    body = operator.get("/findings/rootid000040").json()
    assert [m["finding_id"] for m in body["members"]] == \
        ["rootid000040", "varid0000040"]
    assert body["members"][0]["verdict"]["verdict"] is None
    assert operator.get("/findings/doesnotexist").status_code == 404

    agent_key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(agent_key), name="variant-agent", role="agent")
    agent = TestClient(api.app)
    agent.headers["X-API-Key"] = agent_key
    assert agent.get("/findings/rootid000040").status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: FAIL — 404 on `/findings/...` (route missing).

- [ ] **Step 3: Implement the read path in `api.py`**

```python
_FINDING_VERDICT_KEYS = ("verdict", "reason_code", "validator_id",
                         "validator_version", "action_digest",
                         "observation_digest", "control_digest")


def _finding_target_identity(arena_id: str) -> dict:
    """Whitelisted, operator-safe target identity for one arena."""
    recipe = db.get_lifecycle_recipe(arena_id)
    if not recipe:
        return {"known": False, "scenario": None, "provider": None,
                "recipe_digest": None, "images": {}}
    images = {}
    for node in recipe.get("nodes") or []:
        source = node.get("source") or {}
        images[node.get("name")] = {
            "image": node.get("image"),
            "image_pinned": bool(node.get("image_pinned")),
            "source_repo": source.get("repo"),
            "source_ref": source.get("ref"),
        }
    return {"known": True, "scenario": recipe.get("scenario_name"),
            "provider": recipe.get("effective_provider"),
            "recipe_digest": recipe.get("recipe_digest"), "images": images}


def _finding_member_view(event: dict) -> dict:
    payload = event.get("payload") or {}
    verdict = payload.get("validation") or {}
    identity = _finding_target_identity(event.get("lab_id"))
    return {"finding_id": payload.get("finding_id"), "arena_id": event.get("lab_id"),
            "scenario": identity.get("scenario"), "title": payload.get("title"),
            "cwe": payload.get("cwe"), "reported_at": event.get("ts"),
            "actor": event.get("actor"), "variant_of": payload.get("variant_of"),
            "verdict": {key: verdict.get(key) for key in _FINDING_VERDICT_KEYS},
            "identity": identity}


def _finding_group_outcome(members: list[dict]) -> dict:
    counts = {"confirmed": 0, "refuted": 0, "inconclusive": 0,
              "infrastructure_failure": 0}
    validators = set()
    for member in members:
        verdict = member["verdict"]
        counts[verdict["verdict"] if verdict.get("verdict") in counts
               else "inconclusive"] += 1
        if verdict.get("verdict"):
            validators.add((verdict.get("validator_id"),
                            verdict.get("validator_version")))
    comparable = len(validators) <= 1
    digests = {member["identity"]["recipe_digest"] for member in members}
    if any(not member["identity"]["known"] for member in members):
        identity_match = "unknown"
    else:
        identity_match = "same_recipe" if len(digests) == 1 else "different_recipe"
    reference, variants = members[0], members[1:]
    reference_verdict = reference["verdict"].get("verdict")
    if len(members) < 2 or reference_verdict is None:
        outcome = "unknown"
    elif not comparable or counts["infrastructure_failure"]:
        outcome = "inconclusive"
    elif any(m["verdict"].get("verdict") == "confirmed" for m in variants):
        outcome = "still_observed"
    elif reference_verdict == "confirmed" and any(
            m["verdict"].get("verdict") == "refuted" for m in variants):
        outcome = "disappeared_under_controls"
    else:
        outcome = "inconclusive"
    return {"outcome": outcome, "validator_comparable": comparable,
            "identity_match": identity_match, "counts": counts}


@app.get("/findings/{finding_id}")
def get_finding_group(finding_id: str,
                      principal: Principal = Depends(require_principal)):
    """Operator-only cross-arena view of a finding and its linked variants."""
    _require_operator(principal)
    event = _find_finding_event(finding_id)
    if event is None:
        raise HTTPException(status_code=404, detail="finding not found")
    root = (event.get("payload") or {}).get("research_key") or finding_id
    members = []
    for candidate in db.list_events(limit=None, types=("finding",)):
        payload = candidate.get("payload") or {}
        if payload.get("research_key") == root or payload.get("finding_id") == root:
            members.append(_finding_member_view(candidate))
    members.sort(key=lambda member: (member["finding_id"] != root,
                                     member["reported_at"] or ""))
    return {"schema": "nidavellir/finding-group/v1", "research_key": root,
            "reference_finding_id": root, "members": members,
            "comparison": _finding_group_outcome(members)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add cyber-range/services/scenario-orchestrator/api.py tests/test_finding_variants.py
git commit -m "Add the finding-group read with evidence-derived outcome"
```

---

### Task 3: Forward `variant_of` through the MCP gateway

**Files:**
- Modify: `cyber-range/services/agent-gateway/gateway/server.py` (~315), `gateway/tools.py` (~646), `gateway/rest_client.py` (~249)
- Test: `tests/test_agent_gateway.py` (`test_report_finding_forwards_verification_inputs`, ~365)

**Interfaces:**
- Produces: `report_finding(..., variant_of: str | None = None)` at all three layers; the REST body includes `variant_of` only when set.

- [ ] **Step 1: Write the failing assertion**

In `tests/test_agent_gateway.py::test_report_finding_forwards_verification_inputs`, add
`variant_of="rootid000001"` to the `tools.report_finding(...)` call and
`assert f["variant_of"] == "rootid000001"` after the existing asserts.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_gateway.py::test_report_finding_forwards_verification_inputs -q`
Expected: FAIL — `TypeError: report_finding() got an unexpected keyword argument 'variant_of'`.

- [ ] **Step 3: Implement forwarding**

- `gateway/server.py`: add `variant_of: str | None = None` to the nested
  `report_finding` tool signature and pass it into `tools.report_finding`.
- `gateway/tools.py`: add the parameter and pass it into
  `ctx.client.report_finding`.
- `gateway/rest_client.py`: add the parameter and extend the optional-field tuple
  to `("variant_of", variant_of)` so the body carries it only when set.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_gateway.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cyber-range/services/agent-gateway/gateway/server.py cyber-range/services/agent-gateway/gateway/tools.py cyber-range/services/agent-gateway/gateway/rest_client.py tests/test_agent_gateway.py
git commit -m "Forward variant_of through the MCP report_finding tool"
```

---

### Task 4: End-to-end variant flow, docs, and pinned gate

**Files:**
- Test: `tests/test_http_access_control.py`
- Modify: `docs/API.md`, `README.md`, `TODO.md`, `docs/JOURNAL.md`

**Interfaces:**
- Consumes: Tasks 1–3 and the existing loopback `http_access_control` fixtures (`server`, `clients`, `_arena`, `_transaction`, `_Handler`).
- Produces: proof that two real validator verdicts group into `disappeared_under_controls`; user-facing documentation.

- [ ] **Step 1: Write the end-to-end test**

Add to `tests/test_http_access_control.py`: deploy the vulnerable arena
(`/api/objects/vuln`) and the fixed arena (`/api/objects/fixed`) against the same
loopback `server`; report the vulnerable finding with `transaction_digests` and the
fixed finding with `variant_of=<vulnerable finding id>`; assert
`GET /findings/<vulnerable id>` returns `comparison.outcome ==
"disappeared_under_controls"`, two members, and `identity.known` true on both.

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_http_access_control.py -q`
Expected: PASS. A failure means Tasks 1–2 do not compose — fix before continuing.

- [ ] **Step 3: Update docs**

- `docs/API.md`: `variant_of` on both finding write endpoints; the
  `GET /findings/{finding_id}` response and outcome table.
- `README.md`: one line in the research feature list for affected-versus-fixed
  finding groups.
- `TODO.md`: extend NV-11 with the implemented slice and what remains (Git-diff
  variant hypotheses, console surfacing).
- `docs/JOURNAL.md`: dated entry — outcome, files, verification counts,
  unresolved risks (agent existence-probe residual; not yet surfaced in console).

- [ ] **Step 4: Run the pinned gate**

Run: `make release-check`
Expected: exit 0; Ruff clean, Bandit zero medium/high, SQLite and PostgreSQL
suites pass, smoke ready.

- [ ] **Step 5: Commit**

```bash
git add tests/test_http_access_control.py docs/API.md README.md TODO.md docs/JOURNAL.md
git commit -m "Record the affected-versus-fixed research flow"
```
