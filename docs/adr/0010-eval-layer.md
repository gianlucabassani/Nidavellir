# ADR-0010: Eval layer — run records, trace→dataset export, reference harness, replay

- **Status:** Proposed (ROADMAP M3; this increment lands the run/eval-export record
  + OpenInference trace alignment — the reference harness and deterministic replay
  are specified here and follow)
- **Date:** 2026-07-14
- **Deciders:** Gianluca Bassani

## Context

M1 made provisioning any repo reliable; M2 (ADR-0009) made a single run *scorable*
— a structured `Score`, deterministic validators, and a crash oracle. M3 must make
runs **comparable, replayable, and exportable**: turn one scored arena run into an
eval-dataset row that drops into the tools an agent team already lives in
(Langfuse / Phoenix / Braintrust), and ship the flagship proof that makes the thesis
undeniable.

The convergent lesson across METR, UK-AISI, HAL and SWE-bench's standardized-scaffold
track is that a published score conflates *model capability* with what the *scaffold*
allowed. Since Nidavellir agents are bring-your-own over MCP, the scaffold is not an
implementation detail — it is a first-class field of every result. And the convergent
dataset record shape (`input` / `expected_output` / `metadata` / `tags` +
`source_trace_id`) plus OpenTelemetry-GenAI / OpenInference span conventions are what
let a run flow into an eval stack unmodified.

The substrate already exists: the append-only `events` stream (ADR-0004) holds the
whole run (deploy, `agent_session`, `agent_exec`, `finding`, `monitor_signal`), the
M2 scorer (`scoring.py`) folds it into a `Score`, and the gateway writes a per-arena
JSONL trace (`gateway/trace.py`). So the eval layer is an assembly + a projection over
what we already record, not a new subsystem.

## Decision

Build M3 in four parts against the existing events/score/trace substrate. **This
increment lands parts 1–2; parts 3–4 are specified here and follow.**

1. **Run / eval-export record (landed — `eval_export.py`).** A pure
   `build_eval_record(...)` projects one arena run into the convergent dataset shape:
   `input` (the task/target/stance given to the agent), `expected_output` (the hidden
   manifest — ground truth), `metadata`, `tags`, `source_trace_id`, and the embedded
   M2 `score`. `metadata` carries the **full result tuple** — `gen_ai.request.model`
   + `gen_ai.system` (from the `agent_session` event), the harness/scaffold, stance,
   mode, score, progress-rate/tier, steps, wall-clock, tokens/cost when announced,
   `pass@1`, and difficulty — so a row is self-describing and never conflates model
   with scaffold. Exposed operator-only at `GET /arenas/{id}/eval-export` (it reveals
   ground truth). No new table — event-backed and derived on demand.

2. **OpenInference / OTel-GenAI trace alignment (landed — `gateway/trace.py`).** Each
   trace entry additionally carries a `span_kind` (`invoke_agent` for lifecycle,
   `execute_tool` for tool calls) and an `attributes` block using OpenInference /
   `gen_ai.*` keys (`openinference.span.kind`, `tool.name`, `gen_ai.operation.name`),
   so a trace flows into Langfuse / Phoenix / Braintrust without reshaping. Backward
   compatible — new fields are additive.

3. **Reference harness (M3, to build).** A thin, optional Claude/Anthropic-SDK agentic
   loop that connects to the MCP gateway and plays an arena autonomously (recon →
   exploit → `report_finding`), budget-bounded. The model call is injected so the
   loop is testable offline and credential-free; a default Anthropic-SDK brain runs
   when a key is present. Dual-purpose: it powers the flagship demo now, and in
   Horizon 2 it is the neutral baseline the enterprise's own agent is measured
   against. It ships **no AI of our own** — it is thin wiring over the operator's BYO
   model (scope boundary, ADR-standing-principles).

4. **Deterministic replay (M3, to build).** Checkpoint the frozen scenario spec + the
   recorded event/trace stream so a run can be re-run or forked byte-for-byte
   (Inspect's `.eval` transcript is the model). A run that can't be reproduced is a
   bug, not a result.

Difficulty tiers / First-Solve-Time, guided-vs-unguided modes, a held-out set, and
MITRE ATT&CK / ATLAS / OWASP-LLM technique tagging are carried as `metadata`/`tags`
fields on the record from the start (populated incrementally), so the row schema is
stable before the data is complete.

## Alternatives considered

- **A first-class `runs` SQL table.** Cleaner joins for M5's cross-version comparison,
  but a migration + write path for data already fully present in `events`. Rejected
  for now: derive the record on demand (like `/score`); promote to a materialized
  table in M5 if query cost demands it.
- **A bespoke trace format.** Rejected — the whole point is zero-reshape import into
  existing eval tooling, so we align to OpenInference/OTel-GenAI, not invent.
- **Ship an in-house agent.** Violates the load-bearing scope boundary (Nidavellir is
  the neutral harness; the AI is always bring-your-own). The reference harness stays a
  thin, optional wiring sample.

## Consequences

- Positive: every scored run is now an exportable, self-describing eval row with the
  model+scaffold+cost tuple intact; traces import into Langfuse/Phoenix unmodified.
  No migration, no new subsystem.
- Positive: the record schema is fixed early, so M4/M5 (technique tags, cross-version
  regression) add data into stable fields rather than reshaping.
- Negative / cost: token/cost are only as good as what the agent announces; a
  BYO agent that never calls `announce_agent` yields a row with null model/cost (the
  export flags it rather than guessing). Deterministic replay depends on pinning the
  exact spec + transcript; non-determinism in the target image is out of our control
  and is recorded, not hidden.
- Follow-ups: parts 3–4 (reference harness, replay) complete this ADR; the flagship
  demo (M3 acceptance) rides on the harness; M5 consumes these rows for agent-version
  regression.
