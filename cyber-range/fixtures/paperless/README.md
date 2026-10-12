# Paperless-ngx fixture (Nidavellir research lane)

Pinned, pre-seeded Paperless-ngx 3.3.0 for local authorization research.
Seeded through the HTTP API and explicit fixture-only Django setup: an `admin`
owner, a `member` with global view and selected mutation permissions, restricted,
shared and member-owned documents, version controls, mail accounts and rows, and
an admin-created share link. Foreign objects retain their separate ownership.
Synthetic lab credentials only.

## Build

```bash
python3 cyber-range/fixtures/paperless/build_fixture.py
```

Writes `docs/verification/paperless-fixture-3.3.0.json` (IDs, control
matrix, behavior digest — no auth material; verifiers re-derive tokens
via the lab passwords in `build_fixture.py`). The build asserts its own
control matrix before returning:

| Check | Expected |
|---|---|
| owner reads restricted doc | 200 |
| member reads restricted doc | 404 |
| member reads shared doc | 200 |
| member lists documents | 200 |
| owner reads mail-consumed doc | 200 |
| member reads mail-consumed doc | 404 |
| member lists processed mails | 200 |

The mail cells cover a GreenMail 2.1.14 sink (digest-pinned, same pattern:
arch digest, SMTP 3025 + IMAP 3143 + HTTP API) with one seeded mailbox,
one consumed message, one admin mail account and one consuming rule. Reset
covers the sink: the seed recreates the mailbox user. Equivalent behavior must be
verified by separate builds; stable IDs alone would not establish equivalence.

Reset is deleting the `paperless-fixture-*` volumes and re-running the
script. The historical assertion of two identical builds is unverified: the old
retained manifest establishes one build only. See
[historical reconciliation](../../../docs/verification/research-history-reconciliation-2026-10-11.md).

## Auth notes (3.3.0, learned by probing)

- Tokens from `POST /api/token/` (not `/api/auth/token/`); calls use
  `Authorization: Token <key>`.
- A member needs global view permissions for the list endpoint; denied
  objects answer 404, not 403.
- Historical assertions about nine initial endpoint refutations have no retained
  per-probe proof and remain unverified. Registered probe results are narrower:
  interpret each request, positive control and observed effect separately.

## Pin gotcha

Pin the arch-specific image digest (e.g. amd64), not the manifest-list
digest: the list digest is not directly runnable by the daemon
(`manifest unknown`), so `build_fixture.py` pins Vaultwarden-style per
architecture. Re-resolve at each version pin.

## Research status

No novel finding is established by the historical records. New probing uses a
committed registration, legitimate member-owned mutations and mixed-batch effect
checks. Static inventories retain unresolved candidates and do not establish
exhaustion. Fixture HTTP bindings are loopback-only; credentials and data are
synthetic. The fixture owns only its `paperless-fixture-*` resources.
