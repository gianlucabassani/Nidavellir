# ADR-0005: MCP agent gateway — protocol, stances & guardrails

- **Status:** Accepted (landed: lifecycle tools + auth + stance binding; the
  **attacker** stance — `get_topology`/`list_targets`/`run_command` with
  foothold-scope, step-budget, audit + trace + provider exec primitive; the
  **defender** stance — `query_events`/`get_topology` over the audit stream; and
  **default-on egress containment** — locked arenas use Docker `internal`
  segment networks with a no-masquerade ingress bridge for browser access,
  proven by a CI containment test; and the **allowlisted apt/pip mirror** — a
  per-arena squid sidecar (dual-homed: egress bridge + each internal segment as
  `mirror`) that lets a contained foothold `apt`/`pip install` tooling from
  package repos ONLY, with no general egress (live-verified: nmap installs and
  scans in-scope while the internet stays unreachable); and **server-enforced
  per-arena key↔arena binding** — guardrail #6 below, the orchestrator-side
  authorization that closes audit finding D1. **Deferred:** MITM stance,
  per-request HTTP auth, token budget, operator kill switch.)
- **Date:** 2026-06-14
- **Deciders:** Nidavellir maintainers

## Context

The product's priority pillar is testing **bring-your-own AI agents** against
arenas (VISION.md, ROADMAP Phase 2). An agent is the system under test; it must
reach an arena **only** through a controlled surface that authenticates it,
binds it to a single **stance** (attacker / MITM / defender), scopes and meters
what it can do, and records every action. Nidavellir builds this *integration
surface* — never the AI itself (the model + key are the user's; scope boundary
in VISION.md).

Constraints: the gateway is the sole path into an arena; agents execute commands
inside arenas (so containment is safety-critical); it must stay a decoupled,
separately-deployable service; and it must work in `MOCK_MODE` for free,
deterministic CI.

## Decision

We will ship a dedicated **`services/agent-gateway/`** built on the **official
MCP Python SDK** (`FastMCP`), transports **stdio** (dev) + **streamable-HTTP**
(prod). It talks to the orchestrator over the **REST API** (it does not import
it), forwarding the agent's API key so the orchestrator stays the authz + audit
authority. Tool *logic* is transport-agnostic and unit-tested; the MCP layer is
a thin wrapper.

**Stances.** A session binds to at most one stance. Shared **lifecycle** tools
(`list_scenarios`, `deploy_arena`, `arena_status`, `get_briefing`,
`destroy_arena`) are available to every session; **per-stance execution**
toolsets are gated by an allow-list (`stances.allowed_tools`):
- **attacker** — `run_command` (docker exec / SSH on the foothold), `upload/
  download_file`, `report_finding` (self-report a discovered known vuln, matched
  against the hidden manifest by CWE + node — the 2026-06-16 manifest model that
  replaced `submit_flag`);
- **MITM** — in-path `observe_stream` / `modify_message` on a shared segment;
- **defender** — `query_events`, `get_alerts`, `submit_detection`.

**Guardrails (server-enforced, non-negotiable):**
1. **Network containment is the primary control**, provider-enforced, not
   agent-enforced: arena segments have **no internet egress**. For docker-local
   this is `internal` networks **plus an allowlisted package/tool mirror**
   sidecar (so a Kali foothold can still `apt`/`pip` install during a run
   without a route to the internet) — the chosen posture. AWS gets the same by
   construction (no IGW/NAT, VPC-confined SG — see ADR-0006).
2. **Scope screen** — best-effort static check of targets against the scenario
   `scope.json` (defense in depth; #1 is the real control).
3. **Budgets** — per-session step budget, wall-clock (≤ arena TTL), per-command
   timeout, per-key token budget; exceeding freezes the arena and marks the run.
4. **Identity & audit** — `agent` principal; every tool call → append-only JSONL
   trace (+ the orchestrator `events` table). The raw API key is never logged or
   traced (a derived `agent_id` is used).
5. **Kill switch** — an operator can freeze/destroy any agent arena.
6. **Per-arena key↔arena binding (server-enforced — closes D1).** The gateway's
   stance gate is client-side only, so a direct REST call to the orchestrator
   bypassed it: any valid `agent` key could `exec` / configure / report findings
   on **any** arena. The orchestrator now requires that an `agent` principal hold
   an active **binding** to an arena before it may drive it, and the binding's
   **stance** scopes the capability *server-side* (e.g. `attacker` → exec is
   foothold-only; `configurator` → setup steps only). Bindings are event-backed
   (`agent_binding` / `agent_binding_revoked`, no migration; derived newest-first
   like the setup phase) and granted three ways: **auto on self-deploy** (the
   agent that deploys an arena owns that sandbox, `stance=null` unrestricted),
   an **operator grant** (`POST /arenas/{id}/bindings`, stance-scoped — the
   operator decides which BYO agent is the system-under-test), or **named at
   `setup/start`** (`agent_name` → a `configurator` binding revoked at `finish`,
   so the write/config capability is dropped before the engagement — the
   ADR-0007 hard privilege boundary). Operators/admins author and run engagements
   and manage every arena, so they are never bound and bypass the check. Reads
   (status / event feed) are intentionally **not** capability-gated — D1 is about
   *driving* an arena, and the finding feed is already ground-truth-redacted for
   agents. Residual: a multi-tenant per-operator orchestrator identity + token
   budget remain follow-ups (§2.1 D2/D3).

**Command execution** is *command-at-a-time* (no raw PTY in v1) into the
**foothold/entrypoint node only**, with a per-command timeout.

## Alternatives considered

- **Hand-rolled MCP on the existing FastAPI app** — less idiomatic for MCP
  clients, more protocol code to own. The SDK is the standard surface BYO
  clients (Claude Code, Agent SDK, others) already speak.
- **Gateway holds one service key, authenticates agents separately** — a second
  authz authority to keep in sync. Forwarding the agent key keeps the
  orchestrator the single source of truth.
- **Egress fully blocked (no mirror)** — strongest, but breaks the standard
  Kali install-tools-at-runtime workflow; the allowlisted mirror keeps
  containment while staying ergonomic.

## Consequences

- Positive: one audited, scoped, transport-standard entry point for any MCP
  agent; stances/guardrails are explicit and testable; the skeleton already
  drives arena lifecycle end-to-end over MCP in mock mode.
- Negative / cost: command execution + containment (the dangerous parts) are
  now landed and reviewed — attacker `run_command` is foothold-scoped + audited,
  egress is contained by default, and the package mirror has bounded egress (an
  allowlisted forward proxy, not a router). Residual risk: the mirror reaches
  the package repos, so it is a (narrow) egress path — extend its allowlist
  deliberately. Per-request HTTP header auth + the SDK auth providers
  (multi-tenant concurrent agents) remain a follow-up; the gateway resolves one
  agent key + stance per process. The mirror also appears as a host on the arena
  segment (a minor realism wart; it only exposes the proxy port).
- Follow-ups: attacker `run_command` + the docker `internal`+mirror containment
  + a CI canary test (arena node cannot reach an external host); then defender
  and MITM stances; budgets/kill-switch enforcement; scoring (Phase 4).
