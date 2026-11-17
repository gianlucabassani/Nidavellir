# ADR-0011: Reproducible research sessions and shared change intelligence

- Status: Accepted
- Date: 2026-07-29

## Context

Nidavellir must support three different jobs: training on known labs,
controlled comparison of agents, and vulnerability research on current
open-source or authorized private/closed-source products. Treating them as one
leaderboard hides benchmark leakage and assigns false precision to research
targets whose unknown vulnerabilities have no complete ground truth.

Humans and agents also need the same evidence primitives. A GUI-only diff cannot
be automated; an MCP-only diff prevents analyst review and trust.

## Decision

The durable product unit is a **reproducible security research session**:
immutable target identity, declared authorization/scope/source visibility,
isolated reset point, action trace, changes, evidence, findings and replayable
result.

Training, controlled benchmark and discovery/research remain separate reporting
tracks. Only the controlled track uses hidden known-vulnerability recall as an
accuracy measure. Research reports confirmed findings, crash sites, coverage,
reproducibility and effort without pretending unknown false negatives are known.

Change intelligence is a provider capability used by REST, MCP and GUI:

- repository paths come only from provider outputs;
- attacker bindings see only an explicitly white-box, arena-scoped research
  copy; it is writable on the foothold but separate from the running target;
- configurators see writable setup source;
- Git runs with fixed argv and repository hooks, pagers, textconv and external
  diff drivers disabled;
- revisions and relative pathspecs are validated;
- output is bounded and paginated before leaving the target;
- untracked names are shown but untracked contents are not opened, avoiding
  symlink-based arbitrary reads;
- audit events retain metadata, not potentially sensitive diff bodies.

Git target intake resolves the requested branch/tag to a commit before compiling
the scenario. The target manifest stores requested and resolved refs separately,
the operator's authorization basis/scope confirmation, and the reset strategy.
An infrastructure preflight checks identity, authorization, target/foothold
health, workspace availability and reset reproducibility. Required failures stop
the pre-armed setup session from opening. REST, GUI and MCP consume the same
event-backed result.

Public OCI intake uses registry metadata only in the control plane. Tags resolve
to manifest SHA-256 digests and deployment specs contain only the digest-pinned
runtime reference. Supplied digests are verified. Registry redirects, internal
hosts, non-HTTPS token realms and private credentials are outside this slice.
The target manifest also fixes the runtime platform so an immutable
multi-architecture index cannot select different child artifacts across hosts.
The provider preserves native image startup—even for distroless artifacts—and
treats an early exit as a failed preflight instead of changing behavior with a
shell keepalive. Packaged images skip source-workspace and configurator checks.

Local source-bundle intake is a content-addressed two-step flow. The API streams
and bounds tar/tar.gz uploads, rejects traversal, links, special/sparse files,
embedded Git metadata and archive bombs, then stores both the exact-upload digest
and a sanitized canonical-tar digest atomically. It does not extract on the host.
The worker resolves only by digest, verifies the canonical payload, transfers it
through the Docker API into an arena-owned volume using a networkless helper, and
creates a safe Git baseline. Bundle build/install activity remains inside the
consent-gated target setup session.

Source change evidence exports to an arena-scoped, content-addressed patch store.
The patch body is bounded and excluded from events; events and findings retain a
verified SHA-256 reference. Staged, unstaged and untracked groups are explicit.
Untracked content is opened only by opt-in, only after the provider proves the
path is a bounded regular file, and never by following a link.

Attacker file transfer is a provider capability restricted to foothold nodes and
the fixed `/opt/nidavellir-transfer` root. Uploads and regular-file downloads are
bounded; downloads are chunked for MCP context, and both directions expose a
whole-file SHA-256 while omitting bodies from traces and audit events.

## Consequences

The first implementation supports Git-backed docker-local workspaces, immutable
Git intake, public OCI digest intake, and immutable local source-bundle intake.
Providers that cannot implement the primitive fail explicitly. Closed-source
research next requires immutable binary/installer intake,
before/after filesystem manifests and a snapshot-capable local VM provider; it
must not be simulated with a source diff.

The UI and MCP agree on what changed and on the exact exported patch identity.
Binary targets still require before/after filesystem manifests rather than a
source-diff approximation.

## Amendment 2026-11-10 — non-arena source review snapshots (UI-R4, D3)

Every store this ADR describes is arena-scoped: an identical artifact in two
arenas never grants cross-arena access, and the arena is the authorization
boundary. Source candidate review (UI-R4) does not fit that rule. Its input is
the operator-provisioned research checkout (`RESEARCH_REPO_DIR`), which belongs
to no arena, and its review state must outlive both any arena and the checkout.

Decision, approved by the operator on 2026-11-10:

- A **source review snapshot store** sits beside the evidence store at
  `DATA_DIR/source-review-snapshots/<sha256>/`. It is content-addressed and
  **not** arena-scoped. The address is the SHA-256 of the canonical snapshot
  bytes; every read re-hashes the body and fails closed on a mismatch.
- Its scope boundary is the **operator role**, not an arena. No agent stance,
  arena binding or arena key reaches it. Because nothing in it is keyed by
  arena, it must never be used to hold arena evidence.
- A snapshot is written once and never edited. It holds a frozen inventory:
  repository identity, one resolved commit SHA, the complete paged
  `sibling_search` result per chosen pattern with totals, completeness flags and
  truncation reasons, and optional declared fix links. It holds the existing
  bounded evidence line per site (at most 160 bytes), never file contents.
- Events keep to this ADR's existing rule: they hold the snapshot digest and
  metadata, never source text. Session, capture-outcome and review-state events
  are appended under the non-arena scope `source-review:<session_id>`.
- Repository identity is `repo_id` = SHA-256 over the sorted root commit SHAs
  reachable from the pinned commit, so moving the checkout directory does not
  orphan a session. A shallow checkout changes which commits are roots; the
  session records that the checkout was shallow instead of hiding it.
- The store lives under `data/`, so NV-10 backup already archives it. Backup
  additionally refuses a snapshot whose content address does not match and a
  completed capture whose snapshot is missing.
- Capture runs in a worker task, not the API request. The worker therefore
  needs the same read-only checkout mount as the API.

Unchanged: Git still runs with the fixed read-only argv of the research-code
module; nothing is cloned, fetched or written to the checkout; output stays
bounded. A snapshot is a set of syntactic candidates. It is not evidence that a
flaw exists or is absent, and no review state changes that.
