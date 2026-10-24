# Effective-configuration lineage — design

**Date:** 2026-10-24
**Status:** Approved 2026-10-24
**Roadmap item:** RESEARCH-W1
**Related:** ADR-0011, ADR-0013, ADR-0014, NV-11, NV-12

## Intent

Nidavellir must help a researcher identify, when evidence permits, the earliest
known state in which a security-relevant misconfiguration exists. The enabling
configuration delta should narrow the agent's exploit hypothesis and reduce time
spent testing unrelated paths.

This feature treats effective configuration as more than a checked-in file. It
is the combination of source defaults, immutable build inputs, scenario values,
deployment overrides, setup actions and bounded runtime observations. Conclusions
must state whether the introduction point is proven, inferred or unknown.

## Goals

1. Capture a versioned, normalized effective-configuration snapshot without
   exposing secret values.
2. Preserve provenance for every field: source default, build/image input,
   scenario, deployment override, setup action or runtime observation.
3. Compare two snapshots and isolate security-relevant changes.
4. Analyze an ordered history and identify the earliest known vulnerable state
   and its predecessor when the evidence is sufficient.
5. Feed the enabling delta and its confidence into the agentic hypothesis loop.
6. Prove introduction by replaying adjacent states under matching controls when
   both states can be reconstructed.
7. Keep incomplete history, mutable inputs and conflicting sources explicit.

## Non-goals

- Claiming that a configuration delta is exploitable without an observed effect
  and healthy controls.
- Guessing plaintext secret values or putting them in events, traces, agent
  context, URLs or public projections.
- Importing general CI/CD, cloud audit or configuration-management history in
  the first Docker-local slice.
- Automatically scanning arbitrary production systems.
- Letting an attacker-bound agent mutate victim configuration to make a PoC work.
- Replacing source-semantic review, NV-11 affected/fixed evidence or NV-12 fuzzing.

## Approaches considered

### Repository-only history

Use Git history and bisect only tracked configuration files. This is fast and
useful for source defaults, but it misses scenario values, image defaults,
environment overrides, setup mutations and runtime state. It cannot represent
the configuration that was actually tested.

### Effective-configuration lineage — selected

Combine normalized facts from all available configuration layers, retain field
provenance and compare replayable snapshots. This fits Nidavellir's immutable
target, lifecycle-recipe, append-only event and independent-validation model.
It supplies a useful answer while preserving uncertainty when some layers are
unavailable.

### Full operational-history ingestion

Import CI/CD, cloud audit, GitOps and configuration-management histories. This
can reconstruct real deployments more completely, but it creates external trust,
credential and provider dependencies beyond the current Docker-local scope. The
snapshot input interface leaves room for later reviewed adapters.

## Domain model

**Configuration fact** — one normalized key/value observation with a source
class, source reference, capture method, sensitivity and completeness state.

**Configuration profile** — a versioned, operator-reviewed declaration of the
target's supported sources, parsers, canonical keys, precedence, sensitivity and
runtime observation allowlist. A profile is target-family specific; Nidavellir
does not guess application configuration semantics.

**Effective snapshot** — the deterministic merge of configuration facts for one
target identity and arena stage. It records precedence and conflicts rather than
silently picking ambiguous values.

**Configuration delta** — added, removed or changed facts between two snapshots,
including provenance changes where the effective value is unchanged.

**Introduction analysis** — a conclusion over ordered snapshots that identifies
the first known vulnerable snapshot, its nearest known non-vulnerable predecessor,
the enabling delta and a confidence classification.

**Reproduction pair** — two freshly created arenas from adjacent snapshots with
the same probe, prerequisites and healthy controls. This is the strongest proof
that the delta introduced the observed weakness.

## Module and seam

Add a deep `configuration_lineage` module to the scenario orchestrator. Its
interface is deliberately small:

```python
capture_snapshot(target, profile, facts, stage) -> Snapshot
compare_snapshots(before, after) -> Delta
analyze_history(snapshots, observations) -> IntroductionAnalysis
```

The module owns normalization, precedence, redaction, canonical hashing,
completeness, conflicts, comparison and confidence rules. API routes, workers,
the console and MCP adapters consume its results rather than reimplementing
those rules.

Initial fact adapters are real variations behind internal seams:

- lifecycle recipe: source/build/scenario/deployment inputs;
- setup event adapter: approved victim-side configuration actions;
- Docker-local observation adapter: a strict allowlist of observable runtime
  configuration and image/container metadata;
- Git adapter: tracked configuration history for a pinned repository.

Adapters return facts; they never decide the effective result or verdict.
Every adapter is constrained by the selected configuration profile. Missing or
unsupported profile coverage becomes explicit incompleteness. Profiles are data,
not executable participant code; their schema and parser vocabulary are fixed by
the platform, and operator review is required before use.

## Snapshot schema

`nidavellir/configuration-snapshot/v1` contains:

```json
{
  "snapshot_id": "<12 hex>",
  "arena_id": "...",
  "target_identity": {"kind": "git", "digest": "..."},
  "profile": {"id": "fixture-web", "version": 1, "digest": "sha256:..."},
  "stage": "deployment|post_setup|runtime|historical_candidate",
  "facts": [{
    "key": "service.auth.registration_enabled",
    "value": true,
    "value_digest": "sha256:...",
    "value_state": "plain|withheld|unknown",
    "source_class": "source|build|scenario|deployment|setup|runtime",
    "source_ref": {"kind": "git", "ref": "...", "path": "..."},
    "precedence": 40,
    "security_tags": ["authentication"],
    "complete": true
  }],
  "conflicts": [],
  "completeness": {"status": "complete|partial", "missing_layers": []},
  "snapshot_digest": "sha256:...",
  "captured_at": "..."
}
```

Keys are namespaced and typed. Plain values are allowed only for explicitly
non-sensitive types. Sensitive or unknown fields retain the key, lineage-scoped
HMAC, presence and provenance, with `value_state: withheld`. The comparison key
is derived from the installation's encryption key and lineage identity; raw
hashes are forbidden for low-entropy values. A secret change remains detectable
across snapshots in that lineage without exposing the value or enabling
cross-target correlation. Public projections never include the HMAC;
operator-only comparison performs it server-side.
Capturing a sensitive fact fails closed when record encryption is unavailable;
Nidavellir does not fall back to plaintext storage or an unkeyed digest.

Precedence is explicit and versioned by the configuration profile. The first
fixture profile uses:

```text
source default < build/image < scenario < deployment override < setup < runtime
```

Runtime observation wins only when the adapter proves it observes the active
value. Merely finding a file or environment key records a fact without claiming
that the application consumed it. Equal-precedence disagreement becomes a
conflict and makes the affected key unresolved.

## Storage and audit

Snapshots are immutable encrypted records in a new `configuration_snapshots`
table: id, arena id, target digest, stage, snapshot digest, encrypted payload and
created time. A uniqueness constraint on `(arena_id, snapshot_digest)` makes
capture idempotent. Append-only `configuration_snapshot` events contain only the
snapshot id, target digest, stage, completeness, fact count and snapshot digest.

Introduction analyses are append-only events referencing snapshot and evidence
digests. They do not duplicate snapshot bodies. Backup/restore must include the
new table and validate every digest and arena reference. Teardown retains the
records like lifecycle recipes and findings.

## Capture points

1. **Deployment:** after the immutable lifecycle recipe is recorded, capture
   source/build/scenario/deployment facts.
2. **Post-setup:** when setup finishes, fold approved setup steps into a new
   snapshot. Failed or rejected proposals are retained as audit history but do
   not become effective facts.
3. **Runtime:** an explicit operator capture asks the Docker-local provider for
   the allowlisted observation. No participant-supplied values are trusted as
   runtime truth.
4. **Historical candidate:** the Git adapter extracts normalized facts at a
   selected commit. These snapshots are partial unless the other layers can be
   reconstructed.

No capture executes target code or consumes an arena action budget. Provider
observation is operator-only, bounded and body-safe.

## Comparison and introduction analysis

`compare_snapshots` reports effective value changes, provenance-only changes,
unknown transitions, conflicts and missing layers. Each delta has stable fact
keys and before/after source references suitable for a source diff.

`analyze_history` consumes snapshots ordered by target ancestry or an explicit
operator-supplied sequence plus independently validated observations for the
same hypothesis. It never infers order from timestamps alone.

Confidence is one of:

- `proven`: adjacent reconstructable states were replayed; the earlier state
  refuted the effect under healthy controls and the later state confirmed it;
  the relevant effective delta is known.
- `supported`: an ordered earlier state refuted and a later state confirmed,
  but intermediate states or some non-relevant configuration layers are absent.
- `inferred`: static history identifies a plausible enabling delta but no matched
  adjacent replay proves introduction.
- `unknown`: ordering, configuration, prerequisites or observations are
  insufficient or conflicting.

The output uses `earliest_known_vulnerable`, never `first_vulnerable`, unless the
complete bounded history was tested. Multiple simultaneous changes remain a set
of candidates; the module does not assign causality to one field without a
controlled replay.

## Accelerating agent research

The agent receives a bounded projection after operator authorization:

- affected target and snapshot identities;
- changed non-secret keys and source references;
- names and source classes of withheld changes;
- completeness and confidence;
- suggested source paths and runtime checks;
- linked observations and controls available to that actor.

This becomes input to a new hypothesis, not a verdict. The agent should first
test the narrow path enabled by the delta, then broaden only if evidence rejects
it. Every probe remains subject to existing binding, containment, budget and stop
controls. Operator-only source authoring, hidden truth and raw secret material
remain unavailable.

## Interfaces

First-slice operator REST interface:

```text
POST /arenas/{id}/configuration-snapshots
GET  /arenas/{id}/configuration-snapshots
GET  /arenas/{id}/configuration-snapshots/{snapshot_id}
POST /configuration-lineage/compare
POST /configuration-lineage/analyze
```

Capture accepts only a stage and adapter-specific bounded selectors; callers do
not submit arbitrary facts as observed truth. Compare accepts two snapshot ids.
Analyze accepts an ordered snapshot-id list and an existing finding/research key.

The first MCP increment is a read-only attacker tool returning the authorized
projection of an operator-created delta or analysis. Snapshot capture and
analysis creation remain operator-only. Console work follows UI-R4 rather than
changing its delivery order.

## Failure and uncertainty behavior

- Mutable or unavailable source history produces a partial snapshot.
- Missing secret values are normal; missing secret provenance is incomplete.
- A changed digest shows that a withheld value changed, not what changed.
- Unsupported providers refuse runtime capture explicitly.
- Unrelated target identities cannot be compared as one lineage unless the
  operator supplies a declared variant relationship.
- A Git commit that changes config but cannot be deployed supports only an
  inferred conclusion.
- A crash or 5xx signal does not establish exploitability or configuration
  causality.
- Failed replay, failed controls or infrastructure errors cannot produce
  `proven` or `supported` confidence.

## Security properties

- Raw snapshots are encrypted at rest using the existing record-encryption
  configuration.
- Events, traces and agent projections contain no secret values or reusable
  cross-arena secret equality token.
- Runtime collection uses a fixed allowlist; it cannot read arbitrary paths,
  process memory or the Docker socket through participant input.
- Source/debug access and attacker capabilities remain separately identified.
- Configuration mutation always creates a new snapshot and cannot rewrite the
  tested baseline.
- Analysis results remain observations until linked validators establish the
  claimed security effect.

## Acceptance journey

Use a pinned Docker-local fixture with three ordered revisions:

1. secure default;
2. a misconfiguration introduced through one declared layer;
3. an unrelated later change.

Capture all layers, verify that the secret fixture value never enters REST/MCP
payloads, events or traces, and identify revision 2 as the earliest known
vulnerable state. Replay revisions 1 and 2 from reset with the same action,
positive control and target-local observation; require refuted then confirmed
verdicts. The analysis must be `proven` and identify the enabling delta.

Then exercise conservative cases: missing intermediate revision, simultaneous
changes, conflicting equal-precedence facts, mutable input, failed control,
unsupported provider and a false PoC that changes the target. Each must downgrade
confidence or refuse the claim as specified. Records and authorized projections
must remain readable after teardown; recovery must preserve and verify them.

Backend acceptance requires focused tests, a real Docker-local REST/MCP journey,
zero residual labelled resources, independent review and `make release-check`.
Console/browser acceptance belongs to the console integration slice after UI-R4;
the backend must not be described as available in the console before that passes.

## Delivery slices

1. Pure snapshot, merge, redaction, diff and analysis module with schema tests.
2. Encrypted persistence, recovery and operator REST routes.
3. Lifecycle/setup capture and Docker-local allowlisted runtime adapter.
4. Git historical adapter and matched adjacent-state replay workflow.
5. Read-only agent projection and console integration after UI-R4.
6. Real acceptance, documentation and independent review.

No slice may claim that the feature is available until the matched Docker-local
acceptance journey and release gate pass.

