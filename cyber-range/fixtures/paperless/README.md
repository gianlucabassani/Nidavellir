# Paperless-ngx fixture (Nidavellir research lane)

Pinned, pre-seeded Paperless-ngx 3.3.0 for local authorization research.
Seeded entirely through the product's own HTTP API: an `admin` owner, a
`member` with global view permissions, two documents (one restricted,
one shared with the member via an object-level view grant), explicit
permissions, and one admin-created share link on the shared document.
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

Reset is deleting the `paperless-fixture-*` volumes and re-running the
script; two consecutive builds produced identical object IDs, matrix and
behavior digest.

## Auth notes (3.3.0, learned by probing)

- Tokens from `POST /api/token/` (not `/api/auth/token/`); calls use
  `Authorization: Token <key>`.
- A member needs global view permissions for the list endpoint; denied
  objects answer 404, not 403.
- Refuted hypotheses on 3.3.0 (all correctly denied, not findings):
  share-link creation for an unpermitted doc, bulk edit, selection data,
  notes, download, metadata, thumb, versions endpoints.

## Research status

Calibration-ready with proven controls. No novel finding banked —
per the fail-closed rule the hypotheses above are recorded refuted and
the hunt stops here until the next approved campaign.
