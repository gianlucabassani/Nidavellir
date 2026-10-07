# Research code-intel tools — spec (thin slice)

Status: spec + thin-slice build for the variant-hunt collect+derive step.
Two audiences: agent (scoped MCP tools, operator stance) and human
(operator REST endpoints + this document). No evaluation lane, no
fixtures, no driver, no NV-12/13/14.

## 2026-10-07 correction — Phase 1 contract

The independent audit is accepted. Paperless is **no confirmed vulnerability under
the tested conditions**, not exhausted; **12 retained hypotheses plus 9 asserted
without per-probe evidence** replace 21 evidence-backed refutations. The historical
inventory/efficiency estimates below are self-reported, not measured savings.

Git reads use an explicitly configured directory (unset is refused), resolved
commit refs, no external diff/textconv, no system/global config or inherited Git
environment overrides, no hooks/fsmonitor, no lazy fetch and no transport protocols.
Both pipes retain at most 65536 bytes and terminate on overflow/30-second timeout;
source AST reads have a separate 262144-byte cap. Complete JSON envelopes are
capped at 65536 bytes. Multibyte, hunk-context/evidence, file, row, input and envelope
cuts set `truncation.truncated` with a reason. `layer_diff.counts_complete` is false
on input cuts; `total_matches_complete` is false when grep output is partial.
Digests bind the exact returned metadata and facts, including those limitations.

Method definitions resolve by qualified owner and definition span, including
nested/async functions. Literal global permission arguments must match the object
permission, preserving qualified namespaces, and appear in recognized denying
conditions. Implicit object namespaces and ambiguous, conditional or unreachable
denials require manual review. `composed` means local
syntactic guard presence, not control-flow/dataflow proof. Unused calls are not
guards. `class-covered` means a framework reference requiring manual verification.
Manager-query matching covers `.objects.all/get/exclude/...`, not just filter.
Accumulator classifications: initializer / and-composed / deny-reset / overwrite.
Every `manual-review` site has a concrete `classification`, such as unparsed source,
dynamic permission arguments, bare-auth class, runtime permission override,
framework/module queryset, custom/inherited policy or unverified owner dataflow.
No candidate status implies that a vulnerability exists or is absent.

REST/MCP remain operator-only. Successful REST calls append one audit event; failed
calls currently do not. MCP traces calls; authoring budgets are not checked/charged
(RESEARCH-R10). The earlier every-call/budget assertions below are withdrawn.

## Design principle (explicit)

**Answer-shaped tools, not raw-data tools.** A tool returns the narrow
pre-computed answer ("call sites of `has_perms_owner_aware` lacking the
global half of the composition"), never a raw diff blob. If the caller
could have grepped it cheaper, the tool is wrongly shaped. Every tool
states a byte/row cap, truncates by construction, and reports truncation
instead of truncating silently.

## Phase 1 — token-waste inventory (from the two Paperless rounds)

Manual steps, with cost class and repeat count. These are historical self-reported estimates; raw manual-call/context logs were
not retained, so the inventory does not establish an efficiency ratio.

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
repo + refs. Outputs are source-derived facts; source may itself contain sensitive literals.
Operator-only access is the boundary, not a guarantee that code is secret-free.

### T1 `research_fix_lookup`

- Inputs: `fix_ref` (bounded SHA or ref, resolved to a commit, required), `advisory_id` (optional label).
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
  complete only when `counts_complete` is true; input byte cuts invalidate them.
- Replaces step 7. Saves tokens by collapsing whole-file diffs to
  permission-call deltas.
- Scope: does not judge whether a delta is a fix or a regression —
  classification stays human.

### T3 `research_sibling_search`

- Inputs: `pattern` (closed vocabulary — see below), `ref` (default
  pinned tag), `path_scope` (optional subtree).
- Named patterns (Phase 1 correction): `unscoped-queryset` recognizes manager
  methods including all/get/exclude/filter; `bare-auth-view` distinguishes bare
  classes from runtime permission overrides; `bulk-permission` distinguishes
  initializer, AND composition, deny reset and overwrite; `half-composed-check`
  compares literal global/object permission arguments in an owner-scoped function;
  `unguarded-verb` recognizes denying guards and action permission overrides.
- Output: sites (file, line, status, classification, evidence), capped at 50;
  detail/row/source/grep/envelope truncation is explicit. `total_matches_complete`
  distinguishes an exact match count from a lower bound after an input cap.
- Scope: heuristic syntax, not proof of authorization/dataflow. Every unresolved
  policy or flow remains manual review with a reason. Composition does not imply
  dominance, correct object identity or an independently verified class/caller gate.

### Surfaces and audit

- MCP (agent): three tools on the **operator stance only** (authoring-grade;
  attacker sessions must not browse repo history). Traced by the
  gateway; authoring-budget enforcement remains open (RESEARCH-R10).
- REST (human): `POST /research/code/{fix-lookup,layer-diff,sibling-search}`,
  operator-only, bounded models. Each successful call appends an audit event
  (`lab_id="research-code"`, type `research_code_lookup`: tool, refs,
  output digest, truncation flags, actor) — failed REST calls still need audit coverage (RESEARCH-R10).
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
