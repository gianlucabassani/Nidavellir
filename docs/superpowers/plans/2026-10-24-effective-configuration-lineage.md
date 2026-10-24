# Effective-Configuration Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an operator-controlled, secret-safe Docker-local workflow that captures effective configuration, finds the earliest known vulnerable state, and gives a bound research agent the enabling delta as a focused hypothesis.

**Architecture:** A deep `configuration_lineage` module owns profile validation, fact normalization, precedence, redaction, snapshot comparison and confidence grading. Immutable encrypted snapshot rows and append-only metadata events preserve evidence; lifecycle, setup, Docker and Git adapters supply facts through the module's small interface. REST is authoritative, while MCP exposes only a bounded agent projection of an operator-created analysis.

**Tech Stack:** Python 3.11, FastAPI/Pydantic, SQLAlchemy/Alembic, PostgreSQL/SQLite, Docker SDK, MCP/FastMCP, pytest.

**Spec:** `docs/superpowers/specs/2026-10-24-effective-configuration-lineage-design.md`

## Global Constraints

- Docker-local is the only live-supported runtime adapter; all other providers refuse runtime capture explicitly.
- Configuration profiles are declarative, versioned, operator-reviewed data with a fixed parser vocabulary; participant code never runs as a profile parser.
- Precedence is `source < build < scenario < deployment < setup < runtime`, versioned in the profile.
- Raw secret hashes are forbidden; sensitive comparisons use a lineage-scoped HMAC derived from the configured encryption key and lineage identity.
- Events, traces, public responses and agent projections contain no secret value or reusable cross-lineage equality token.
- `proven` requires matched adjacent-state replay with a refuted earlier state, confirmed later state, healthy controls and a known relevant delta.
- A crash, 5xx, source candidate or agent success statement is not exploit proof.
- Existing binding, containment, budget, stop, hidden-truth and operator-only authoring rules remain unchanged.
- Console implementation remains after UI-R4; this plan ships the complete REST/MCP backend and live CLI acceptance without reordering UI-R4.

## Review Focus

- Low-entropy secrets: `test_sensitive_fact_uses_lineage_hmac_and_never_projects_digest` must prove neither plaintext nor raw/stable cross-lineage hashes escape.
- Conflicting facts at equal precedence: `test_merge_marks_equal_precedence_conflict_unresolved` must prevent an arbitrary effective value.
- Incomplete or mutable history: `test_analysis_downgrades_when_intermediate_or_required_layer_is_missing` must never return `proven`.
- Causality with simultaneous changes: `test_analysis_keeps_multiple_enabling_candidates` must not select one field without controlled evidence.
- Cross-arena agent access: `test_agent_projection_requires_binding_and_subject_arena` must deny unrelated analyses and strip operator-only sources.

---

## Increment 1 — Lineage core and durable records

### Task 1: Pure profile, snapshot, delta and analysis module

**Files:**
- Create: `cyber-range/services/scenario-orchestrator/configuration_lineage.py`
- Modify: `cyber-range/services/scenario-orchestrator/crypto.py`
- Create: `tests/test_configuration_lineage.py`
- Modify: `tests/test_secrets.py`

**Interfaces:**
- Consumes: `lifecycle_manifest.canonical_json(value)` and `crypto.lineage_secret_hmac(value: object, *, lineage_id: str) -> str`.
- Produces: `validate_profile(profile: dict) -> dict`, `capture_snapshot(*, arena_id: str, target_identity: dict, profile: dict, facts: list[dict], stage: str, lineage_id: str, captured_at: str | None = None) -> dict`, `public_snapshot(snapshot: dict) -> dict`, `agent_snapshot(snapshot: dict) -> dict`, `compare_snapshots(before: dict, after: dict) -> dict`, and `analyze_history(*, snapshots: list[dict], observations: list[dict], research_key: str) -> dict`.

- [ ] **Step 1: Write the failing profile and normalization tests**

Add `test_validate_profile_rejects_executable_or_unknown_parser`, `test_capture_snapshot_applies_profile_precedence`, and `test_capture_snapshot_is_canonical_across_fact_order`. Assert schema `nidavellir/configuration-snapshot/v1`, canonical profile digest, fixed stage vocabulary, typed keys and identical snapshot digests for reordered input.

- [ ] **Step 2: Run the profile tests and verify failure**

Run: `pytest -q tests/test_configuration_lineage.py -k 'profile or precedence or canonical'`

Expected: FAIL because `configuration_lineage` does not exist.

- [ ] **Step 3: Implement profile validation and snapshot capture**

Accept only declarative source kinds `source_file`, `build`, `scenario_env`,
`deployment`, `setup`, and `runtime_env`; types `bool`, `int`, `string`, and
`enum`; bounded ids/keys/tags; and the fixed precedence sequence. `source_file`
permits only normalized relative paths with fixed `dotenv` or `json_pointer`
parsers and bounded selectors. Reject absolute/traversing paths, shell commands,
imports and unknown fields. Resolve effective values only across facts declared
by the profile.

- [ ] **Step 4: Write the failing secrecy and conflict tests**

Add `test_sensitive_fact_uses_lineage_hmac_and_never_projects_digest`, `test_sensitive_hmac_changes_between_lineages`, `test_sensitive_capture_refuses_when_encryption_is_disabled`, `test_merge_marks_equal_precedence_conflict_unresolved`, and `test_public_and_agent_projection_strip_hmac_and_withheld_value`.

- [ ] **Step 5: Run the secrecy tests and verify failure**

Run: `pytest -q tests/test_configuration_lineage.py -k 'sensitive or conflict or projection'`

Expected: FAIL on missing HMAC, projection and conflict behavior.

- [ ] **Step 6: Implement secret handling and projections**

Add `crypto.lineage_secret_hmac` so raw key material never leaves `crypto.py`.
Derive a comparison key with HMAC-SHA256 over
`b"nidavellir/config-lineage/v1\0" + lineage_id`; HMAC sensitive canonical
values with that derived key. Raise `ConfigurationLineageError` when encryption
is disabled. Never expose `value_hmac` from `public_snapshot` or
`agent_snapshot`; agent projection includes only key, change state, source class,
permitted source reference, security tags, completeness and confidence.

- [ ] **Step 7: Write failing delta and analysis tests**

Add `test_compare_reports_value_provenance_unknown_and_conflict_changes`, `test_analysis_proves_adjacent_refuted_then_confirmed`, `test_analysis_downgrades_when_intermediate_or_required_layer_is_missing`, `test_analysis_keeps_multiple_enabling_candidates`, and `test_analysis_never_uses_timestamp_as_history_order`.

- [ ] **Step 8: Run the delta/analysis tests and verify failure**

Run: `pytest -q tests/test_configuration_lineage.py -k 'compare or analysis'`

Expected: FAIL on missing comparison and confidence rules.

- [ ] **Step 9: Implement comparison and history analysis**

Return schemas `nidavellir/configuration-delta/v1` and `nidavellir/configuration-introduction/v1`. Require caller-provided ancestry order, matching profile keys, target lineage compatibility and structured validator observations. Emit `earliest_known_vulnerable`, `predecessor`, all enabling candidates, missing evidence and one of `proven|supported|inferred|unknown`.

- [ ] **Step 10: Run the complete pure-module tests**

Run: `pytest -q tests/test_configuration_lineage.py`

Expected: all tests pass.

- [ ] **Step 11: Commit the pure module**

```bash
git add cyber-range/services/scenario-orchestrator/configuration_lineage.py cyber-range/services/scenario-orchestrator/crypto.py tests/test_configuration_lineage.py tests/test_secrets.py
git commit -m "feat: model effective configuration lineage"
```

### Task 2: Version profiles with lifecycle recipes

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/scenario_spec.py`
- Modify: `cyber-range/services/scenario-orchestrator/lifecycle_manifest.py`
- Modify: `cyber-range/services/scenario-orchestrator/api.py`
- Modify: `tests/test_scenario_spec.py`
- Modify: `tests/test_lifecycle_reset.py`
- Create: `tests/test_configuration_capture.py`

**Interfaces:**
- Consumes: Task 1 `validate_profile` and `capture_snapshot`.
- Produces: optional `lifecycle.configuration_profile` in validated scenario v3; lifecycle recipe fields `configuration_profile` and `configuration_profile_digest`; `_capture_deployment_configuration(arena_id: str, recipe: dict) -> dict | None` in `api.py`.

- [ ] **Step 1: Write failing scenario-profile validation tests**

Test a valid profile containing a non-sensitive scenario environment fact and a sensitive runtime environment fact. Reject duplicate canonical keys, undeclared source kinds, unknown profile fields, invalid node/key names, more than 128 facts and profiles larger than 64 KiB.

- [ ] **Step 2: Run the scenario tests and verify failure**

Run: `pytest -q tests/test_scenario_spec.py -k configuration_profile`

Expected: FAIL because scenario v3 does not accept the profile.

- [ ] **Step 3: Add the bounded declarative profile schema**

Validate and normalize the profile through Task 1. Keep it under `lifecycle.configuration_profile`, so scenario review and immutable lifecycle capture version the same bytes.

- [ ] **Step 4: Write failing lifecycle capture tests**

Assert the recipe retains the normalized profile and digest, its public projection exposes only id/version/digest, deployment capture extracts only declared scenario/build facts, missing profiles yield `None`, and no environment value enters the lifecycle event.

- [ ] **Step 5: Run lifecycle capture tests and verify failure**

Run: `pytest -q tests/test_lifecycle_reset.py tests/test_configuration_capture.py`

Expected: FAIL on absent recipe/profile capture behavior.

- [ ] **Step 6: Implement recipe integration and deployment fact extraction**

Call `_capture_deployment_configuration` only after `save_lifecycle_recipe`
succeeds. Use Task 1 `crypto.lineage_secret_hmac`; do not read or decode the
encryption key in `api.py`, and do not copy secret material into event payloads.

- [ ] **Step 7: Run focused tests**

Run: `pytest -q tests/test_scenario_spec.py tests/test_lifecycle_reset.py tests/test_configuration_capture.py`

Expected: all pass.

- [ ] **Step 8: Commit lifecycle integration**

```bash
git add cyber-range/services/scenario-orchestrator/scenario_spec.py cyber-range/services/scenario-orchestrator/lifecycle_manifest.py cyber-range/services/scenario-orchestrator/api.py tests/test_scenario_spec.py tests/test_lifecycle_reset.py tests/test_configuration_capture.py
git commit -m "feat: capture deployment configuration profiles"
```

### Task 3: Encrypted persistence, migration and recovery

**Files:**
- Create: `cyber-range/services/scenario-orchestrator/migrations/versions/0011_add_configuration_snapshots.py`
- Modify: `cyber-range/services/scenario-orchestrator/models.py`
- Modify: `cyber-range/services/scenario-orchestrator/database.py`
- Modify: `cyber-range/services/scenario-orchestrator/recovery.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_recovery.py`
- Modify: `tests/test_configuration_capture.py`

**Interfaces:**
- Consumes: Task 1 snapshot and analysis dictionaries.
- Produces: `ConfigurationSnapshot` model; `db.save_configuration_snapshot(snapshot: dict) -> dict`, `db.get_configuration_snapshot(snapshot_id: str) -> dict | None`, `db.list_configuration_snapshots(arena_id: str, *, limit: int = 100, before: str | None = None) -> list[dict]`, and `db.find_configuration_snapshot_by_digest(arena_id: str, digest: str) -> dict | None`.

- [ ] **Step 1: Write failing migration and persistence tests**

Assert columns `id`, `arena_id`, `target_digest`, `stage`, `snapshot_digest`, `encrypted_payload`, `created_at`; unique `(arena_id, snapshot_digest)`; immutable duplicate save; decryption; ordering; pagination; and rejection when the same id or digest maps to different content.

- [ ] **Step 2: Run persistence tests and verify failure**

Run: `pytest -q tests/test_migrations.py tests/test_configuration_capture.py -k 'snapshot or migration'`

Expected: FAIL because the table/model methods do not exist.

- [ ] **Step 3: Implement migration, model and database methods**

Encrypt the canonical full payload with `encrypt_secret`; store only indexed metadata in plaintext. Generate snapshot ids from the first 12 hex characters of the canonical snapshot digest and reject collisions rather than overwriting.

- [ ] **Step 4: Write failing recovery tests**

Add a backup/restore round-trip with a sensitive snapshot. Tamper with its digest, encrypted payload and arena reference in separate cases and assert restore refusal.

- [ ] **Step 5: Run recovery tests and verify failure**

Run: `pytest -q tests/test_recovery.py -k configuration_snapshot`

Expected: FAIL because recovery does not validate the new records.

- [ ] **Step 6: Extend recovery validation**

Add the arena foreign-key check, decrypt/canonical digest verification, and full round-trip inclusion. Preserve offline/quiescent recovery rules.

- [ ] **Step 7: Run persistence and recovery tests**

Run: `pytest -q tests/test_migrations.py tests/test_configuration_capture.py tests/test_recovery.py`

Expected: all pass.

- [ ] **Step 8: Commit durable records**

```bash
git add cyber-range/services/scenario-orchestrator/migrations/versions/0011_add_configuration_snapshots.py cyber-range/services/scenario-orchestrator/models.py cyber-range/services/scenario-orchestrator/database.py cyber-range/services/scenario-orchestrator/recovery.py tests/test_migrations.py tests/test_recovery.py tests/test_configuration_capture.py
git commit -m "feat: persist encrypted configuration snapshots"
```

## Increment 2 — Capture, history analysis and agent access

### Task 4: Operator snapshot, comparison and analysis REST interface

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/api.py`
- Create: `tests/test_configuration_lineage_api.py`

**Interfaces:**
- Consumes: Tasks 1–3 module and database interfaces.
- Produces: `POST/GET /arenas/{id}/configuration-snapshots`, `GET /arenas/{id}/configuration-snapshots/{snapshot_id}`, `POST /configuration-lineage/compare`, `POST /configuration-lineage/analyze`, and `GET /configuration-lineage/analyses/{analysis_id}`.

- [ ] **Step 1: Write failing authorization and contract tests**

Cover operator success, agent denial for raw snapshots/compare/analyze, unknown arena/snapshot, cross-lineage refusal, bounded ordered snapshot list, idempotent capture and metadata-only audit events.

- [ ] **Step 2: Run API tests and verify failure**

Run: `pytest -q tests/test_configuration_lineage_api.py -k 'operator or raw or compare'`

Expected: 404 or import failures for the new routes.

- [ ] **Step 3: Implement raw snapshot and comparison routes**

Pydantic models use `extra="forbid"`; compare takes exactly two snapshot ids. Reads verify arena ownership through the stored arena id. Return the full decrypted snapshot only to operator/admin roles.

- [ ] **Step 4: Write failing analysis confidence tests through REST**

Exercise `proven`, `supported`, `inferred`, `unknown`, unhealthy controls, infrastructure failure, missing layer, simultaneous changes and timestamp-only unordered input.

- [ ] **Step 5: Run analysis route tests and verify failure**

Run: `pytest -q tests/test_configuration_lineage_api.py -k analysis`

Expected: FAIL because analysis persistence/projection is absent.

- [ ] **Step 6: Implement append-only analysis records**

Store a `configuration_introduction` event on the declared subject arena. Its payload contains analysis id, research key, snapshot ids/digests, confidence, candidate keys, completeness and linked validator evidence digests—never fact values/HMACs or hidden truth.

- [ ] **Step 7: Run API tests**

Run: `pytest -q tests/test_configuration_lineage_api.py`

Expected: all pass.

- [ ] **Step 8: Commit the operator interface**

```bash
git add cyber-range/services/scenario-orchestrator/api.py tests/test_configuration_lineage_api.py
git commit -m "feat: expose configuration lineage analysis"
```

### Task 5: Setup, Docker runtime and bounded Git-history adapters

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/setup_phase.py`
- Modify: `cyber-range/services/scenario-orchestrator/api.py`
- Modify: `cyber-range/services/scenario-orchestrator/providers/base.py`
- Modify: `cyber-range/services/scenario-orchestrator/providers/docker_local.py`
- Modify: `cyber-range/services/scenario-orchestrator/research_code.py`
- Modify: `tests/test_configurator_setup.py`
- Modify: `tests/test_providers.py`
- Modify: `tests/test_research_code.py`
- Modify: `tests/test_research_code_hardening.py`
- Modify: `tests/test_configuration_capture.py`

**Interfaces:**
- Consumes: profile selectors and snapshot capture from Tasks 1–4.
- Produces: `RangeProvider.observe_configuration(instance_id: str, selectors: list[dict]) -> dict`; `research_code.configuration_history(repo: Path, refs: list[str], profile: dict) -> dict`; post-setup capture and explicit runtime capture through the Task 4 POST route.

- [ ] **Step 1: Write failing setup capture tests**

Prove only approved successful setup steps declared by the profile can become
provenance for facts; rejected, failed and attacker steps remain audit history;
secret stdout/stderr never become configuration values. A setup declaration does
not become an effective observed value unless a later trusted adapter confirms it.

- [ ] **Step 2: Run setup tests and verify failure**

Run: `pytest -q tests/test_configurator_setup.py tests/test_configuration_capture.py -k post_setup`

Expected: FAIL because setup completion does not capture a snapshot.

- [ ] **Step 3: Implement post-setup fact adaptation**

Use structured non-secret setup-step metadata declared by the profile; never
parse free-form commands or output for facts. Capture after successful
`finish_setup`, associate a step only with a trusted runtime observation of the
declared key, and record explicit missing facts when no such observation exists.

- [ ] **Step 4: Write failing provider tests**

Assert Docker reads only declared container `Config.Env` names and immutable image/config metadata through the Docker SDK; refuses arbitrary paths/commands; clips counts; returns value-bearing facts only to the orchestrator; mock/libvirt/openstack defaults raise `NotImplementedError`.

- [ ] **Step 5: Run provider tests and verify failure**

Run: `pytest -q tests/test_providers.py tests/test_configuration_capture.py -k runtime_configuration`

Expected: FAIL because `observe_configuration` is absent.

- [ ] **Step 6: Implement the Docker-local runtime adapter**

Resolve only arena-labelled containers and profile-declared node/environment keys. Do not exec inside the target, read files, inspect process memory or accept participant-supplied Docker selectors.

- [ ] **Step 7: Write failing Git-history hardening tests**

Test an explicit ordered ref list, `.env` and JSON fixed parsers, relative bounded paths, byte/file/ref caps, disabled Git helpers/transports, missing commits, incomplete files and a malicious profile path. Assert history does not claim ancestry order from timestamps.

- [ ] **Step 8: Run Git adapter tests and verify failure**

Run: `pytest -q tests/test_research_code.py tests/test_research_code_hardening.py -k configuration_history`

Expected: FAIL because the adapter is absent.

- [ ] **Step 9: Implement bounded historical extraction**

Reuse `research_code.run_git` and fixed parsing code; support at most 32 explicit refs, 16 profile files and existing subprocess/output limits. Historical snapshots are partial unless every required layer is reconstructable.

- [ ] **Step 10: Run all adapter tests**

Run: `pytest -q tests/test_configurator_setup.py tests/test_providers.py tests/test_research_code.py tests/test_research_code_hardening.py tests/test_configuration_capture.py`

Expected: all pass.

- [ ] **Step 11: Commit adapters**

```bash
git add cyber-range/services/scenario-orchestrator/setup_phase.py cyber-range/services/scenario-orchestrator/api.py cyber-range/services/scenario-orchestrator/providers/base.py cyber-range/services/scenario-orchestrator/providers/docker_local.py cyber-range/services/scenario-orchestrator/research_code.py tests/test_configurator_setup.py tests/test_providers.py tests/test_research_code.py tests/test_research_code_hardening.py tests/test_configuration_capture.py
git commit -m "feat: collect configuration lineage facts"
```

### Task 6: Bound-agent lineage projection over MCP

**Files:**
- Modify: `cyber-range/services/scenario-orchestrator/api.py`
- Modify: `cyber-range/services/agent-gateway/gateway/stances.py`
- Modify: `cyber-range/services/agent-gateway/gateway/rest_client.py`
- Modify: `cyber-range/services/agent-gateway/gateway/tools.py`
- Modify: `cyber-range/services/agent-gateway/gateway/server.py`
- Modify: `tests/test_configuration_lineage_api.py`
- Modify: `tests/test_agent_gateway.py`

**Interfaces:**
- Consumes: Task 4 stored analysis and Task 1 `agent_snapshot`/agent delta projection.
- Produces: `GET /arenas/{id}/configuration-lineage/{analysis_id}` with binding checks and MCP attacker tool `get_configuration_lineage(arena_id: str, analysis_id: str) -> dict`.

- [ ] **Step 1: Write failing agent visibility tests**

Add `test_agent_projection_requires_binding_and_subject_arena`, operator-private/unpublished denial, wrong-arena 404, post-teardown authorized receipt behavior, sensitive/HMAC absence, hidden validator truth absence and unchanged budget assertions.

- [ ] **Step 2: Run visibility tests and verify failure**

Run: `pytest -q tests/test_configuration_lineage_api.py -k agent_projection`

Expected: FAIL because the projection route is absent.

- [ ] **Step 3: Implement the bounded projection route**

Require an active or retained successful actor receipt for the subject arena using existing binding/ownership patterns. Return only changed keys, source classes, permitted source refs, completeness, confidence and linked actor-visible evidence; consume no action.

- [ ] **Step 4: Write failing gateway tests**

Assert attacker registration/call/trace, defender/configurator denial, REST error forwarding, no HMAC/value in trace and no budget call.

- [ ] **Step 5: Run gateway tests and verify failure**

Run: `pytest -q tests/test_agent_gateway.py -k configuration_lineage`

Expected: FAIL because tool registration is absent.

- [ ] **Step 6: Implement REST client, tool, stance and MCP wrapper**

Keep the gateway a thin adapter. Trace only arena id, analysis id, confidence and analysis digest.

- [ ] **Step 7: Run API and gateway tests**

Run: `pytest -q tests/test_configuration_lineage_api.py tests/test_agent_gateway.py`

Expected: all pass.

- [ ] **Step 8: Commit agent access**

```bash
git add cyber-range/services/scenario-orchestrator/api.py cyber-range/services/agent-gateway/gateway/stances.py cyber-range/services/agent-gateway/gateway/rest_client.py cyber-range/services/agent-gateway/gateway/tools.py cyber-range/services/agent-gateway/gateway/server.py tests/test_configuration_lineage_api.py tests/test_agent_gateway.py
git commit -m "feat: expose configuration lineage to bound agents"
```

## Increment 3 — Real acceptance and release

### Task 7: Docker-local introduction fixture and live gate

**Files:**
- Create: `cyber-range/fixtures/config-lineage/Dockerfile`
- Create: `cyber-range/fixtures/config-lineage/app.py`
- Create: `cyber-range/fixtures/config-lineage/profile.json`
- Create: `cyber-range/fixtures/config-lineage/README.md`
- Create: `scripts/verify-configuration-lineage-live.py`
- Modify: `Makefile`
- Test: `tests/test_configuration_lineage.py`
- Test: `tests/test_configuration_lineage_api.py`

**Interfaces:**
- Consumes: Tasks 1–6 complete REST/MCP flow.
- Produces: `make verify-configuration-lineage-live` and a dated JSON verification artifact under `docs/verification/`.

- [ ] **Step 1: Add the three-state fixture and deterministic validator case**

State 1 denies the cross-account action; state 2 introduces one declared authorization misconfiguration; state 3 changes unrelated presentation configuration. Include one sensitive low-entropy environment value solely to test non-disclosure. Pin all image/build inputs.

- [ ] **Step 2: Add fixture unit tests**

Prove state 1 refutes, states 2/3 confirm, positive controls pass, reset starts clean and the profile maps only declared keys.

- [ ] **Step 3: Run fixture tests**

Run: `pytest -q tests/test_configuration_lineage.py tests/test_configuration_lineage_api.py`

Expected: all pass.

- [ ] **Step 4: Implement the isolated live verifier**

Follow existing NV live-script patterns: isolated Compose project, dedicated image tags/volumes/network, readiness, operator snapshot/history/analysis, real MCP client call, teardown and labelled-resource inventory. Record exact target/image/profile/snapshot/analysis digests and failure stages.

- [ ] **Step 5: Exercise conservative live cases**

The same run must record: proven state-1→state-2 introduction; state 3 not selected; partial history downgrade; simultaneous candidate set; failed control downgrade; false PoC target mutation refusal; wrong-arena agent denial; no secret in REST/MCP/events/traces; retained read after teardown.

- [ ] **Step 6: Run the live gate**

Run: `make verify-configuration-lineage-live`

Expected: exit 0, `confidence: proven`, revision/state 2 selected as `earliest_known_vulnerable`, all conservative cases passed, and zero labelled containers/networks/volumes/images after cleanup.

- [ ] **Step 7: Commit fixture and live gate**

```bash
git add cyber-range/fixtures/config-lineage scripts/verify-configuration-lineage-live.py Makefile tests/test_configuration_lineage.py tests/test_configuration_lineage_api.py docs/verification/configuration-lineage-live-*.json
git commit -m "test: prove configuration introduction analysis live"
```

### Task 8: Documentation, review and authoritative release gate

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/SCENARIOS.md`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `TODO.md`
- Modify: `ISSUES.md`
- Modify: `docs/JOURNAL.md`
- Create: `docs/verification/configuration-lineage-closure-2026-10-24.md`
- Create: `docs/verification/configuration-lineage-review-2026-10-24.md`

**Interfaces:**
- Consumes: all implemented interfaces and live/release evidence.
- Produces: accurate operator documentation and a closure record; no console availability claim.

- [ ] **Step 1: Document schemas, routes, MCP tool, profiles and limits**

Explain confidence semantics, earliest-known wording, secret handling, unsupported providers, profile coverage, non-proof signals and the absence of console integration pending UI-R4.

- [ ] **Step 2: Run focused backend and gateway suites**

Run: `pytest -q tests/test_configuration_lineage.py tests/test_configuration_capture.py tests/test_configuration_lineage_api.py tests/test_agent_gateway.py tests/test_recovery.py`

Expected: all pass.

- [ ] **Step 3: Run source checks**

Run: `ruff check cyber-range/services/scenario-orchestrator cyber-range/services/agent-gateway tests scripts/verify-configuration-lineage-live.py`

Expected: exit 0.

Run: `git diff --check`

Expected: exit 0.

- [ ] **Step 4: Conduct independent review and fix important findings**

Review the final diff against the approved design, with special attention to secret equality leakage, provenance/confidence overclaiming, actor/arena access, arbitrary runtime reads and recovery integrity. Record findings and fixes in the review document.

- [ ] **Step 5: Re-run the live gate after review fixes**

Run: `make verify-configuration-lineage-live`

Expected: final code passes and leaves zero labelled resources.

- [ ] **Step 6: Run the authoritative release gate**

Run: `make release-check`

Expected: Ruff and Bandit clean; SQLite and PostgreSQL suites, clean migration and API/UI/gateway smoke all pass on pinned Python 3.11.

- [ ] **Step 7: Reconcile project status from evidence**

Mark RESEARCH-W1's lineage portion complete only if the final live gate, independent review and release gate passed. Keep the broader agentic workflow open if hypothesis/recipe orchestration remains incomplete. Record files, exact verification, unresolved limits and next concrete step in `docs/JOURNAL.md`.

- [ ] **Step 8: Commit final documentation**

```bash
git add docs/API.md docs/OPERATIONS.md docs/SCENARIOS.md README.md ROADMAP.md TODO.md ISSUES.md docs/JOURNAL.md docs/verification/configuration-lineage-closure-2026-10-24.md docs/verification/configuration-lineage-review-2026-10-24.md
git commit -m "docs: record verified configuration lineage workflow"
```

