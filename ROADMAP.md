# Roadmap

> **North star:** Nidavellir is the GUI-driven, bring-your-own-agent arena for
> security work on real running systems. It provisions a reproducible target,
> gives a human or agent a contained research position, observes what really
> happened, verifies evidence, and turns the session into a replayable result.
>
> That substrate serves **two objectives on one engine**:
>
> - **Discovery** — find real, previously unknown vulnerabilities in real
>   products, with reproducible setup, evidence-grade proof, and a
>   disclosure-ready record. Here the **target** is under test and the
>   participant, human or agent, is the instrument.
> - **Evaluation** — measure and compare complete agent builds over held-out
>   challenges. Here the **AI** is under test and Nidavellir is the environment,
>   capability boundary, observer, referee, and comparison layer.
>
> Neither is a side product of the other. They share the arena, gateway, event
> spine, evidence, validation, and scoring substrate, and they are sequenced so
> that discovery work produces the verified, held-out material that makes
> evaluation credible.

## Current delivery order — updated 2026-09-24

[TODO.md](TODO.md) is the canonical ordered checklist with stable NV task IDs,
dependencies and acceptance criteria. This roadmap retains product/design detail;
S/C/R/D/E/P labels below are subject areas, not a competing execution order.
The operator requested this reorganization after reviewing both Nidavellir and Bughunt.
NV-01–06 have completed their accepted gates; NV-07 is next.

1. **P0 / NV-01–05:** restore a repeatable Python 3.11 release gate; prove pinned target
   lifecycle/reset; complete confined PoC execution, durable budgets/stop and scoped access.
2. **P1 / NV-06–10:** strengthen independent validation; persist experiments and paired
   trials; maintain a small challenge library; prove usefulness with a Bughunt workflow;
   restore research/evaluation records on a clean installation.
3. **P2 / NV-11–15:** affected-versus-fixed replay, targeted variant/fuzzing work,
   binary/local VM intake and research campaign/disclosure output as concrete targets need
   them; held-out comparison and active episodes follow suitable evidence.

Discovery and evaluation remain first-class objectives. One local calibration workflow
can prove operational usefulness before a broad discovery toolkit or private corpus
exists. Calibration must not be advertised as held-out capability evidence. Bughunt owns
live bounty campaigns; Nidavellir owns controlled environments, independent validators
and repeated experiments. BH-13/NV-09 exchange synthetic versioned test/evidence manifests,
not real campaign credentials. Integration remains planned.

Preserve Docker-local as the supported implementation focus. Cloud parity, hosted concerns,
and multi-agent breadth remain deferred; local VM intake requires a selected research need.
The previous August sequence remains traceable in Git and the milestone mapping below.

Correctness, containment, and independent verification remain ahead of feature
count. The authoritative product boundary is
[`docs/VISION.md`](docs/VISION.md). Architecture
decisions live in [`docs/adr/`](docs/adr/).

---

## 1. Product definition

### 1.1 Two objectives, one engine

**Discovery.** Nidavellir is a vulnerability research platform: point it at a
real product, get it running at an exact identity, work it from a contained
position with real tooling, and leave with a reproducible proof — the finding,
its PoC, the observed effect, the patch or diff that explains it, and the
immutable identity of what was tested. The output is a defensible vulnerability
record, not a score. Most of the friction this removes is unglamorous and real:
standing the thing up at the right version, keeping the environment contained,
and being able to prove afterwards exactly what was hit.

**Evaluation.** Nidavellir also evaluates **complete agents**, not only models. A
result identifies the model, scaffold, tools, budgets, target, starting state,
and evidence. The primary benchmark is an **active challenge**: a real running
system whose state and responses change as the participant acts. Static CTFs and
known-CVE packs remain useful calibration lanes, but they are not the whole
product.

The two are duals of one substrate. The same provisioning, containment, monitor,
validator, evidence, and scoring machinery answers "is this vulnerability real?"
and "did this agent find it". A discovery session with hidden truth withheld is
an evaluation challenge; an evaluation run whose participant is a human operator
is a discovery session.

They also feed each other in one direction that matters: **verified findings from
real research are the only honest source of held-out challenges.** Public CTFs and
known-CVE packs are calibration, and any agent comparison built solely on them is
contestable. This is why the held-out proof corpus must come from verified research. A small
calibration comparison can land first under NV-07–09 without making that stronger claim.

### 1.2 Operator journeys

Nidavellir supports two first-class operator journeys:

- **Engagement:** one human or agent performs security research in one active
  arena. The operator configures the target, observes work, and reviews evidence.
  An engagement declares its purpose — *discovery* and *manual research* serve the
  discovery objective; *benchmark* and *calibration* serve measurement.
- **Evaluation:** one or more pinned agent builds run repeated trials over a
  challenge suite. Nidavellir compares verified capability, regressions, cost,
  latency, and safety.

Both journeys reuse the same arena, gateway, event, evidence, validation, and
scoring substrate. Evaluation is not a second engine layered beside engagements,
and discovery is not a degraded evaluation — it is the mode in which the target,
rather than the participant, is the thing being judged.

### Product objects and relationships

| Object | Meaning |
|---|---|
| **Target** | An immutable Git object, OCI digest, source bundle, package, or future VM/binary identity. |
| **Scenario** | The provider-agnostic topology specification (`nodes[]`, `segments[]`, services, stances). This remains the engine term. |
| **Challenge** | A scenario plus target identity, participant brief, visibility policy, objectives/hidden truth, validators, and optionally a staged episode. |
| **Agent build** | A pinned external system under test: identity, version/digest, driver, model/scaffold metadata, and default limits. |
| **Engagement** | One operator-led research session against one challenge or ad-hoc target. |
| **Evaluation** | A configured experiment: agent builds × challenge suite × trials × budgets. |
| **Run** | One agent build on one challenge for one trial/seed. |
| **Arena** | The live infrastructure allocated to an engagement or run. It is an execution resource, not the top-level product workflow. |
| **Evidence** | Findings, PoCs, monitor signals, files, patches, traces, and validator verdicts tied to immutable identities. |
| **Campaign** | A discovery-lane grouping: one target portfolio worked across many engagements over time, with findings deduplicated and tracked to disclosure. |
| **Vulnerability record** | The discovery-lane result: a confirmed finding with its PoC, observed effect, affected identity/version range, and disclosure state. A challenge is what it becomes once its truth is hidden. |

The existing code/database terms `deployment` and `lab` may remain internally
until migrated safely. New operator-facing prose uses the glossary above.

---

## 2. Current status — shipped engine

Read against the dual objective, the shipped engine is already most of a research
substrate and only part of a research *toolkit*. Reproducible setup from an
immutable identity, containment, the crash oracle, change intelligence, hashed
patch artifacts, PoCs, and an evidence trail that outlives the arena all serve
discovery today. What discovery lacks is offensive tooling (§4) and the lane in §5:
nothing feeds the crash oracle, there is no variant hunting, no binary or VM
intake, and no campaign-level view across sessions.

For evaluation the split is the opposite: the observation and scoring half is
shipped, and the durable experiment records that make runs comparable are not.

### S1 — Control plane and dynamic arenas · shipped

- FastAPI orchestrator ↔ Redis/Celery worker ↔ provider drivers.
- PostgreSQL/SQLAlchemy/Alembic, explicit arena state machine, append-only events,
  TTL/stuck reaper, log redaction, and optional Fernet encryption at rest.
- Scenario schema v3 with arbitrary nodes/segments and a Docker-local compiler.
- API-key roles, CSRF, rate limits, input validation, and server-enforced
  key↔arena stance bindings.
- Mature `docker-local` path; `mock` for tests/demo. OpenStack, AWS, and libvirt
  remain non-live skeletons and are deliberately deferred.

### S2 — Target → running service · shipped (legacy M1)

- Repository introspection and deterministic Dockerfile build path.
- Verified LLM Dockerfile synthesis fallback and `service.package` install.
- Git target resolution to immutable object IDs.
- Public OCI tag resolution to digest-pinned references.
- Bounded local tar/tar.gz intake with canonical hashes and safe materialization.
- SUT setup modes: operator-scripted, HITL, and double-locked autonomous
  configurator; white-box source access separated from the target runtime.

Remaining breadth—not a blocker for the present product sequence: execute
Compose/devcontainer/buildpack tiers; binary/installer and VM-image intake.

### S3 — Observation, validation, scoring, and eval export · shipped (legacy M2–M3)

- Crash/sanitizer/5xx/resource monitor and deduplicated evidence signals.
- Deterministic validators, including observed browser execution for reflected XSS.
- Structured Inspect-style `Score`, benchmark/discovery modes, and milestone
  progress for incomplete runs.
- Reproducible PoCs and operator confirm/refute workflow.
- OpenInference/OTel-aligned traces and eval dataset rows.
- Reference MCP harness, concurrency-capped suites, and deterministic transcript
  replay.

The engine can score and export a run today. It does not yet have durable
evaluation/suite/trial records or paired agent-version comparisons.
NV-06 adds a resettable authorization fixture with action-linked, target-local
effect and healthy-control observations, versioned four-way verdicts and
post-teardown operator review. The headline benchmark score now uses automatic
confirmed points; claim coverage and manual judgments remain separate.
The 2026-09-24 pinned release and Docker-local live gate passed with NV-02–05
regressions. See `docs/verification/nv06-gates-2026-09-24.json`.

### S4 — Research session and attacker tooling · partially shipped (legacy M4)

Shipped:

- authorization/scope declarations and fail-closed target preflight;
- Git change intelligence for staged, unstaged, and selected untracked files;
- SHA-256 patch evidence artifacts attachable to findings;
- bounded foothold upload/download with body-free audit metadata;
- target-scoped disposable headless browser shared with the XSS validator;
- arena-target HTTP requests, content-addressed transactions, replay/modify, MCP tools,
  console controls and finding attachment by digest (R1 code implemented August 24).
- worker-owned confined PoC execution (NV-03) and orchestrator-enforced durable
  action/deadline budgets with per-arena and system stop controls (NV-04).
- declared-service, fixed-destination TCP forwards with durable lease/stream
  accounting and a principal-filtered REST/console/MCP capability manifest (NV-05).

Still required:

- trusted token/cost preflight and usage accounting for future supported model drivers;
- before/after manifests for non-Git/binary targets.

### Verified health boundary

NV-01 completion on 2026-09-16 supersedes the release-gate portion of the
2026-09-07 review below. The documented `make release-check` command builds a
clean Python 3.11.14 verifier from an exact dependency lock, excludes local
environments and `.env` files, and starts with disposable database state. Ruff
0.6.9 passed; Bandit 1.9.4 found zero medium/high issues. NV-02's final 2026-09-21
gate passed 863 tests on SQLite (one PostgreSQL-only concurrency test skipped)
and 864 on PostgreSQL, with six declared integration deselections on each backend.
Alembic clean migration plus API, console and MCP-gateway readiness smokes passed.
The isolated live Docker gate then proved two resets across three deployments,
retained evidence, deployment/teardown recovery and a zero-resource final inventory.

NV-04's final 2026-09-23 pinned gate passed Ruff 0.6.9, Bandit 1.9.4 with zero
medium/high findings, 889 SQLite tests (two PostgreSQL-only tests skipped) and
891 PostgreSQL tests, each with six declared integration deselections. Alembic,
API, console and MCP readiness smoke passed. The isolated NV-04 live gate proved
cross-process allowance persistence, a one-slot 200/429 race, stop/drain/reaper
recovery, sticky system stop across restarts, deadline expiry and zero final
resources. NV-02 and NV-03 Docker-local live regressions passed on the same
source. See `docs/verification/nv04-live-2026-09-23.json` and the dated journal.

NV-05's 2026-09-23 pinned gate passed Ruff 0.6.9, Bandit 1.9.4 with zero
medium/high findings, 891 SQLite tests (four PostgreSQL-only tests skipped)
and 895 PostgreSQL tests, each with six declared integration deselections.
PostgreSQL covered competing lease creation, stream claims, revoke/connect and
stop/helper-start serialization. The isolated Docker live gate proved a
two-segment internal-only TCP fixture, principal-filtered REST/MCP discovery,
console controls, fixed destination denial, revoke/expiry/stop stream closure,
killed-worker cleanup, reset and zero labeled resources. NV-02/03/04 live
regressions passed afterward. See `docs/verification/nv05-live-2026-09-23.json`
and the dated journal. This is a fixed TCP relay, not an SSH tunnel; token/cost
hard caps for external agents remain explicitly unsupported.

Review on 2026-09-07: no main stack services running under this Compose project; a stopped
agent-gateway and cached images exist. Ruff passed. Source-only Bandit (excluding both
`.venv` and nested `venv`) reported no medium/high findings. 121 focused unit tests passed
for scenarios, source bundles, HTTP/evidence storage, scoring, validators and gateway.

The full host Python 3.14 run stalled in Starlette TestClient and was interrupted; this
is not a full pass. `make check` also scans a nested virtual environment because its Bandit
exclusion only names `.venv`; NV-01 repairs that verification workflow. The cached Python
3.11 orchestrator image lacks the full test dependencies. No live arena lifecycle or
PostgreSQL suite was rerun in this review.

The historical Python 3.11 gate (2026-08-18) recorded 808 passes and six integration skips,
Ruff clean and no medium/high Bandit findings. Keep that historical result distinct from
current verification. Docker-local is the historically live-verified provider; cloud/VM
support and current deployment health must not be inferred from driver files.

---

## 3. Console product architecture — shipped (C1–C4)

### C1 — Information architecture and application shell · **COMPLETE**

**Goal.** Give every shipped and planned function one predictable home before
adding evaluation features. This is a workflow reorganization, not a visual-only
redesign and not a backend rewrite.

The primary console navigation becomes:

```text
Home

Engagements
  Active
  History
  New engagement

Evaluations
  Suites
  Runs
  Comparisons
  New evaluation

Library
  Challenges
  Targets
  Agents

Activity
  Findings
  Evidence
  Audit trail

Administration
  Providers & capacity
  Security
  Settings
```

**Migration mapping.** Existing functions are preserved while routes/templates
move incrementally:

| Current surface | Destination |
|---|---|
| Dashboard | Home, redesigned last from the new objects |
| Arenas | Engagements; arena lifecycle remains visible inside an engagement/run |
| Launch + SUT wizard | Global Create → New engagement |
| Inventory / scenarios | Library → Challenges |
| Git/OCI/bundle intake | Library → Targets and the engagement wizard |
| Agents live-connections page | Run/engagement Agent tab; Library → Agents becomes the build registry |
| Logs | Activity → Audit trail |
| Findings/evidence/change cards | Activity indexes plus contextual run/engagement tabs |
| Settings/profile/model connection | Administration/Account |

**Application-shell work.** Establish grouped navigation, breadcrumbs, a global
Create action, consistent page headers, filters, tables, statuses, empty states,
and responsive behavior. Existing routes may remain as aliases during migration.

**Shipped first slice (2026-08-10).** The Flask console now has collapsible
Engagements, Evaluations, Library, Activity, and Administration groups; a global
Create menu routes operators into the existing challenge- and target-based
engagement flows. Target-language routes coexist with the legacy URLs, and
honest foundation pages reserve planned destinations without pretending their
data models exist. Page titles and breadcrumbs now use the target vocabulary.
The responsive shell now shares one compact-navigation breakpoint, provides a
mobile dismissal layer and keyboard dismissal, and exposes its state to
assistive technology. Filterable indexes share the same toolbar pattern.
Automated route/render coverage is green. Live-browser visual verification and
the final shell review are still required before C1 is complete.

**Completion (2026-08-18).** The shell was reviewed in a real browser against the
running compose stack. Twenty-three destinations — Home, both engagement pages,
the evaluation and library and activity and administration destinations, the
arena workspace, and every legacy alias — were walked at 1440×900 and 390×844.
Each renders with a breadcrumb, exactly one current navigation item, no
horizontal overflow at compact width, and no page-level console error or failed
request. The review found and fixed two real defects: the New engagement steps
rendered 1 → 3 → 4 → 2 because the participant/policy slice was inserted above
the source step, and `/launch` and `/wizard` opened the Engagements group without
marking any item current. Both are now covered by regression tests, and the
console serves its own `favicon.ico` instead of 404ing. The remaining 404 on an
arena's research preflight is correct: a challenge-based arena has none, and the
card hides itself.

**Acceptance.** A clickable, realistic prototype and route map cover Home,
Engagements, Evaluations, Library, Activity, Administration, and the workspace
below. An operator can locate every existing function; no shipped capability is
orphaned or duplicated. → ADR-0012.

### C2 — Unified engagement creation · **COMPLETE**

Replace separate Launch/SUT mental models with one GUI wizard composed from
shared steps:

1. purpose: calibration, benchmark, discovery, or manual research;
2. challenge or ad-hoc target;
3. target identity and black/white-box visibility;
4. human/agent participants and stance;
5. setup mode and explicit consent;
6. tools, containment, and limits;
7. scoring/monitoring policy;
8. immutable review and launch.

Advanced choices stay collapsed until relevant. Generated infrastructure and
autonomous configuration keep their existing review/double-lock gates.

**Shipped first slice (2026-08-10).** `/engagements/new` is now the canonical
GUI entry point. It captures benchmark, discovery, calibration, or manual
research purpose plus challenge/target source, then hands off to the existing
validated builder with the chosen context visible. Global Create, Home,
Engagements, and challenge-library actions use this entry; `/launch` and
`/wizard` remain compatibility routes. No deployment endpoint, authorization
confirmation, setup consent, or review gate was weakened. The remaining C2 work
at that point was participant/policy composition. Purpose was validated by every
deployment request and persisted as an append-only `engagement_intent` event;
compatibility clients could omit it. Generated, pasted, and Vulhub challenges return to the same builder
with the imported challenge selected and purpose preserved instead of dropping
the operator into the library. Remaining policy controls wait for matching
backend enforcement.

**Completion (2026-08-10).** The composed journey now captures purpose, source,
participant mode, and an enforced engagement time box. Every predefined,
custom, generated, pasted, Vulhub, Git, OCI, and local-bundle path carries that
contract into the existing backend request. Purpose/participants/policy are
recorded once as append-only intent; the time box controls deployment expiry.
Review distinguishes selectable intent from authoritative policy: agent access
and stance remain binding-enforced, target agent visibility remains black-box
unless a challenge explicitly declares white-box source, runtime containment is
provider-enforced, and monitoring/scoring are automatically derived. Generated
infrastructure still requires import/review before launch, and target
authorization/setup consent is unchanged. Legacy `/launch` and `/wizard` routes
remain valid compatibility entry points.

**Acceptance.** From the browser, the operator can launch every currently
supported predefined, custom, generated, Vulhub, Git, OCI, and local-bundle path
through one coherent journey, with the same backend validation as today.

**Met in source/render/contract tests, and confirmed live on 2026-08-18.** In the
browser, Create → New engagement → configuration → launch produced an active
arena from the challenge path with the composed contract intact: the
`engagement_intent` event recorded purpose, source, participant mode, time box,
and the platform-enforced containment/monitoring/scoring values, and the chosen
30-minute time box became the deployment expiry.

### C3 — Engagement/run workspace · **COMPLETE**

Decompose the growing arena-detail page into one contextual workspace:

```text
Overview · Live · Target · Findings · Evidence · Changes
Agent · Trace · Score · Infrastructure
```

Only applicable tabs appear. Setup is a phase inside Overview/Live, not a permanent
page block. Destroyed arenas become read-only records whose evidence remains
available. Add SSE for live state, events, monitor signals, agent actions, findings,
and budgets; retire five-second polling.

**Shipped (2026-08-18).** The arena page is now one workspace of contextual tabs.
`_workspace_tabs` renders only what has something to show: Target needs a preflight
or a configurable target, Changes a provider-discovered workspace, Evidence artifacts
or monitor signals, Trace a connected agent's activity, Score a score. A predefined
challenge arena therefore shows six tabs, not ten. The active tab is the URL fragment,
so `#findings` is a shareable deep link. Setup became a phase — an Overview card while
the target comes up, a Target-tab record afterwards. A destroyed arena is a read-only
record: lifecycle and configuration actions disappear, node state is labeled as last
recorded rather than claimed running, and findings, evidence, score, and trace stay
reviewable. Evidence and Trace are new surfaces: content-addressed patch artifacts and
monitor signals in one place, and the run's model/scaffold/stance attribution with an
eval-row export.

`GET /api/arenas/{id}/stream` is the workspace's SSE channel. `state` frames carry
arena status and outputs; `activity` frames carry new audit events — agent actions,
findings, monitor signals — and the SSE id is the event's monotonic database id, so a
reconnecting browser resumes from `Last-Event-ID` with no gap and no replay. The
five-second status poll is retired: a live workspace makes zero `/api/poll` requests,
and the positioning/configurator panels refresh because an event says they changed
rather than on a fixed timer, with a slow safety tick behind them and the old poller
kept as a fallback where a stream cannot be held. Budget frames wait for R3, which is
where durable budgets are actually introduced.

**Acceptance.** An operator can follow provision → setup → engagement → result
without leaving the workspace, while detailed evidence and infrastructure remain
available on demand rather than competing on one page.

**Met, and confirmed live on 2026-08-18** against the compose stack: every tab was
walked in a real browser at 1440×900 and 390×844 with one panel visible at a time and
no horizontal overflow; a finding submitted through the API alone appeared in the
browser without a reload; destroying the arena flipped the status badge live; and the
same arena then rendered as a read-only record. Two defects found by that review are
fixed — the topology could not measure itself inside a hidden panel, and the manual
finding form's inline `display:grid` had been silently defeating its `hidden`
attribute.

### C4 — Home and cross-cutting activity · **COMPLETE**

Redesign Home only after C1–C3 so it reflects the real product model:

- active engagements and running evaluations;
- findings awaiting review;
- failed/blocked runs and containment warnings;
- recent comparisons;
- provider/capacity health.

Activity supplies global Findings, Evidence, and Audit indexes; each item links
back to its engagement/run context.

**Shipped (2026-08-18).** Home is composed from the objects an operator acts on:
live engagements with their expiry, findings awaiting a verdict, and an attention
list that names both failed runs and any live arena whose egress is open, beside
provider/capacity health and the activity feed. Every tile is a route into the work
it counts. Evaluations remains an honest dash until E1 gives it durable records.

Activity → Findings and Activity → Evidence are no longer foundation pages. Findings
folds the global `finding` and `finding_verification` streams into one index — the
operator verdict overriding any automatic one — with facet counts (all / awaiting
review / confirmed / refuted) and search over title, CWE, node, and engagement.
Evidence lists content-addressed artifacts with their provenance and download, plus
monitor signals, across engagements. Both filter through the same toolbar contract as
the audit trail, and every row returns to the engagement workspace on the tab that
owns it (`/arena/{id}#findings`). Where an engagement record has been pruned, the
finding still stands but the console offers no link or download it cannot honor.

**Acceptance.** Met, and confirmed live on 2026-08-18: filtering 26 findings by
verdict and text worked in the browser, a row followed through to its engagement's
Findings tab, evidence whose arena record was gone rendered as unavailable rather
than as a dead download, and the nav no longer marks either destination as
foundation.

---

## 4. Research-ready runtime — the shared prerequisite

This work follows the C1 shell and C3 workspace foundations so new controls have
a durable place in the product. It completes, rather than replaces, legacy M4.

**Both objectives need exactly this.** A researcher cannot work a real target
without an HTTP primitive, a place to run a PoC, and a way to reach an internal
service; an agent under evaluation cannot demonstrate capability without the same
tools, and a comparison across builds is meaningless if the toolset differs
between them. Build each primitive so a human drives it in the workspace and an
agent drives the same bounded operation over MCP — one implementation, two
callers, identical scope checks and audit records. A tool that only an agent can
reach will not be exercised often enough to be trustworthy.

### R1 — HTTP research primitive · code implemented; fresh live gate pending

Ship structured, arena-target-only HTTP inspect/replay/modify over REST and
attacker MCP. Accept node plus relative path—not arbitrary URLs. Bound and hash
request/response bodies; keep audit events body-free; apply binding, budget,
timeout, and target-scope checks. Keep this distinct from MITM packet observation.

### R2 — Confined PoC execution

Run Python/PoC work in disposable CPU/RAM/PID/time-capped containers with no
filesystem or egress by default. Route lifecycle through the worker; never widen
the orchestrator's root-equivalent Docker-socket authority. Prove the sandbox
cannot reach the internet or cloud metadata.

### R3 — Pivoting and durable guardrails

- Foothold-segment TCP forwards to declared services with expiry, cleanup, and trace.
- Cross-process action/time budgets with fail-closed accounting; external model
  token/cost hard caps refuse admission until a trusted driver supplies usage.
- Per-arena stop plus system-wide emergency stop; reject new work, cancel where
  safe, terminate disposable helpers, and flush final traces.

**Research-runtime acceptance.** A BYO agent confirms XSS in the browser, develops
a PoC in the sandbox, transfers payload/evidence, inspects and replays HTTP, and
connects to a declared internal service. Every action is scoped and traced; a breached
budget freezes further work; containment tests remain green.

### R1 implementation slices — historical plan, reconciled 2026-09-07

The six slices below now exist in code, including the console and finding attachment.
Retain them as the acceptance/design reference; fresh full/live verification is NV-01–02.
NV-03 confined execution, NV-04 durable guardrails and NV-05 scoped access are
complete on Docker-local. These six slices are not six open implementation tasks:

1. **Provider primitive** — `http_request` across `base` (refuse), `docker-local`
   (disposable arena-bound runner, mirroring the headless-browser pattern), and
   `mock`; bounded bodies, hard timeout, no off-target redirects.
2. **Orchestrator wrapper and REST route** — an `_http_target` resolver in the
   shape of `_browser_target`: node plus relative path only, foothold targeting
   refused, arena binding and rate limit enforced, bodies hashed and capped, audit
   events body-free.
3. **Transaction store** — bounded, arena-scoped, content-addressed request/response
   records that a researcher can list and inspect, on the same evidence-artifact
   discipline as patches.
4. **Replay and modify** — re-send a stored transaction with edits, keeping the
   original immutable so the pair is the evidence.
5. **Attacker MCP tools** — the same operations over the gateway chain, with the
   scope checks server-side and identical audit records.
6. **Workspace surface and evidence attachment** — an HTTP tab that appears only
   where it applies, streaming new transactions over the existing SSE channel, with
   a transaction attachable to a finding by digest.

Leave a counter seam in slices 2 and 5 for the durable budgets R3 introduces; do
not invent a second accounting path. Detailed work items, seams, and per-slice
acceptance live in the internal backlog.

---

## 5. Discovery lane — the vulnerability research platform

The engine already does the unglamorous half of vulnerability research: it
resolves a target to an immutable identity, stands it up reproducibly, contains
it, watches it for faults, hashes what changed, and records proof that survives
the arena. What it does not yet do is the specifically *offensive* half — hunt
variants of a known fix, drive a fuzzer into its own crash oracle, open a firmware
image, or carry findings across months of work on one product.

This lane closes that gap. It assumes R1–R3 exists, since a researcher without an
HTTP primitive or a sandbox is not equipped.

**Scope discipline.** Nidavellir does not become an exploitation framework or a
scanner. It provisions, contains, observes, verifies, and records. Tooling lands
here only when it produces evidence the platform can independently check.

### D1 — Patch-diff and variant hunting

Intake two identities of the same target — a vulnerable release and its fix, two
Git objects, two OCI digests — and make the security-relevant difference a
first-class object: the changed files and functions, the reachable entry points
they sit behind, and a bounded, hashed diff artifact reusing the existing evidence
path. From there, drive a variant sweep: the same defect class in the same
codebase in the places the fix did not touch.

This is where a researcher actually starts on a real product, and it is the
cheapest strong capability the platform can add, because the change-intelligence
and evidence-artifact primitives already exist.

**Acceptance.** From the browser, an operator supplies a target and two versions,
sees the security-relevant diff with its hashed artifact, launches an arena pinned
to the vulnerable identity, and records a finding whose evidence references both
the diff digest and the observed effect. The same diff is available to an agent
over MCP under the existing scope checks.

### D2 — Fuzzing and crash triage

The crash oracle exists and nothing feeds it. Add the missing half: register a
harness for a target, manage seed corpora and dictionaries as versioned artifacts,
run campaigns inside the R2 confined-execution boundary, and route every fault
into the monitor path that already deduplicates by fingerprint.

Then make a crash usable: automatic minimization, deterministic reproduction from
a stored input, and a triage verdict that separates a reproducible fault from log
noise. Coverage is a means, not a metric to display for its own sake.

**Acceptance.** A campaign against a known-vulnerable target rediscovers its fault
from a cold corpus, the crash is minimized and reproduced deterministically from
its stored input, and the resulting finding carries the input digest as evidence.
Campaign resource use stays inside declared budgets and the host stays contained.

### D3 — Binary, appliance and VM intake

Promoted from the deferred list, with its reason stated: the highest-value product
research targets are appliances, firmware, and thick clients, not source-available
web applications. A platform that only accepts a Git URL cannot serve the work its
users actually do.

Required: VM-image and firmware intake with the same content-addressed identity
discipline as source bundles; a local VM provider path (libvirt/QEMU is the
existing skeleton); snapshot and restore so a research position is repeatable;
debugger attach and symbolization inside the arena boundary; and a before/after
manifest for targets with no Git workspace, so change intelligence still works.

This is the largest single item on the roadmap and the one most likely to be
descoped to a subset — a defensible first cut is VM-image intake plus snapshot and
restore, with debugging deferred.

**Acceptance.** An operator ingests a VM or firmware image by digest, boots it in a
contained arena, takes a snapshot, works it, restores, and reproduces the same
state. Findings reference the image digest and the before/after manifest.

### D4 — Campaigns, deduplication and disclosure output

Research on one product runs for months across many sessions. Add a **campaign**:
a target portfolio worked over time, with findings deduplicated across engagements
and versions, tracked through a disclosure state — internal, reported, fixed,
published, regressed — and exportable as a disclosure bundle carrying the finding,
PoC, observed effect, affected identity range, and hashes.

Regression matters as much as discovery here: when a vendor ships a fix, the same
PoC must be re-runnable against the new identity to confirm it, and to catch the
fix that does not hold.

**Acceptance.** An operator opens a campaign over one product's release history,
sees findings deduplicated across sessions and versions with their disclosure
state, re-runs a stored PoC against a newer release to confirm or refute the fix,
and exports a disclosure-ready bundle whose every claim resolves to a recorded
identity and artifact.

### Discovery acceptance

The lane is credible when a real, previously unknown vulnerability in a real
product is found and proven end to end inside Nidavellir — set up from an
immutable identity, worked from a contained position, confirmed by observed
effect rather than assertion, and exported as a disclosure bundle — and when the
same finding, with its truth withheld, becomes a held-out challenge for the
evaluation lane without any rework.

---

## 6. How the lanes meet

The discovery lane produces material the evaluation lane cannot obtain otherwise,
and the evaluation lane produces the pressure that keeps discovery tooling honest.

| Shared substrate | Used by discovery as | Used by evaluation as |
|---|---|---|
| Immutable target identity | proof of what was tested and what a fix applies to | the pinned starting state a comparison requires |
| Contained arena + stances | a safe research position on someone else's product | the capability boundary a result is valid within |
| Monitor + validators | independent confirmation that a bug is real | the grader that outranks an agent's claim |
| Evidence artifacts + PoC | the disclosure record | the reproducibility check behind a score |
| Structured score | progress within a long campaign | the comparable outcome per run |
| Verified finding | the deliverable | the challenge, once its truth is hidden |

**The one-way dependency:** a challenge is a solved discovery problem with the
answer withheld. Nidavellir can therefore build a private challenge corpus that no
public benchmark can replicate, but only if discovery work actually happens on the
platform. An evaluation product built before the discovery lane would be limited
to public CTFs and known-CVE packs — exactly the calibration material this roadmap
says is not sufficient for a defensible comparison.

The reverse dependency is weaker but real: measuring agents on a corpus exposes
which tools they could not use and which evidence paths were never exercised,
which is the most reliable signal for where the research runtime is still thin.

---

## 7. GUI-driven agent evaluation workbench

This lane turns single engagements into repeated, comparable runs. It is the
measurement half of the dual objective, and it depends on §5 for the material
worth measuring on: without held-out challenges of known provenance, a comparison
runs on public CTFs and known-CVE packs, which the participants may have trained
on and any vendor can contest.

E1–E5 can be built before that corpus exists — the machinery is independent of the
challenges it runs — but publishing a comparison should not get ahead of it.

### E1 — Durable experiment model

Add first-class records for agent builds, suites, evaluations, runs, and trials.
Every run records agent version/digest, model/scaffold, target/scenario digest,
visibility, seed, budgets, tool versions, start/end state, score, cost, trace, and
reset proof. Existing event-derived eval rows remain the export projection.

### E2 — Generic external-agent drivers

Support different agent shapes without embedding any agent's product logic:

- `mcp-interactive` for agents that use Nidavellir tools directly;
- `container-service` for persistent/event-driven agents;
- `external-webhook` for an authorized system outside the stack.

The driver owns prepare/start/wait/metadata/stop. Findings and evidence still
enter through Nidavellir's authenticated, independently validated path. A
continuous pentesting agent is the first serious internal validation case, not
a hard-coded dependency.

### E3 — Agent registry and suite builder

Library → Agents registers pinned builds, connectivity, driver, model/scaffold
metadata, secret references, and default limits. Evaluations → Suites composes
held-out challenges, trial counts, seeds, visibility, budgets, and reset policy.

### E4 — Active challenge episodes

A challenge may define deterministic phases:

```text
baseline release → representative traffic → changed component
→ observation window → fixed release → regression release
```

This measures agents that react to changes as well as one-shot exploit agents.
The episode controller is generic and provider-contained. Hidden truth and
release schedules are never exposed to the agent.

### E5 — New Evaluation wizard, live execution, and comparison

Entirely from the browser, an operator:

1. selects baseline and candidate builds;
2. selects a suite and trials;
3. reviews identities, seeds, budgets, and containment;
4. launches and watches live progress;
5. inspects failures/retries;
6. receives per-challenge and aggregate comparisons;
7. drills down to findings, validator evidence, timeline, and trace;
8. exports OpenInference/Inspect-compatible data.

Comparison metrics include verified TP/FP/FN, precision/recall where truth exists,
progress rate, detection latency, unnecessary retesting, fixed/regressed finding
lifecycle, steps/requests/tokens/cost, timeouts, and scope violations. Show paired
rows and uncertainty; never hide regressions inside one aggregate.

**Evaluation acceptance.** From the GUI, one operator runs two pinned agent builds
over the same active held-out suite for at least three trials, gets independently
verified results, and sees exactly where capability, false positives, latency,
cost, or safety improved or regressed.

---

## 8. Proof, release, and later extensions

### P1 — Held-out flagship proof

There are two proofs to publish, and they are not interchangeable.

**Discovery proof.** A real vulnerability in a real product, found and proven
inside Nidavellir: immutable identity, contained arena, observed effect,
reproducible PoC, disclosure bundle. This is what demonstrates the platform is
useful to a researcher, and it can be published as soon as the D lane supports it —
it does not wait on the evaluation workbench.

**Comparison proof.** A reproducible agent-version comparison over a held-out
suite:

- Build the private/held-out challenge set **from confirmed discovery-lane
  findings with their truth withheld**; public labs are calibration only.
- Include static known-vulnerability, randomized, and active-change episodes.
- Publish leakage policy, scaffold/tool disclosure, repeated-trial methodology,
  uncertainty, and infrastructure-failure handling.
- Record the GUI journey: register builds → run evaluation → inspect proof → compare.

**Acceptance.** The discovery artifact demonstrates a vulnerability found and
proven end to end on the platform. The comparison artifact demonstrates a
reproducible agent-version comparison — not merely a successful single exploit —
on challenges whose provenance is stated and whose truth was never public.

### P2 — Optional LLM-application targets

After the workbench is credible, add prompt-injection RAG, secret-exfiltration,
improper-output-handling, and excessive-agency challenges aligned with OWASP LLM
and Agentic Top 10. Reuse the same challenge, episode, validator, and comparison
model; do not create a separate evaluation product.

---

## 9. Explicitly deferred

These do not block the single-team, self-hosted product on either objective:

- MCP OAuth 2.1 and third-party tool-supply-chain defense;
- multi-tenant workspaces, SSO, graduated organization RBAC, and hosted billing;
- real AWS/OpenStack cloud apply at scale;
- multi-agent red-vs-blue and defender detection scoring;
- in-browser VNC/Guacamole and a full hosted web terminal;
- large public leaderboards.

**Promoted out of this list (2026-08-19):** VM, firmware, and binary target intake,
and the local VM provider path, are now **D3**. They were deferred while the
product was framed only as an agent-evaluation arena, where source-available
targets are sufficient. Under the discovery objective they are load-bearing: the
products worth researching are largely appliances and thick clients. Cloud
provider *apply* remains deferred — a local hypervisor is what discovery needs, not
a fleet.

Re-promote the rest only for a concrete need, roughly in this order: worker/socket
isolation → OAuth/tool trust → multi-tenant identity → cloud providers →
multi-agent/purple-team.

---

## 10. Standing principles

- **GUI-driven product, API-backed architecture.** Every normal operator workflow
  is complete in the browser. Business logic, orchestration, and persistence stay
  in the orchestrator/services; Flask/Jinja presents and drives them.
- **Bring your own agent.** Nidavellir ships a neutral substrate and thin reference
  connectors, never the agent whose capability it claims to measure.
- **AI-centered, never AI-required.** A human can operate an engagement and submit
  evidence without a model.
- **Two objectives, one engine.** Discovery and evaluation are duals on the same
  substrate. Reject any capability that serves one by forking the arena, the
  evidence model, or the validators — a fork means the results stop meaning the
  same thing. When a tool is added, a human in the workspace and an agent over MCP
  drive the same bounded operation.
- **A challenge is a solved discovery problem.** Held-out evaluation material comes
  from verified findings with their truth withheld. Public labs calibrate; they do
  not settle a comparison.
- **Immutable identity before score.** Targets, agent builds, scenarios, tools,
  seeds, and starting state are recorded. A comparison without them is invalid.
- **Deterministic proof before judgment.** Validators and observed effects outrank
  agent claims. Unknown is not refuted; discovery mode does not pretend to know
  false negatives.
- **Containment is the primary control.** No egress by default, narrow tools,
  explicit consent, bounded helpers, and live containment tests.
- **Preserve feature parity during UI migration.** Reorganize incrementally; do not
  replace working backend flows or strand existing capabilities.
- **Verify the product, not only tests.** Each milestone needs automated coverage
  and a live Docker-local path through the real compose stack.
- **One source of status truth.** ROADMAP is the public sequence. The internal
  backlog and active development handoff must be reconciled with it at each
  milestone boundary.

---

## 11. Legacy milestone mapping

| Previous roadmap | New location |
|---|---|
| *(none — new lane, 2026-08-19)* | D1–D4 discovery: patch-diff/variant hunting, fuzzing + triage, binary/appliance/VM intake, campaigns and disclosure |
| M1 repo→service | S2, shipped |
| M2 monitoring/scoring | S3, shipped |
| M3 eval/export/reference harness | S3, shipped; durable comparison continues in E1–E5 |
| M4 research workspace/tooling | S4 shipped slice + R1–R3 remainder |
| M5 regression/eval pipeline | E1–E5, now explicitly GUI-driven |
| M6 LLM-app targets | P2, optional after proof |
| Former console/SSE items | C1–C4 |
| OAuth, multi-tenancy, cloud, purple-team, VNC | §9 deferred; local VM intake is NV-13 |

Current task mapping is in [TODO.md](TODO.md). Detailed historical `Pn-m` implementation records remain in
[`.agent/backlog/BACKLOG.md`](.agent/backlog/BACKLOG.md) and git history.

---

## 12. Architecture decisions

- ADR-0002 — API-key authentication and WebUI login.
- ADR-0003 — provider driver interface and scenario compilation.
- ADR-0004 — PostgreSQL persistence and event spine.
- ADR-0005 — MCP gateway, stances, bindings, and guardrails.
- ADR-0007 — software-under-test arenas.
- ADR-0008 — repository-to-image pipeline.
- ADR-0009 — monitoring, validators, and structured scoring.
- ADR-0010 — eval export, reference harness, and replay.
- ADR-0011 — reproducible research sessions and change intelligence.
- **ADR-0012 — GUI-first product model and console information architecture.**
- **ADR-0013 — replacement reset, immutable recipes and observed equivalence.**

The detailed state-of-the-art references behind the shipped design remain in the
ADRs and repository history. New evaluation work should integrate with established
formats such as Inspect and OpenInference rather than inventing a general-purpose
eval framework around Nidavellir's specialized cyber environment.
