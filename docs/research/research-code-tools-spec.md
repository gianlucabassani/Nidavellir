# Research code-intel tools — spec (thin slice)

Status: spec + thin-slice build for the variant-hunt collect+derive step.
Two audiences: agent (scoped MCP tools, operator stance) and human
(operator REST endpoints + this document). No evaluation lane, no
fixtures, no driver, no NV-12/13/14.

## Design principle (explicit)

**Answer-shaped tools, not raw-data tools.** A tool returns the narrow
pre-computed answer ("call sites of `has_perms_owner_aware` lacking the
global half of the composition"), never a raw diff blob. If the caller
could have grepped it cheaper, the tool is wrongly shaped. Every tool
states a byte/row cap, truncates by construction, and reports truncation
instead of truncating silently.

## Phase 1 — token-waste inventory (from the two Paperless rounds)

Manual steps, with cost class and repeat count. No speculation: each row
is a step actually performed.

| # | Step | Cost | Repeats/round | Automate? |
|---|---|---|---|---|
| 1 | Advisory discovery (`gh api` advisories list) | negligible (1 call, 16 rows) | once | No — already answer-shaped |
| 2 | Fix-commit lookup (`git log --grep`) | negligible (2 calls) | once | No |
| 3 | Patch-hunk reading (`git show` × ~9, 20–130 lines each, ~600 lines) | **tokens** (all of it enters context) | per advisory | **Yes → fix_lookup** |
| 4 | Added-check classification (reasoning over each hunk) | **tokens** (reasoning, untruncated input) | per advisory | **Yes → deterministic extraction** |
| 5 | Table-row construction (manual writing) | time | per advisory | Yes (tool emits rows) |
| 6 | Sibling/call-site search (targeted greps, 15–60 line outputs, most discarded; follow-up reads of models/views/urls) | **tokens, largest share** (exploratory, high discard ratio) | per hypothesis | **Yes → sibling_search** |
| 7 | Cross-version permission awareness (which beta fixes postdate the pin) | **tokens** (full-diff reads if done by hand) | per round | **Yes → layer_diff** |
| 8 | Probe-script authoring + debug (3 iterations: JSON shape, wrong routes, classifier) | **time** dominant (each iteration ≈ a full rebuild) + tokens | per round | Partial (endpoint/route lists only; execution stays manual) |
| 9 | Auth/permission-model discovery (CSRF, token endpoint, Token scheme, global perms) | tokens + time | once per target | No — product-specific, keep manual |
| 10 | Control matrix + teardown | negligible | per round | No |

**Ranked by tokens saved if automated:** sibling_search (1st) >
fix_lookup + check extraction (2nd) > layer_diff (3rd) > probe
scaffolding (4th). Rows 1, 2, 9, 10 stay manual.

## Phase 2 — tool surface

All tools read a server-side pinned checkout (`RESEARCH_REPO_DIR`,
operator-provisioned out of band). Tools never clone/fetch/pull/push
(no egress); git verbs are allowlisted to read-only
(`log/show/grep/diff/blame/rev-parse/describe/ls-tree`) with a timeout
and a byte cap. Every tool returns `{data, digest, truncation,
provenance}` where `digest` is sha256 over canonical JSON (outputs are
digest-bound), `truncation` reports caps/hits, and `provenance` names
repo + refs. Secret-free by construction: inputs are refs/patterns,
outputs are code facts.

### T1 `research_fix_lookup`

- Inputs: `fix_ref` (40-hex SHA, required), `advisory_id` (optional label).
- Output: subject, files changed, Python-file hunks (capped), extracted
  added permission calls (`has_perms_owner_aware`,
  `get_objects_for_user_owner_aware`, `has_perm`, permission_classes,
  `validate_*`), and a deterministic one-line check summary templated
  from the extraction, e.g. "added `has_perms_owner_aware(view_document)`
  gate in `ShareLinkSerializer.validate_document`".
- Replaces manual steps 3–5. Saves tokens by returning ~15 fact lines
  instead of the ~130-line raw hunk.
- Scope: single commit, Python files. Evidence: commit SHA + digest of
  output in the audit trace.

### T2 `research_layer_diff`

- Inputs: `from_ref`, `to_ref` (SHAs or tags), `paths` (default:
  documents permission + views + serialisers + mail views; bounded
  list, max 8).
- Output: per-file added/removed permission-call counts, added check
  sites (function + call, capped at 20, truncation reported), totals
  always complete even when sites truncate.
- Replaces step 7. Saves tokens by collapsing whole-file diffs to
  permission-call deltas.
- Scope: does not judge whether a delta is a fix or a regression —
  classification stays human.

### T3 `research_sibling_search`

- Inputs: `pattern` (closed vocabulary — see below), `ref` (default
  pinned tag), `path_scope` (optional subtree).
- Named patterns (v2): `unscoped-queryset` (bare `.objects.filter(`
  call sites in views/serialisers with per-function composition status:
  covered/uncovered by an owner-aware call in the same function);
  `bare-auth-view` (view classes with bare `IsAuthenticated`);
  `bulk-permission` (assignments to the bulk `has_perms` accumulator:
  initializer / AND-composed / overwrite); `half-composed-check` (F6/F7
  shape: `has_perms_owner_aware` sites whose enclosing function lacks the
  global half → not composed); `unguarded-verb` (F1/F5 shape:
  `@action`-decorated methods with neither a body check nor an
  object-permission class on the enclosing view → not composed).
- Output: sites (file, function/line, status, one evidence line each,
  capped at 50, truncation reported) — never file dumps.
- Replaces step 6. Saves tokens by returning only sites with verdicts
  instead of grep output plus follow-up reads.
- Scope: heuristic text/AST analysis, reported as such — a site marked
  `uncovered` is a candidate, not a finding. Composition analysis is
  function-scoped; cross-function flows are out of scope and stated so.

### Surfaces and audit

- MCP (agent): three tools on the **operator stance only** (authoring-grade;
  attacker sessions must not browse repo history). Auto-traced by the
  gateway; budget-checked like other tools.
- REST (human): `POST /research/code/{fix-lookup,layer-diff,sibling-search}`,
  operator-only, bounded models. Each call appends an audit event
  (`lab_id="research-code"`, type `research_code_lookup`: tool, refs,
  output digest, truncation flags, actor) — every tool call lands in the
  audit trace on both surfaces.
- Console page: deferred — REST JSON is the human view in this slice; a
  console page over the same endpoints is a trivial follow-up.

### Explicit non-goals (thin slice)

No advisory ingestion (IDs are inputs), no LLM check classification (deterministic
extraction only), no probe execution, no campaign/hypothesis records (NV-14),
no console page, no repo provisioning (operator clones out of band).

## Acceptance mapping

Mail collect+derive through the new surface: mail fix rows (7qqc, 96jx,
bulk-mail-delete) via T1 + sibling candidates via T3, compared against
the manual round's call/line cost. No mail probes (SMTP sink is the known
prerequisite, next pass).
