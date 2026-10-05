# Affected-versus-fixed replay — design

**Date:** 2026-10-05
**Status:** Approved design (brainstorming complete); pending spec review
**Roadmap item:** NV-11 (first P2 research feature)
**Related:** `validators.py` (`http_access_control`), `docs/verification/vaultwarden-live-2026-10-05-b4c1bd2c.json`

## Context and intent

A researcher confirms a flaw on one target version. Proving it gone on the
fixed version is currently a manual exercise: deploy a second arena, repeat the
probe, keep both record sets, and compare by hand. The Vaultwarden calibration
(CVE-2026-26012 on 1.35.2 confirmed, 1.37.3 refuted) is exactly that work done
manually in `scripts/verify-vaultwarden-live.py`.

The intent is to make it first-class with the smallest possible surface:

- **Simple** — one optional field on the existing finding write path; one
  read endpoint; no new tables, no migration, no deploy automation.
- **Fast** — the researcher links a variant with one extra field and reads one
  grouped response; nothing to configure or carry between calls.
- **Effective** — the comparison states only what the evidence supports, using
  each arena's independent validator verdict under its healthy controls.
- **Scalable** — the event spine stays the single source of truth; a
  materialized link table is a documented, transparent upgrade if finding
  volume ever demands it.

NV-11's Git-diff artifact extension is **out of scope** here: for
image/commit-pinned targets the lifecycle recipe already carries identity. A
separate follow-up will cover variant hypotheses from source diffs.

## Goals

1. Link a finding to an earlier "reference" finding on another arena with
   `variant_of`.
2. Read the full group in one call: members, target identity, verdicts,
   evidence digests.
3. Derive the affected-versus-fixed conclusion from evidence only; no
   hand-typed role labels; unknown version identity stays unknown.
4. Keep the agent path working: the MCP `report_finding` tool forwards
   `variant_of`.

## Non-goals

- Auto-deploying a variant arena or selecting a version pin.
- New database tables or migrations.
- Console/UI work (the React console lives on `ui/royal-command`).
- Changing any validator semantics; a variant is validated exactly like any
  other finding in its own arena.
- Cross-arena search/listing beyond one finding group.

## Researcher workflow (fast path)

1. Confirm the finding on the affected arena (existing flow).
2. Deploy the fixed-version arena (any scenario/provider, as today).
3. In the fixed arena, make the probe request and report the finding with
   `variant_of: <affected finding_id>` — one extra field.
4. `GET /findings/<any member id>` returns the group and the evidence-derived
   outcome.

## Interfaces

### Write path

`FindingRequest` (both `POST /arenas/{id}/findings` and the operator manual
`POST /arenas/{id}/findings/manual`) gains:

```text
variant_of: str | None   # 12-hex finding id of an existing finding
```

On report, before recording:

- Invalid format or unknown id → HTTP 422 `unknown variant_of finding`.
- Self-reference is impossible in practice (the new finding id is generated
  after the link is resolved); the check is still enforced.
- `research_key` = referenced event's `research_key` if present, else the
  referenced finding's id (the root).
- The new finding event payload adds `variant_of` and `research_key`. Its own
  validation runs unchanged in the target arena.

The MCP gateway `report_finding` tool, `gateway.tools.report_finding` and
`RestClient.report_finding` add the same optional field.

### Read path

`GET /findings/{finding_id}` — operator-only (`_require_operator`); agents
receive 403. Unknown finding → 404.

Response:

```json
{
  "schema": "nidavellir/finding-group/v1",
  "research_key": "<root finding id>",
  "reference_finding_id": "<root finding id>",
  "members": [
    {
      "finding_id": "…",
      "arena_id": "…",
      "scenario": "vaultwarden-1352",
      "title": "…",
      "cwe": "CWE-639",
      "reported_at": "…",
      "actor": "…",
      "variant_of": null,
      "verdict": {
        "verdict": "confirmed",
        "reason_code": "unauthorized_disclosure",
        "validator_id": "http_access_control",
        "validator_version": 1,
        "action_digest": "sha256:…",
        "observation_digest": "sha256:…",
        "control_digest": "sha256:…"
      },
      "identity": {
        "known": true,
        "scenario": "vaultwarden-1352",
        "provider": "docker-local",
        "recipe_digest": "sha256:…",
        "images": {"target": "sha256:…"}
      }
    }
  ],
  "comparison": {
    "outcome": "disappeared_under_controls",
    "validator_comparable": true,
    "identity_match": "different_recipe",
    "counts": {"confirmed": 1, "refuted": 1, "inconclusive": 0,
               "infrastructure_failure": 0}
  }
}
```

Members are ordered root first, then by report time ascending. The group is
resolved by scanning `finding` events (type filter) for
`research_key == root` (and the root event itself). Findings are few; no
indexed table is required at this scale.

### Target identity

Built from `db.get_lifecycle_recipe(arena_id)` with a strict whitelist:
scenario id, provider, `recipe_digest`, and node image pins. Environment
variables, `validation_config`, markers, and credentials are never included.
An arena without a recipe (custom/SUT) yields `identity.known: false` with
null fields.

## Outcome semantics

A claim is made only when every member with a recorded verdict shares the same
`validator_id` and `validator_version` (`validator_comparable: true`) and no
member ended in `infrastructure_failure`.

| Condition (reference = root finding) | `outcome` |
|---|---|
| Fewer than two members, or any member `identity.known` is false, or the reference has no verdict | `unknown` |
| A non-root member is `confirmed` | `still_observed` |
| Reference `confirmed` and at least one non-root member `refuted` | `disappeared_under_controls` |
| Anything else (including incomparable validators or infrastructure failure) | `inconclusive` |

A `refuted` verdict already implies the validator's healthy controls passed,
so `disappeared_under_controls` means "effect not observed under matched
controls". The response never asserts that a version "is fixed".

`identity_match`: `same_recipe` when every member shares one recipe digest,
`different_recipe` when they differ, `unknown` when any identity is unknown.

## Errors and edge cases

- `variant_of` malformed or unknown → 422.
- Reference finding in the same arena (re-test) → allowed.
- Several variants, several levels: all resolve to one root via
  `research_key`; no cycles are possible because links only reference
  pre-existing findings.
- A member whose verdict is `inconclusive` (no linked action) does not block
  a `still_observed`/`disappeared` outcome by itself; it appears in counts.
- A member with no stored verdict at all is counted as `inconclusive` in
  `counts` and does not by itself force `unknown` (only the reference's missing
  verdict does).
- Reading an arena with no retained recipe → `known: false`, outcome
  `unknown` rather than a false claim.
- Retention: findings and recipes survive teardown like other evidence; the
  group read works on archived arenas.

## Security and visibility

- The read endpoint is operator-only; participant keys never see other
  arenas' findings, verdicts, or identities (consistent with the existing
  evaluation-record boundary).
- Identities expose pins and digests only; no credentials or probe plans.
- `variant_of` is an id reference validated against existing findings; it
  cannot inject data from another arena into a participant's view.

## Testing

- **Write path:** reporting with a valid `variant_of` stores both fields and
  the root key; unknown/malformed id → 422; manual report supports it;
  MCP forwarding unit-covered.
- **Read path:** group across two arenas; ordering; operator-only (agent
  403); unknown finding 404; identity whitelist excludes secrets.
- **Outcome matrix:** `unknown`, `still_observed`,
  `disappeared_under_controls`, `inconclusive` (mixed validator versions,
  infrastructure failure), `identity_match` variants — using recorded
  verdicts directly; one end-to-end case reuses the loopback
  `http_access_control` harness so the verdict is real.
- **Regression:** pinned `make release-check`.

## Migration path

If finding volume later makes the scan costly, add a `finding_links` table
populated on write and backfilled from the `finding` events; the read endpoint
switches to indexed queries with no interface change. The event payload keeps
`variant_of`/`research_key` as the durable audit truth.
