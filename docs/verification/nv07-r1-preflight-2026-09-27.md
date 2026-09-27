# NV07-R1 model smoke preflight — 2026-09-27

No model endpoint was called in this preflight. The durable evaluation path now
supports a bounded `model-mcp/v1` build and a single-trial calibration smoke via
`POST /evaluation-smokes`; provider decisions were tested with mocked responses.
This does not close NV07-R1 or prove a model can use the live gateway.

## Connection observed locally

Read-only inspection of the running main Compose database found one stored model
connection: owner `bootstrap`, provider `gemini`, model `gemini-2.5-flash`, status
`standby`. The query did not retrieve or print the credential. The main stack's
SQLite database has no `alembic_version` or `evaluations` table, and its
`model_connections` table lacks the current `base_url` column. It is an older
deployment, not a migrated durable evaluation installation; its connection
cannot be treated as ready for the new driver. No saved Haiku connection
was found. Codex Luna availability in this coding session does not constitute
a Nidavellir model API connection, and a Codex subscription does not establish
Gemini API billing or quota.

## Proposed single smoke, after setup and specific permission

- One `nv06-authorization` **calibration** challenge, one `model-mcp/v1` build,
  one trial with seed 1. The build pins `gemini-2.5-flash` on the operator's
  Gemini API connection, with `reasoning_effort: none` through Google's OpenAI
  compatibility endpoint. No held-out claim follows from this fixture.
- At most eight model turns and eight MCP actions, at most 512 output tokens
  requested per model turn, and a 600-second trial deadline. No automatic
  retry, second seed, parallel test, or full suite. The four exposed tools are
  `get_briefing`, `browser_visit`, `http_request`, and `report_finding`; the
  worker injects the arena ID. The independent validator, healthy control,
  operator-only truth, neutral finding acknowledgement and durable action/time
  budget are the same as the scripted path.
- Expected consumption is roughly 10,000–20,000 input tokens and at most
  4,096 requested output tokens (8 × 512). At Google's published paid standard
  rate for Gemini 2.5 Flash of $0.30/M input and $2.50/M output, that is roughly
  $0.013–$0.016. The stored connection's actual free/paid tier and quota are
  unknown. Google lists a free tier too; we cannot assume it applies to this
  credential. [Google Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
  and [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai).
- The enforceable local limits are model call count, requested output per call,
  wall-clock deadline and gateway action count. Input token count is estimated
  from bounded prompt text, not reserved before a provider call. Provider
  tokenization, billing, external quota, network latency and actual dollar cost
  cannot be guaranteed by Nidavellir. Trial records retain provider-reported
  input/output tokens, any provider-reported cost, MCP trace, termination and
  validator verdict. Missing cost stays unknown.

Before this test, the running stack needs its schema and worker/API code aligned
with the pinned release line through a reviewed data-preserving deployment path,
and the operator must confirm the API connection's
billing mode and that the credential is usable. Checking the credential against
the model endpoint itself is a live API invocation and requires separate
permission. Starting `POST /evaluation-smokes` also requires a new, specific
permission for that single trial. A failed smoke does not authorize a repeat.
