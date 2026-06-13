# CyberGuard — Security Posture & Threat Model

> **Status (2026-06): NOT safe to expose to an untrusted network.**
> The `docs/README.md` "Production Ready" badge refers to feature completeness
> of the mock/OpenStack workflow, **not** to a hardened security posture. Treat
> the current build as a trusted-LAN / single-operator tool until Phase 1 of the
> [ROADMAP](../ROADMAP.md) lands.

This document tracks the known security gaps so they are visible and tracked,
not hidden. Each item links to the roadmap phase that closes it.

## What CyberGuard does (attack surface)

CyberGuard takes API/web requests and, in production mode, runs `tofu apply`
against a real OpenStack cloud — i.e. it turns HTTP input into infrastructure
and shell execution. That makes the input-validation and authn/authz boundaries
the most security-sensitive part of the system.

## Known gaps (audit, June 2026)

| # | Severity | Gap | Location | Closed by |
|---|----------|-----|----------|-----------|
| 1 | **High** | No authentication or authorization. Any caller can deploy, list, or destroy **any** lab. | `api.py` (all routes) | **Fixed** — API-key auth on all data routes + WebUI session login ([ADR-0002](adr/0002-api-authentication.md)). Note: per-lab *ownership* enforcement still arrives with multi-tenancy (Phase 3); demo defaults (`dev-insecure-key`, `admin`/`cyberguard`) must be overridden per the checklist below. |
| 2 | **High** | Hardcoded Flask `secret_key` and `debug=True` in source. | `webui/app.py` | **Fixed** — now env-driven (`SECRET_KEY`, `FLASK_DEBUG`) |
| 3 | **High** | No CSRF protection on state-changing WebUI routes (`/create`, `/api/destroy`). | `webui/app.py` | **Fixed** — Flask-WTF `CSRFProtect` on all POSTs (forms + `X-CSRFToken` header for JS) |
| 4 | **Med**  | Unvalidated user input (`scenario`, `instance_id`) flows toward Terraform `-var` args and workspace paths. Server-generated UUID mitigates the deploy path today, but the validation boundary is missing. | `api.py`, `orchestrator.py` | Phase 1 |
| 5 | **Med**  | Bare `except:` clauses swallow errors and can mask failures (incl. security-relevant ones). | `api.py:43-47,99-103`, `orchestrator.py:212` | Phase 1 |
| 6 | **Med**  | Secrets (OpenStack creds, SOC passwords) logged/echoed and stored in plaintext in the DB `outputs` column. | `database.py`, `orchestrator.py` | **Fixed** — OpenTofu stderr / logged variable dicts are run through `redaction.py` before logging or surfacing in API errors; lab outputs are encrypted at rest with Fernet (`crypto.py`) when `SECRETS_ENCRYPTION_KEY` is set. See *Secrets handling* below. |
| 7 | **Med**  | No rate limiting; a single client can exhaust the worker pool / cloud quota. | `api.py` | **Fixed** — slowapi per-client limits on `/deploy` (10/min) and `/destroy` (30/min), tunable via `RATE_LIMIT_*` env; per-user quotas follow in Phase 3 |
| 8 | **Low**  | No network isolation guarantees between concurrent tenant labs are documented/enforced. | `infra/terraform/network.tf` | Phase 2 |

## Secrets handling (audit #14)

Two layers protect lab and cloud secrets:

- **Redaction in logs/errors** (`redaction.py`). OpenTofu runs with the
  OpenStack credentials in its environment and echoes them into stderr on
  failure; we log that stderr and also return it in API-visible error strings.
  `redact()` masks (a) the literal values of known secret env vars
  (`OS_PASSWORD`, `BOOTSTRAP_API_KEY`, `SECRET_KEY`, `SECRETS_ENCRYPTION_KEY`,
  and any password embedded in `DATABASE_URL`) and (b) `key=value` / JSON pairs
  whose key looks sensitive. `redact_mapping()` masks sensitive keys in logged
  variable dicts (scenario vars, `user_vars`).
- **Encryption at rest** (`crypto.py`). The `deployments.outputs` blob (SOC
  credentials, SSH commands, IPs) is encrypted with Fernet before it is written
  to the database and decrypted transparently on read by the `Database` facade.
  Enabled by setting `SECRETS_ENCRYPTION_KEY` to a urlsafe-base64 32-byte key
  (`python -m crypto` generates one). When unset, values pass through in
  plaintext — fine for the mock/dev demo, but a real run logs a startup warning.
  Encrypted values are tagged `enc:v1:` so legacy plaintext rows stay readable.

  **Out of scope (follow-ups):** key rotation; sourcing the key from a KMS /
  secrets manager instead of an env var; and the hardcoded SOC password in the
  OpenStack template (`infra/terraform/outputs.tf`) — that belongs with
  scenario-package parameterization. The `outputs` API responses still return
  decrypted credentials to any authenticated caller; narrowing that to the
  lab's owner is multi-tenancy work (gap #1 / Phase 3 RBAC).

## docker-local provider: Docker socket implications

The `docker-local` provider (ADR-0003) talks to the host Docker daemon. A
worker that can reach `/var/run/docker.sock` is **root-equivalent on that
host** — only enable it (the socket mount + `RANGE_PROVIDER=docker-local`)
on machines where the operator already owns the host, i.e. laptops and
dedicated lab hosts, never on a shared control-plane node. Lab containers
get a dedicated bridge network per lab; full egress lockdown for agent
training is tracked separately (roadmap Phase 5 guardrails).

## Reporting a vulnerability

This is an educational project. If you find a security issue, open a private
report to the maintainer rather than a public issue. Do not include live
credentials in reports.

## Hardening checklist before any internet-facing deployment

- [x] Authentication on the API and WebUI (Phase 1 — ADR-0002)
- [ ] `CYBERGUARD_API_KEY`, `WEBUI_USERNAME`/`WEBUI_PASSWORD` overridden (no demo defaults)
- [ ] `SECRET_KEY` set to a strong random value; `FLASK_DEBUG` unset
- [ ] Reverse proxy with TLS in front of both services
- [ ] API not bound to `0.0.0.0` on an untrusted interface
- [x] Rate limiting enabled (on by default; `RATE_LIMIT_ENABLED=false` only for tests)
- [ ] OpenStack credentials supplied via secrets manager, not `.env` on disk
- [ ] `SECRETS_ENCRYPTION_KEY` set so lab outputs are encrypted at rest (`python -m crypto`)
- [ ] Per-tenant network isolation verified
