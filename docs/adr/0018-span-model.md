# ADR-0018: Span model for agent and operator actions

- **Status:** Accepted
- **Date:** 2026-11-24
- **Deciders:** project maintainer (OBS-01, review item FR-10)

## Context

The operator cannot answer "what did the agent do, how long did it take and what
came back" from durable data. The audit `events` table records that something
happened, with a small payload and no duration, status or parent. The gateway's
JSONL trace (ADR-0005, ADR-0010) has timings and OpenInference/GenAI attributes but
lives in a gateway-local file that the orchestrator and console never read. Model
calls in the NV-07 driver are not recorded per call at all.

OBS-02 (single action boundary), OBS-03 (gateway and model calls in one trace),
OBS-04 (push stream) and OBS-05 (live view) all need one durable record per action.

## Decision

We will add a `spans` table, written only by the orchestrator, with one row per
action:

| column | meaning |
|---|---|
| `id` | autoincrement; the stream cursor (OBS-04 `Last-Event-ID`) |
| `span_id`, `trace_id`, `parent_span_id` | W3C trace-context sizes (16 / 32 hex) |
| `arena_id`, `evaluation_id`, `trial_id` | nullable links |
| `actor`, `actor_kind`, `stance` | key name; `human` / `agent` / `system` |
| `kind`, `name` | `tool` / `model` / `lifecycle` / `validation` / `agent`; operation name |
| `started_at`, `ended_at`, `duration_ms` | naive UTC (FR-08) |
| `status`, `error_class` | `ok` / `error` / `denied` / `budget_refused` |
| `input_digest`, `output_digest` | SHA-256 of the canonical JSON of the full input/output |
| `input_preview`, `output_preview` | at most 2 KiB each, redacted |
| `attrs` | JSON; OpenInference / OTel GenAI names as in the gateway trace, token counts and cost when reported, links to stored records (e.g. `http.transaction_digest`) |
| `visibility` | `agent` or `operator` |

Rules:

- **One trace per run.** An arena's trace ID is derived from its ID and a trial's
  from the trial ID, so every writer (API, worker, gateway context in OBS-03) lands
  in the same trace without coordination. A caller may pass an explicit trace and
  parent.
- **Payloads stay where they are.** Full request/response bodies already live in
  content-addressed stores (HTTP transactions, evidence artifacts, validation
  evidence). A span holds digests, a bounded preview and attributes that link to
  those records; it never becomes a second payload store.
- **Previews are redacted before storage** with the existing `redaction.redact()`
  plus span-specific masking: sensitive mapping keys (including `Authorization`,
  `Cookie`, `Set-Cookie`, `Proxy-Authorization`), bearer tokens, JWTs and cookie
  header lines. Redaction runs at write time, so no read path can leak the original.
- **Truth rule.** `validation` spans, and any span a caller marks operator-only, are
  stored with `visibility = operator`. An agent key reads only `agent` spans of an
  arena it is bound to (FR-04), the same scope as the event allowlist in
  `event_visibility.py`. The read path filters on the stored column; there is no
  per-request derivation to forget.
- **Writes are best-effort for the caller.** Recording a span never fails the action
  it describes; a write error is logged. OBS-02 makes span creation part of the action
  boundary so coverage does not depend on each route remembering it.

## Alternatives considered

- **Extend `events` with timing columns.** Events are the append-only audit record
  with their own visibility allowlist and consumers (exports, findings, bindings).
  Overloading them with high-volume, nested tool and model spans would change what
  every existing reader receives.
- **Ingest the gateway JSONL.** It covers only gateway calls, not console or REST
  agents, and a file on the gateway host is not a source of truth.
- **Adopt an OTel collector and backend as the store.** Adds a required service to a
  local-first platform. OBS-07 keeps OTLP as an optional export of these rows.

## Consequences

- Positive: one queryable timeline per run for the console, exports and replay
  (OBS-05, OBS-08); a stable cursor for the stream (OBS-04).
- Negative / cost: one insert per action; previews cost up to 4 KiB a row. Retention
  follows the arena record and is not yet pruned.
- Follow-ups: OBS-02 writes spans from `actions.run`; OBS-03 adds trace context from
  the gateway and model spans; OBS-04 publishes span inserts.
