# ADR-0012: GUI-first product model and console information architecture

- **Status:** Accepted — the GUI-first product model and acceptance items 1–4
  are implemented. The original Flask/Jinja renderer choice is superseded by
  ADR-0017; full evaluation workflow parity remains tracked in E5.
- **Date:** 2026-08-10
- **Deciders:** Gianluca Bassani

## Context

Nidavellir's backend grew through independently valuable vertical slices:
scenario authoring, predefined launch, custom topology launch, SUT intake and
setup, arenas, agent bindings, findings, scoring, change evidence, browser/file
tools, logs, and model-assisted generation. The current Flask/Jinja console
exposes those increments as top-level implementation-era pages such as Launch,
SUT, Inventory, Arenas, Logs, and Agents.

That structure was sufficient while the product unit was one arena. The next
major capability is repeated agent evaluation: registered agent builds,
challenge suites, trials, runs, and comparisons. Adding those as more sibling
pages would make the UI harder to understand and would split shared concepts
between manual research and evaluation.

Nidavellir is also intentionally GUI-driven. Operators should not need a CLI to
perform normal work. At the same time, putting orchestration or persistence in
Flask routes would duplicate the control plane and make future automation
fragile. The console must therefore be browser-complete and API-backed.

## Decision

### 1. Organize around operator intent

The primary product journeys are:

- **Engagement:** one human or agent researches one challenge/ad-hoc target.
- **Evaluation:** pinned agent builds run repeated trials over a challenge suite
  and are compared.

Both reuse the same arena lifecycle and evidence/scoring systems. An arena is a
live execution resource owned by an engagement or run, not the highest-level
navigation concept.

### 2. Adopt explicit product objects

The operator-facing model is Target, Scenario, Challenge, Agent build,
Engagement, Evaluation, Run, Arena, and Evidence, as defined in `ROADMAP.md`.
The existing provider-neutral `Scenario` remains an engine concept. A Challenge
adds the participant brief, target identity, visibility, objectives/truth,
validators, and optional staged episode.

### 3. Adopt the new navigation

```text
Home
Engagements
Evaluations
Library
  Challenges
  Targets
  Agents
Activity
  Findings
  Evidence
  Audit trail
Administration
```

A global Create action starts an Engagement, Evaluation, Challenge, Target, or
Agent workflow. Existing routes may remain as compatibility aliases during the
migration.

### 4. Use one contextual workspace

The current arena detail page is decomposed into a shared engagement/run
workspace with contextual tabs:

```text
Overview · Live · Target · Findings · Evidence · Changes
Agent · Trace · Score · Infrastructure
```

Only applicable tabs render. Setup is a lifecycle phase inside the workspace.
Destroyed arenas retain a read-only result/evidence view.

### 5. Keep the console thin

The original Flask/Jinja renderer choice is superseded by ADR-0017. The product
boundary remains: business rules, records, scheduling, validation, scoring, and
lifecycle transitions live behind service APIs. Flask owns the same-origin
session and BFF boundary; the browser renderer must not become a second control
plane. New backend capabilities remain independently usable through their APIs.

### 6. Migrate incrementally with feature parity

The order is:

1. prototype and route/object map;
2. application shell and grouped navigation;
3. unified engagement creation;
4. contextual engagement/run workspace and SSE;
5. activity indexes and Home;
6. evaluation registry, suites, trials, and comparisons.

Existing pages remain usable until their replacement covers the same behavior.
No backend vertical is rewritten merely to fit the new navigation.

## Consequences

- **Positive:** evaluation becomes a native journey instead of another page
  attached to arena operations.
- **Positive:** every current capability receives a stable, predictable home.
- **Positive:** manual research and repeatable evaluation share one product
  model without being conflated.
- **Positive:** browser completeness is preserved while API/service boundaries
  remain suitable for agents, CI, and future Inspect integration.
- **Positive:** the application can be migrated without a high-risk frontend or
  backend rewrite.
- **Cost:** route aliases, navigation state, and transitional templates must be
  maintained during migration.
- **Cost:** product records such as Agent build, Evaluation, Run, and Trial need
  durable models before their final screens can ship.
- **Risk:** a purely cosmetic redesign could leave the object confusion intact.
  Acceptance is therefore task- and feature-parity-based, not screenshot-based.

## Alternatives considered

- **Add a Benchmarks page to the current sidebar.** Rejected: it leaves Launch,
  SUT, Inventory, Arenas, Agents, and future Runs/Comparisons competing at one
  level and duplicates shared workflows.
- **Make the arena the permanent top-level unit.** Rejected: an evaluation owns
  many runs/arenas, while a durable result must survive arena destruction.
- **Create a separate benchmark application.** Rejected: it would duplicate
  target provisioning, observation, evidence, validation, scoring, and auth.
- **Rewrite the console as a SPA immediately.** Rejected: the problem is product
  structure, not rendering technology; it would increase migration risk without
  clarifying the model.
- **Expose the new workflow only through a CLI/API.** Rejected: Nidavellir is an
  operator console and normal workflows must be complete in the browser.

## Acceptance

Items 1–4 were accepted with C1–C4. Item 5's durable evaluation records now
exist, but complete browser comparison parity remains an E5 item in
[`TODO.md`](../../TODO.md).

The decision is accepted when:

1. a reviewed prototype and route map cover every current function;
2. the new application shell is live with compatibility routes;
3. all existing launch/SUT paths work through New Engagement;
4. the arena detail capability is available through the contextual workspace;
5. an operator can configure and compare a repeated evaluation entirely in the
   GUI without business logic living in WebUI routes.
