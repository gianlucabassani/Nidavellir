# ADR-0002: API-key authentication with roles; session login on the WebUI

- **Status:** Accepted (**superseded in part** — 2026-06-13 enterprise-arena
  pivot: the role set `instructor`/`student` is renamed to **`operator`**
  (`admin`/`agent` unchanged); see `ROADMAP.md` Phase 0 and
  `.agent/proposals/VISION.md`. The API-key mechanism below is otherwise
  unchanged. `attacker`/`MITM`/`defender` are per-session agent *stances*
  chosen via the MCP gateway, not auth roles.)
- **Date:** 2026-06-10
- **Deciders:** CyberGuard maintainers

## Context

The audit (ROADMAP #2, SECURITY gap #1) found the platform fully
unauthenticated: any network caller could deploy, list, or destroy any lab —
and in production mode that means turning anonymous HTTP into `tofu apply`
against a real cloud. Phase 1 requires an authentication boundary that:

- is simple enough to ship now, on SQLite, without a user-management UI;
- serves *programmatic* callers first (the WebUI backend, scripts, CI — and
  soon the Agent Gateway, whose AI-agent callers authenticate the same way);
- doesn't paint us into a corner for Phase 3 (users/orgs/ownership/RBAC) or a
  later OIDC integration.

## Decision

**Static API keys with roles, checked by a FastAPI dependency.**

- Key format `cg_<48 hex>` (192-bit random, `secrets`). Sent as `X-API-Key`.
- Only the **SHA-256 digest** is stored (`api_keys` table). High-entropy
  random tokens need no slow hash — unlike passwords there is no
  low-entropy structure to brute-force; a DB leak still reveals no keys.
- Each key has a `name` (audit identity, logged on deploy/destroy) and a
  `role` ∈ {`admin`, `instructor`, `student`, `agent`}. **Today every valid
  key may call every route** — roles are *recorded but not yet enforced*;
  enforcement (ownership, quotas) lands with multi-tenancy in Phase 3 so we
  don't invent throwaway authz semantics now. The `agent` role exists from
  day one for the Phase-5 Agent Gateway.
- Keys are revoked, never deleted (audit trail). Management via
  `python auth.py create-key|revoke-key` (prints the key exactly once).
- **Bootstrap:** `BOOTSTRAP_API_KEY` env is registered at API startup
  (idempotent). docker-compose feeds the same value to the WebUI as
  `ORCHESTRATOR_API_KEY`; the default `dev-insecure-key` is a well-known
  demo value that triggers a loud startup warning.
- `GET /health` is the only unauthenticated route (container healthcheck).
- **WebUI:** Flask session login (`WEBUI_USERNAME`/`WEBUI_PASSWORD` env,
  constant-time compare, relative-only redirect targets). The browser never
  sees the API key — only the Flask backend holds it.

## Alternatives considered

- **JWT (self-issued)** — adds signing-key management, expiry/refresh logic,
  and clock concerns for zero benefit while we have no user database; tokens
  in logs are as leakable as keys. Revisit when sessions for humans and
  short-lived agent credentials matter.
- **OIDC (Keycloak/Authentik/Cognito)** — right end-state for human SSO in a
  multi-tenant deployment, wrong first step: heavy operational dependency
  before there are even users. The API-key dependency is the seam where an
  OIDC bearer-token validator will slot in (Phase 3+), keeping API keys for
  machine callers.
- **mTLS** — strong but operationally painful for classroom/laptop use and
  awkward for the browser path.
- **bcrypt/argon2 for key storage** — wrong tool: those defend low-entropy
  passwords; for 192-bit random keys SHA-256 is sufficient and keeps lookups
  O(1) by digest.

## Consequences

- Positive: every state-changing call is attributable (`name`, `role`) in
  logs; the WebUI demo still works out of the box; agents and humans share
  one auth mechanism; tests run fully authenticated.
- Negative / accepted debt: no per-key expiry or rate limits yet (rate
  limiting is a separate Phase-1 item); roles unenforced until Phase 3; the
  dev default key and WebUI password are insecure by design for the local
  demo — SECURITY.md's hardening checklist requires overriding them.
- Follow-ups: Phase 3 binds keys to user accounts and enforces ownership;
  the Agent Gateway (Phase 5) issues scoped, budgeted agent keys; OIDC ADR
  when multi-tenant SSO becomes real.
