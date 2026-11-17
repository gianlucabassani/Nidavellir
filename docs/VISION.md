# Vision

> Nidavellir is the GUI-driven, bring-your-own-agent arena for security work on
> real running systems, serving two objectives on one engine: **discovery** of
> real vulnerabilities, and **evaluation** of the agents that hunt them.

## Purpose

Nidavellir provisions reproducible running targets and multi-machine
topologies, gives a human or external agent a contained research position,
observes what actually happens, independently verifies evidence, and turns the
session into a scored, replayable, auditable result.

That substrate is deliberately dual-purpose.

**Discovery.** As a vulnerability research platform, Nidavellir removes the
unglamorous friction of real product research: standing a target up at an exact
identity, containing it, working it from a stable position, and proving afterwards
precisely what was hit. The output is a defensible vulnerability record — finding,
PoC, observed effect, affected identity, disclosure state. Here the **target** is
under test and the participant, human or agent, is the instrument.

**Evaluation.** As an agent evaluation arena, Nidavellir measures complete security
agents — model, scaffold, tools, memory, policies, budgets together — over held-out
active challenges, and compares builds on verified capability rather than claims.
Here the **AI** is under test and Nidavellir is the environment factory, capability
boundary, observer, referee, and comparison layer.

It is neither the autonomous pentesting agent nor a generic model benchmark.
Humans author and operate the work.

The objectives share one engine and one evidence model, and they meet at a single
asset: **a challenge is a solved discovery problem with its truth withheld.**
Verified findings from real research are the only honest source of held-out
evaluation material — public CTFs and known-CVE packs calibrate, but cannot settle
a comparison. That is why the platform is built to be useful to a researcher
before it is built to rank an agent.

## Product journeys

### Engagement

One human or agent researches one challenge or ad-hoc target in a live arena.
The operator configures it, observes work, and reviews proof. An engagement
declares its purpose: *discovery* and *manual research* serve the discovery
objective, while *benchmark* and *calibration* serve measurement. The declared
purpose changes the result model, never the containment or the validators.

### Evaluation

Pinned agent builds run repeated trials over a challenge suite. Nidavellir
compares verified capability, regressions, latency, cost, and safety without
exposing hidden truth to the participant.

Both journeys reuse the same arena, gateway, event, evidence, validation, and
scoring engine. The console is the complete normal operator surface; APIs remain
the service boundary and automation seam.

## Active challenges

The primary benchmark is an active challenge: a real running system whose state
and responses change as the participant acts. A challenge may stage controlled
releases—baseline, changed component, fixed release, regression—so continuous
agents can be measured on detection latency and selective retesting, not only
one-shot exploitation.

Public CTFs and known-CVE environments are calibration. A defensible agent
comparison uses pinned, held-out or private challenges, repeated trials,
declared leakage policy, independent validators, and the complete
model+scaffold+tools+cost identity.

## Engine pillars

1. **Dynamic topologies and target intake.** Provider-neutral scenarios describe
   arbitrary nodes and network segments. Targets resolve to immutable Git, OCI,
   bundle, package, or future binary/VM identities.
2. **Scoped participant runtime.** Humans and external agents enter contained
   arenas through explicit roles/stances, capabilities, budgets, and traces.
3. **Independent evidence and comparison.** Monitor signals, deterministic
   validators, structured scores, immutable identities, and replay make agent
   version comparisons explainable.

## Scope boundary

Nidavellir builds integration surfaces and a safe substrate only. It does not
ship an AI attacker, MITM, defender, judge, or proprietary generator. Reference
connectors are thin, optional wiring samples. The agent, model, key, and scaffold
belong to the operator. Targets are owned or explicitly authorized and run
behind provider-enforced containment.

**AI-centered, never AI-required.** A human pentester can operate an engagement
and submit evidence without a model. MCP is an additional, measured way into the
same arena, never the only way.

## GUI-first, service-backed

Every normal operator workflow is complete in the browser: create an engagement,
configure a target, attach an agent, observe work, review evidence, run an
evaluation, and compare builds. The console remains a thin client of the
orchestrator/services. Business rules do not migrate into Flask merely because
the product is GUI-driven.

## Product language

- **Target:** immutable software/artifact identity.
- **Scenario:** provider-neutral topology specification.
- **Challenge:** scenario + target + participant brief + visibility + truth and
  validators + optional episode.
- **Agent build:** pinned external system under test.
- **Engagement:** one operator-led research session.
- **Evaluation:** agent builds × challenge suite × trials × budgets.
- **Run:** one agent build on one challenge for one trial/seed.
- **Arena:** temporary live infrastructure owned by an engagement or run.
- **Evidence:** findings, PoCs, signals, artifacts, changes, traces, and verdicts.

## Success

Nidavellir succeeds when an operator can select two pinned security-agent builds,
run them repeatedly against identical held-out active challenges, and determine
from independently verified evidence exactly where capability, false positives,
latency, cost, or safety improved or regressed.
