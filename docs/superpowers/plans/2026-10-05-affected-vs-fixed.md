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

## Review Focus

1. `variant_of` points at a finding whose arena was destroyed or has no recipe → the group must still read from events and return `identity.known: false`, not error.
2. A member with no stored verdict (unverified finding) → reference missing verdict forces `unknown`; a variant missing one counts as `inconclusive` and does not force `unknown`.
3. Legacy findings recorded before this feature have no `research_key` → group resolution falls back to `finding_id == root`.
4. Duplicate 12-hex finding ids across arenas (rare) → `_find_finding_event` must pick the newest deterministically.
5. An agent probing `variant_of` for another arena's id only learns existence (422 vs success) → accepted residual; the response must not expose cross-arena content.

---

### Task 1: Link findings on the write path

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/api.py` (helpers near `_finding_events` ~5062; `FindingRequest` ~5432; `_record_finding` ~5477)
- Create: `tests/test_finding_variants.py`

**Interfaces:**
- Consumes: `db.list_events(lab_id=None, limit=None, types=("finding",))` returning `{id, lab_id, ts, actor, type, payload}` newest-first; `HTTPException`; `Field`, `field_validator` already imported.
- Produces: `FindingRequest.variant_of: str | None`; `_find_finding_event(finding_id: str) -> dict | None`; finding payload keys `variant_of: str | None` and `research_key: str` (self id for a plain finding, root id for a variant).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_finding_variants.py` with an operator client fixture and a minimal `_arena(db, name)` helper (`db.create_deployment(name, name, name, provider="docker-local", actor="test")` + `db.update_deployment(name, status="active", actor="test")`), then:

```python
def test_manual_finding_links_variant_and_root(clients):
    db, operator = clients
    arena = _arena(db, "variant-root")
    root = _post_manual(operator, arena, "root claim")
    variant = _post_manual(operator, arena, "variant claim", variant_of=root)
    payloads = _finding_payloads(operator, arena)
    assert payloads[root]["research_key"] == root
    assert payloads[root]["variant_of"] is None
    assert payloads[variant]["variant_of"] == root
    assert payloads[variant]["research_key"] == root


def test_unknown_variant_of_is_rejected(clients):
    db, operator = clients
    arena = _arena(db, "variant-unknown")
    response = operator.post(f"/arenas/{arena}/findings/manual",
                             json={"title": "x", "variant_of": "0" * 12})
    assert response.status_code == 422


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
    root = _post_manual(operator, source, "root claim")
    response = operator.post(f"/arenas/{target}/findings/manual",
                             json={"title": "variant claim", "variant_of": root})
    assert response.status_code == 200
    assert set(response.json()) == {"recorded", "finding_id", "manual"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: FAIL — `variant_of` rejected/ignored, `api._find_finding_event` missing.

- [ ] **Step 3: Implement the write path**

In `api.py`:

```python
def _find_finding_event(finding_id: str) -> dict | None:
    for event in db.list_events(limit=None, types=("finding",)):
        if (event.get("payload") or {}).get("finding_id") == finding_id:
            return event
    return None
```

`FindingRequest` gains:

```python
variant_of: str | None = Field(default=None, max_length=32)

@field_validator("variant_of")
@classmethod
def _variant_id_shape(cls, v: str | None) -> str | None:
    if v is not None and not re.fullmatch(r"[0-9a-f]{12}", v):
        raise ValueError("variant_of must be a 12-hex finding id")
    return v
```

In `_record_finding`, before generating `finding_id`: when `req.variant_of` is set, resolve via `_find_finding_event`; missing → `HTTPException(status_code=422, detail="unknown variant_of finding")`; `research_key = referenced.payload.get("research_key") or req.variant_of`. In the recorded payload add `"variant_of": req.variant_of` and `"research_key": research_key or finding_id`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cyber-range/services/scenario-orchestrator/api.py tests/test_finding_variants.py
git commit -m "Link finding variants with variant_of and a research key"
```

---

### Task 2: Group read endpoint and evidence-derived outcome

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/api.py` (helpers near `_find_finding_event`; endpoint after `add_manual_finding` ~5667)
- Test: `tests/test_finding_variants.py`

**Interfaces:**
- Consumes: `db.get_lifecycle_recipe(arena_id)` recipe with `scenario_name`, `effective_provider`, `recipe_digest`, `nodes[]` (`name`, `image`, `image_pinned`, `source{repo,ref}`); `db.get_deployment(arena_id)`; `_find_finding_event`.
- Produces: `_finding_target_identity(arena_id: str) -> dict` (`{known, scenario, provider, recipe_digest, images}` where `images[name] = {image, image_pinned, source_repo, source_ref}`); `_finding_member_view(event: dict) -> dict`; `_finding_group_outcome(members: list[dict]) -> dict`; `GET /findings/{finding_id}` returning `nidavellir/finding-group/v1` exactly as the spec defines.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_finding_variants.py`. Create arenas *with* recipes via `api._record_lifecycle_recipe(name, scenario_name=name, scenario_config=SCENARIO, requested_provider="docker-local", expires_at=...)` where `SCENARIO` has one pinned node `image "sha256:" + "a"*64`. Add a local helper

```python
def _record_verdict(db, arena, finding_id, *, verdict, reason,
                    variant_of=None, research_key=None, validator_version=1):
    db.record_event(arena, "finding", {
        "finding_id": finding_id, "title": finding_id, "cwe": "CWE-639",
        "node": "target", "variant_of": variant_of, "research_key": research_key,
        "validation": {"verdict": verdict, "reason_code": reason,
                       "validator_id": "http_access_control",
                       "validator_version": validator_version,
                       "action_digest": "sha256:" + "a" * 64,
                       "observation_digest": "sha256:" + "b" * 64,
                       "control_digest": "sha256:" + "c" * 64},
    })
```

then:

```python
def test_group_outcome_disappeared_under_controls(clients, recipe_arenas):
    vuln_arena, fixed_arena = recipe_arenas
    _record_verdict(db, vuln_arena, "rootid000001", confirmed="confirmed",
                    reason="unauthorized_disclosure")
    _record_verdict(db, fixed_arena, "varid0000001", confirmed="refuted",
                    reason="access_denied", variant_of="rootid000001",
                    research_key="rootid000001")
    body = operator.get("/findings/rootid000001").json()
    assert body["schema"] == "nidavellir/finding-group/v1"
    assert body["comparison"]["outcome"] == "disappeared_under_controls"
    assert body["comparison"]["validator_comparable"] is True
    assert body["comparison"]["counts"] == {"confirmed": 1, "refuted": 1,
                                            "inconclusive": 0,
                                            "infrastructure_failure": 0}
    assert [m["arena_id"] for m in body["members"]] == [vuln_arena, fixed_arena]
    assert body["members"][0]["identity"]["known"] is True
```

Add sibling tests: `still_observed` (variant confirmed); `unknown` when an arena has no recipe; `unknown` when the reference finding has no `validation`; a variant with no verdict counted `inconclusive` without forcing `unknown`; `inconclusive` on `infrastructure_failure`; `inconclusive` with differing `validator_version`; legacy root (no `research_key`) found by `finding_id` fallback; agent key on the read endpoint → 403; unknown finding → 404.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Implement helpers and endpoint**

`_finding_target_identity`: no recipe → `{"known": False, "scenario": None, "provider": None, "recipe_digest": None, "images": {}}`; else build `images` from recipe nodes and return `known: True` with `scenario=recipe["scenario_name"]`, `provider=recipe["effective_provider"]`, `recipe_digest=recipe["recipe_digest"]`.

`_finding_member_view(event)`: `{finding_id, arena_id, scenario, title, cwe, reported_at: event["ts"], actor, variant_of, verdict: {verdict, reason_code, validator_id, validator_version, action_digest, observation_digest, control_digest}, identity}`; missing verdict → `verdict: {verdict: None, ...}`.

`_finding_group_outcome(members)`: counts where a missing verdict counts as `inconclusive`; `validators` = set of `(validator_id, validator_version)` over members with a verdict; `validator_comparable = len(validators) <= 1`; `identity_match` = `same_recipe` / `different_recipe` / `unknown`; outcome by the spec table — `unknown` when `<2` members, any `identity.known` false, or the reference (first member) has no verdict; `inconclusive` when incomparable or any `infrastructure_failure`; `still_observed` when a non-reference member is confirmed; `disappeared_under_controls` when reference confirmed and a non-reference member refuted; else `inconclusive`.

Endpoint: operator-only, 404 when `_find_finding_event(finding_id)` is None; `root = payload.research_key or finding_id`; collect events where `payload.research_key == root or payload.finding_id == root`; order root first then `ts` ascending; return the spec shape.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_finding_variants.py -q`
Expected: PASS

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

In `tests/test_agent_gateway.py::test_report_finding_forwards_verification_inputs`, add `variant_of="rootid000001"` to the call and `assert f["variant_of"] == "rootid000001"` after the existing asserts.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_gateway.py::test_report_finding_forwards_verification_inputs -q`
Expected: FAIL — `TypeError: unexpected keyword argument 'variant_of'`.

- [ ] **Step 3: Implement forwarding**

Add `variant_of: str | None = None` to the signatures in `server.py` (and pass it into `tools.report_finding`), `tools.py` (pass through), and `rest_client.py`; in `rest_client`, add `("variant_of", variant_of)` to the optional-field tuple that only sends set values.

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
- Consumes: everything from Tasks 1–3 and the existing loopback `http_access_control` fixtures (`server`, `clients`, `_arena`, `_transaction`, `_Handler`).
- Produces: proof that two real validator verdicts group into `disappeared_under_controls`; user-facing documentation.

- [ ] **Step 1: Write the failing end-to-end test**

In `tests/test_http_access_control.py`, add a test that creates the vulnerable arena (`/api/objects/vuln`) and the fixed arena (`/api/objects/fixed`) from the same loopback `server`, reports a finding in each (the fixed one with `variant_of=<vulnerable finding id>`), then asserts `GET /findings/<vulnerable id>` returns `comparison.outcome == "disappeared_under_controls"`, two members, and each member's `identity.known` is true.

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `.venv/bin/python -m pytest tests/test_http_access_control.py -q`
Expected: PASS once Tasks 1–2 are in; a failure here means the tasks do not compose — fix before continuing.

- [ ] **Step 3: Update the docs**

- `docs/API.md`: document `variant_of` on both finding write endpoints and the `GET /findings/{finding_id}` response with the outcome table.
- `README.md`: one line in the research/session feature list for affected-versus-fixed finding groups.
- `TODO.md`: extend the NV-11 entry with the implemented slice and what remains (Git-diff variant hypotheses, console surfacing).
- `docs/JOURNAL.md`: dated entry — outcome, files, verification (`make release-check` counts), unresolved risks (agents can probe finding-id existence; interface not yet surfaced in the console).

- [ ] **Step 4: Run the pinned gate**

Run: `make release-check`
Expected: exit 0; Ruff clean, Bandit zero medium/high, SQLite and PostgreSQL suites pass, smoke ready.

- [ ] **Step 5: Commit**

```bash
git add tests/test_http_access_control.py docs/API.md README.md TODO.md docs/JOURNAL.md
git commit -m "Record the affected-versus-fixed research flow"
```
