# ADR-0003: Pluggable deployment providers behind a RangeProvider interface

- **Status:** Accepted
- **Date:** 2026-06-11
- **Deciders:** Nidavellir maintainers

## Context

The orchestrator was hard-wired to one backend: a fixed OpenStack OpenTofu
template, with a `MOCK_MODE` boolean short-circuiting it for demos. The
product direction (ROADMAP rev. 2026-06) requires the same scenario to run
on a laptop (containers), on OpenStack (today's deployments), and on AWS
(hosted platform) — and cheap, fast lab instances are a prerequisite for
agentic-pentest training loops, where an agent may consume dozens of labs.

## Decision

Introduce a **driver interface** and make the Orchestrator a dispatcher:

```
orchestrator.py            # loads scenario config, picks provider, delegates
providers/
  base.py                  # RangeProvider ABC: deploy(config, id, vars) / destroy(id)
  mock.py                  # canned outputs (extracted from the MOCK_MODE branch)
  openstack.py             # per-lab OpenTofu workspaces (extracted real-mode logic)
  __init__.py              # registry + get_provider()
```

- **Selection precedence:** explicit argument → `RANGE_PROVIDER` env →
  legacy `MOCK_MODE=true` → `openstack` default. `MOCK_MODE` keeps working
  so nothing in compose/docs/tests breaks.
- **Contract:** providers receive the *parsed scenario config* (loading and
  the path-traversal guard stay above the interface, in `scenarios.py`) and
  return the existing dict shape (`{"success", "outputs"|"error"}`) with
  **flat** outputs ({name: value}, no terraform envelopes). `destroy` is
  idempotent.
- **Scope of this change:** pure refactor — no behavior change except one
  deliberate fix: mock deployments of nonexistent scenarios now fail like
  real ones instead of fake-succeeding (the API already blocks them anyway).

## Alternatives considered

- **Status quo (`if mock_mode:` branches)** — every new backend multiplies
  the conditionals through deploy/destroy/outputs; untestable combinations.
- **Provider == Terraform module selection only** — would force docker-local
  labs through Terraform for no benefit; the docker SDK is the natural
  driver there, and a shared `TerraformDriver` base can still be factored
  out for openstack/aws when aws lands.
- **Typed result objects now** — deferred; tasks.py and the DB consume the
  dict shape today. Worth doing together with the Phase-3 state machine.

## Consequences

- Positive: `docker-local` (Phase 2) and `aws` (Phase 7) become additive
  modules + a registry entry; the Orchestrator/API/tasks stay untouched.
  Tests can inject fake providers (dispatch is now unit-testable).
- Negative / accepted: scenario→infra mapping (`_extract_terraform_vars`)
  is still the legacy fixed-3-VM shape inside the openstack provider; the
  generic `nodes[]` compilation arrives with the scenario-package work
  (Phase 4 / backlog P1-5).
- Follow-ups: `validate(scenario)` hook on the interface once scenarios
  declare requirements (`provider_class: vm|container`); per-provider image
  maps; `RANGE_PROVIDER` surfaced per-deployment in the API rather than
  per-install.
