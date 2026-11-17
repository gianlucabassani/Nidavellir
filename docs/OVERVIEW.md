# Overview

> Nidavellir is a **GUI-driven, bring-your-own-agent arena for security work on
> real running systems**. It provisions reproducible targets, gives a human or
> external agent a contained research position, independently verifies observed
> effects, and produces evidence-grade, replayable, auditable results.

One engine serves two objectives. In **discovery**, the target is under test: the
platform removes the friction of standing a real product up at an exact identity,
containing it, and proving afterwards what was hit — the output is a vulnerability
record. In **evaluation**, the AI is under test: complete agent builds run over
held-out challenges and are compared on verified capability. They meet at one
asset — a challenge is a solved discovery problem with its truth withheld.

Nidavellir ships no autonomous pentesting agent. It is the environment factory,
capability boundary, observer, referee, and comparison layer. For agent connection details see
[`MCP.md`](./MCP.md); for the product boundary see [`VISION.md`](./VISION.md);
for subsystem internals see
[`INTERNALS.md`](./INTERNALS.md); for the product sequence see
[`../ROADMAP.md`](../ROADMAP.md).

---

## What it evaluates

The unit under test is a **complete agent build**: model, scaffold, prompts,
tools, memory, policies, budgets, and version together. A model-only score is not
enough to explain whether an internal security agent improved.

The primary task is an **active challenge**: a real running application or
topology that responds to participant actions and may move through controlled
releases. This supports both one-shot offensive agents and continuous agents
that must notice a new component, avoid retesting unchanged surfaces, close a
fixed finding, and rediscover a regression.

Public CTF/CVE packs remain useful for calibration. Held-out/private challenges,
immutable identities, repeated trials, and independent validators are required
for a defensible comparison.

## Two operator journeys

- **Engagement:** one human or agent researches one challenge or ad-hoc target.
- **Evaluation:** pinned agent builds run repeated trials over a challenge suite
  and are compared on verified capability, regressions, latency, cost, and safety.

Both journeys use the same arena, gateway, event, evidence, validation, and
scoring engine.

## Product model

```text
Target + Scenario + truth/validators/episode
                 ↓
              Challenge ───────────────┐
                 │                     │
          Engagement              Evaluation
                 │            agent builds × suite × trials
                 │                     │
                 └──────────┬──────────┘
                            ↓
                         Run/Arena
                            ↓
             findings · evidence · trace · score
```

- A **Target** is an immutable Git object, OCI digest, source bundle, package,
  or future binary/VM identity.
- A **Scenario** is the provider-neutral topology specification.
- A **Challenge** adds participant instructions, visibility, truth/objectives,
  validators, and an optional staged episode.
- An **Arena** is temporary live infrastructure; durable engagement/run records
  and evidence survive its destruction.

---

## The engine pipeline

```text
Operator console
      │
      ├── choose/ingest target + challenge
      ├── review identity, setup, containment and limits
      ▼
Orchestrator ──tasks──▶ Worker ──provider──▶ isolated running arena
      │                                           │
      │ bind human/agent stance                   │ observed effects
      ▼                                           ▼
MCP gateway / external driver              monitor + validators
      │                                           │
      └──────── actions/findings/evidence ────────┘
                            │
                            ▼
                  events + trace + Score
                            │
                            ▼
                 run export / comparison
```

### Provisioning and target identity

- Scenario schema v3 defines arbitrary nodes and network segments.
- Docker-local creates per-arena networks and real containers.
- SUT targets can originate from pinned Git, digest-pinned public OCI images,
  or bounded local source bundles.
- Existing Dockerfiles are preferred; verified synthesis and package tiers fill
  gaps. Setup can be operator-scripted, HITL, or double-locked autonomous.

### Agent boundary

- Server-enforced key↔arena bindings and stance-scoped MCP tools.
- Attacker, MITM, defender, and special configurator capabilities.
- Provider-enforced containment, command limits, and append-only traces.
- Generic drivers for persistent/container/external agents are planned for the
  evaluation workbench; product-specific agent logic does not enter Nidavellir.

### Evidence and scoring

- Monitor signals cover crashes, sanitizer aborts, OOM/resource faults, and
  unhandled 5xx behavior.
- Deterministic validators prove effects such as observed XSS execution, marker
  disclosure, OAST callbacks, or correlated crashes.
- Verdicts are tri-state: confirmed, refuted, or unknown. Only confirmed earns
  credit; unknown is never silently converted into refuted.
- Benchmark mode scores against hidden truth. Discovery mode reports confirmed
  findings and fault sites without pretending that unknowable false negatives
  are zero.
- Structured scores, OpenInference-aligned traces, dataset export, and replay
  are already shipped.

---

## The console

The console is organized around operator intent rather than implementation
increments:

```text
Home
Engagements
Evaluations
Library → Challenges · Targets · Agents
Activity → Findings · Evidence · Audit trail
Administration
```

One New Engagement journey composes purpose, source, participants, and an enforced
time box, then hands off to the validated builder for every launch path. An
engagement opens as a contextual workspace:

```text
Overview · Live · Target · Findings · Evidence · Changes
Agent · Trace · Score · Infrastructure
```

Only applicable tabs render, setup is a phase rather than a permanent block, live
state and audit events stream over SSE, and a destroyed arena becomes a read-only
record whose evidence stays reviewable. Activity carries cross-engagement Findings
and Evidence indexes; legacy routes remain valid. Evaluations, the Targets and
Agents libraries, and the administration destinations are reserved routes whose
durable data models ship with E1–E5. See
[ADR-0012](./adr/0012-gui-first-product-model.md).

---

## Current status

- **Shipped:** dynamic Docker arenas, SUT provisioning, secure target intake,
  setup gates, monitoring, validators, structured scoring, findings/PoCs,
  eval export, reference harness, batch execution, replay, Git evidence,
  file transfer, target-scoped browser tooling, and the GUI product model.
- **Shipped console:** grouped navigation, unified engagement creation, the
  contextual engagement/run workspace with SSE live state, an object-driven Home,
  and cross-engagement Findings/Evidence indexes.
- **Next:** HTTP replay/modify, confined PoC sandbox, tunnelling, durable budgets
  and kill switches; followed by the GUI evaluation workbench.
- **Evaluation gap:** durable Agent build/Suite/Evaluation/Run/Trial records,
  active episode schedules, and paired N-vs-N+1 comparison do not exist yet.
- **Provider boundary:** Docker-local is mature. OpenStack, AWS, and libvirt are
  validation-level skeletons with no supported live apply.
- **Security boundary:** this remains a trusted-host/single-team system and is
  not safe to expose directly to an untrusted network; see
  [`SECURITY.md`](./SECURITY.md).
- **Verification:** the declared Python 3.11 container gate records 808 passing
  tests with Ruff and Bandit clean. Host Python 3.13 currently hangs in
  Starlette `TestClient` and is not the supported full-test path.
