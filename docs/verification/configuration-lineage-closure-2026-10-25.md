# Effective-configuration lineage — backend delivery

The approved lineage direction is implemented through operator REST and a
read-only attacker MCP projection. It captures immutable configuration snapshots,
retains provenance, compares effective changes, and identifies the earliest known
vulnerable state within an explicitly selected experiment history.

Profiles are bounded declarative data with canonical keys, types, sensitivity,
source selectors and precedence. Snapshot payloads are encrypted; sensitive
values use lineage-scoped HMACs which are removed from public projections.
Unknown sensitivity is withheld, and profile deployment without record encryption
is refused before recipe storage. Equal-precedence disagreement remains unresolved.

Source history reads locally provisioned immutable Git objects using the existing
hardened read-only runner, fixed dotenv/JSON-pointer parsers and bounded refs/files/
bytes. Parents and omitted history stay explicit. Static candidates do not become
runtime vulnerability verdicts. No automatic Git bisect or production audit-log
ingestion is delivered.

Docker environment metadata is supplied input rather than proof that an application
consumed it. Complete runtime coverage requires an instrumented target's fixed
localhost active-value readback. Successful labelled setup steps can supply
provenance only when that readback confirms the declared setting. Uninstrumented
or unsupported layers remain partial. The fixed reader is trusted operator
observation following the existing independent-validator convention; it never
runs a profile-supplied command or URL.

Analysis derives verdicts from retained action/control/effect evidence. `proven`
requires matched probes and control plans, refuted predecessor/confirmed successor,
complete relevant facts, successful reset receipts and unchanged runtime integrity.
It certifies the bounded tested configuration transition, not a global first
upstream commit, deployment date, or universal exploitability claim. Incomplete
reconstruction lowers confidence; static evidence is inferred. Multiple changed
keys remain a candidate set with no asserted single causal key.

## Live acceptance

[The final expanded report](configuration-lineage-live-2026-10-25-3750717d.json)
records real Docker-local deployment, reset and independent validation:

- Secure state refuted the cross-account action; the misconfigured successor
  confirmed it. An unrelated later state was not selected as the introduction.
- Active readback, encryption-safe projection and labelled setup provenance passed.
- Real MCP read returned the enabling key; the expanded REST projection retained
  direction, source references and completeness. Reads did not consume action budget.
- Failed controls and conflicting readbacks returned `unknown`; missing runtime
  facts/history and target mutation returned `supported`; unresolved mutable image
  input was refused by the existing deployment guard.
- Simultaneous declared changes retained both candidate keys and no single causal key.
- Private raw reads and wrong-arena access were refused. Snapshot and analysis
  reads, including the published agent projection, survived teardown.
- All ten invocation-owned arenas have zero labelled containers, networks,
  volumes and images. Service volumes/network were removed with the isolated stack.

The earlier basic pass is retained separately in
`configuration-lineage-live-2026-10-25-438b4097.json`. Failed attempts remain labelled:
`e5febbf4` exposed missing clean-image template directories; `5e7d1a72` exposed an
unchanged-state harness expectation; `d54d23b9` exhausted host subnet pools;
`0ac2ec8b` exercised the existing unresolved-image guard instead of the expected
runtime downgrade. They are not acceptance passes and record their cleanup.

## Release and review

Final [`make release-check` log](configuration-lineage-release-2026-10-25.log)
exited zero on Python 3.11.14: Ruff passed, Bandit reported no issues,
SQLite **1,186 passed / four skipped / six deselected**, PostgreSQL
**1,190 passed / six deselected**. Clean migrations and API/UI/gateway readiness
smokes passed. The `.log.gz` sibling retains the original log bytes; the text
copy removes terminal trailing whitespace. A final fail-closed deployment guard
and unknown-sensitivity regression are included in this release gate; both are
outside the successful live fixture's explicitly configured/encrypted path.
[Independent review and the regression fixes](configuration-lineage-review-2026-10-25.md)
describe the Important findings and their resolution. Focused tests cover
normalization, missing facts, keyed secrecy, confidence, profiles, ownership,
storage, migrations, recovery, adapters and gateway behavior.

## Remaining scope

This is synthetic calibration proof of workflow. Docker-local is the live provider
boundary. Full video/transcript inspection, generic deployment-override adapters,
arbitrary target runtime semantics, automatic investigation coordination and
reusable research recipes remain outside this backend slice. Historical source
inspection does not itself prove which commit first became exploitable.
Console integration remains after UI-R4; NV-12 fuzzing remains open. The broader
RESEARCH-W1 workflow is not closed by this delivery. Existing Paperless historical
proof gaps are unchanged.

Local base, fixture and dedicated service build images are retained as build
cache. They are not running infrastructure and are not included in the zero
arena-labelled resource claim. No unrelated host Docker resource was pruned.
