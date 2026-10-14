# Research quality phase — closure

Verified locally on 2026-10-12 (Europe/Rome). Raw timestamps use UTC.
RESEARCH-R7–R10 are remediated within the following scope. The verified branch
was published to the current GitLab origin. The GitHub suspension response during
the initial handoff check concerned the old, separately configured remote.

## Active proof

| Check | Retained result |
|---|---|
| Registered Paperless/GreenMail live probe | [Twelve rows](paperless-quality-verified-2026-10-12.json), registration commit `b059439`; every assertive control held. Eleven request-scoped refutations; H5 group management is authorized by change_user, with privilege flags unchanged. All registered source hashes match the executed final sources. |
| Real REST and MCP authoring | [Live evidence](research-code-live-2026-10-12.json): three REST answers, paged MCP answer, agent denial, two admitted failed queries, six metadata-only audit events. No fake transport or TestClient is used in this check. |
| Real Docker browser/HTTP research | [NV-09 live gate](nv09-live-2026-10-11-95d6c14c.json): scripted MCP calibration, browser/HTTP work, independent validation, reset and retained evidence; all recorded final arena resource counts are zero. This is machinery proof, not a new model-capability result. |
| Final release gate | [Raw log](research-quality-release-2026-10-12.log): Ruff passed, no medium/high Bandit findings; 1,114 SQLite tests passed, four skipped and six integrations deselected; 1,118 PostgreSQL tests passed, six integrations deselected. Python 3.11.14 migration/API/UI/gateway smoke passed. |
| Fixture teardown | Final Docker queries for paperless-fixture containers, volumes and networks returned no resources. Existing unrelated stacks were outside scope. |
| Evidence retention | Both new evidence writers reject existing output paths before starting work. Complete and intermediate inventories are retained as lossless compressed JSON. |

The probe now supplies global permissions and legitimate owned controls before
interpreting foreign-object denial. H3 uses the shared document where CHANGE is
already granted, preserving the owned control's owner. H4 tests a member-owned
document after revoking DELETE, with a separate allowed bulk-delete control.
M2 records foreign-account choice exclusion rather than treating every 400 as
denial. M4 proves a real mailbox connection. M5 sends an owned-first mixed batch
and verifies both rows survive, while a separate owned row is deleted successfully.
Concrete request inputs and identity/effect observations exclude authentication
material and text content. Failed prerequisites cannot refute; effect observations
can establish unauthorized loss. Successful responses with unchanged effects are
inconclusive. The earlier fixture JSON-banner failure and intermediate runs are
retained; they are superseded for current conclusions.

## Complete source inventory

The [summary](research-quality-inventory-summary-2026-10-12.json) links a checksummed
[complete compressed JSON artifact](research-quality-inventory-2026-10-12.json.gz).
All current totals and affected/fixed source inventories are complete within their
recorded scopes. The source ref is `6f7ed1d4a7f06c1373b84f8b606fd011e294c4b4`.

| Pattern | Retained candidate lines |
|---|---:|
| unscoped-queryset | 2,846 |
| bare-auth-view | 8 |
| bulk-permission | 5 |
| half-composed-check | 17 |
| unguarded-verb | 25 |
| field-validation | 320 |
| privilege-flags | 139 |
| template-context | 315 |
| mutation-order | 693 |

The original five inventories use src/documents and src/paperless_mail; the four
additional patterns also include src/paperless. These directories include tests
and migrations. Counts describe candidate lines, not endpoints or findings.
Nine fix shapes retain patch facts and affected/fixed inventories over all source
files changed by their fixes. File parsing limits, framework enforcement, boolean
parsing, safe template contents and mutation dominance remain explicit manual
review. No vulnerability absence or exhaustion is established.

The former Phase 1 queryset value of 459 was a byte-limited lower bound.
Continuation now follows retained sites after JSON clipping; grep has a bounded
2 MiB capture, answers remain 64 KiB, and source reads remain 256 KiB. Literal
source filenames containing Git command words are accepted without enabling
write verbs or transports. Classifying only each requested page fixes repeated
whole-inventory analysis; bare-auth syntax filtering still precedes its count.

## Audit and historical scope

Failed admitted code-intel calls retain tool, actor and HTTP status without refs,
request bodies or exception content. Focused regressions cover expected 422 and
unexpected 500 failures across all three endpoints. Authoring is explicitly
unbudgeted operator work; arena execution keeps its durable budgets. Checkout
provisioning and immutability remain operator-owned.

[Historical reconciliation](research-history-reconciliation-2026-10-11.md) keeps
unsupported old endpoint, determinism and gate assertions unverified and withdraws
the efficiency comparison. Historical files remain unchanged. Today's runs do not
certify old runs.

## Review and reproduction

Review and active verification identified and resolved global permission masking, foreign
ownership masking, effect/prerequisite confusion, inherited database configuration
and owned-control state loss. Final review reported no remaining serious finding.
Focused regression suites and the full supported gate passed.

From this branch, the registered target probe is:

```bash
python3 scripts/probe-paperless-variants.py --require-prereg b059439 --round-tag paperless-quality-verified
make release-check
make verify-nv09-live
```

Provision the source separately, then use verify-research-inventory.py with a new
output path. Run verify-research-code-live.py in the pinned verification image,
mounting the source read-only and using its owner's UID/GID to preserve Git's
ownership protection. Use --output with a new path. Do not squash or rebase away
the registration commits when integrating this branch; their ancestry is part of
the registration contract.

Next: select the [research usability proposal](../research/research-usability-next.md).
Its first slice makes controls, effects and evidence reviewable in the console.
It remains a proposal; no new console implementation is claimed.
