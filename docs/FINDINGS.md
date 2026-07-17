# Bugs & Improvement Vectors

Findings from building and live-verifying M2 (scoring), the MCP loop, and M3 (eval
layer + reference harness). Two categories: **bugs** (defects, with the two found
this cycle already fixed) and **improvement vectors** (open work, ranked by
leverage). Companion to [`OVERVIEW.md`](./OVERVIEW.md) and [`INTERNALS.md`](./INTERNALS.md).

Severity: 🔴 high · 🟠 medium · 🟡 low. Effort: S/M/L.

---

## A. Bugs

### A1 — Unreachable target scored as *refuted* instead of *unknown* · 🟠 · **FIXED**
`validators` / `api._arena_http_fn`. `curl` still prints its `-w` status marker with
code `000` on a connection failure, so an unreachable victim produced an empty body
that the reflected-XSS check read as "reflected? no → **refuted**". A false *refuted*
violates the tri-state contract (`false` means "probe ran, effect absent"). **Fix:**
treat HTTP status `0` as unreachable → raise inside the probe → validator records
`null` (unknown). Caught during the live active-validator run; regression-tested.

### A2 — Discovery-mode findings never confirmed by the crash oracle · 🟠 · **FIXED**
`api.arena_score` / `scoring`. Passive crash correlation was gated on findings that
*matched a manifest vuln*, so in **discovery** mode (no manifest) a reported finding
on a crashed node was never credited — the score showed `0 confirmed` despite a real
crash. **Fix:** correlate **all** findings (not just matched) and add a
`confirmed_findings` count independent of manifest ids; the discovery answer/tier now
reflect it. Regression-tested.

### A3 — MCP `report_finding` doesn't forward the active-validation inputs · 🟠 · **FIXED**
`agent-gateway/gateway/{tools,server,rest_client}.py`. The orchestrator's
`FindingRequest` accepts `path`/`param`/`payload`/`oast_token` (the evidence that
lets an *active* validator confirm a finding), but the gateway's `report_finding`
tool only forwarded `title`/`cwe`/`node`/`evidence` — so an MCP agent's findings
could only be confirmed by **passive crash correlation**, never by the active
XSS/marker/OAST probe. **Fix:** the four optional fields are now threaded through the
tool schema (`server.py`), `tools.report_finding`, and `rest_client.report_finding`;
the ack stays neutral. An MCP agent can now get its web findings actively proven.
Regression-tested (`test_report_finding_forwards_verification_inputs`).

### A4 — `get_topology` "null node names" · 🟡 · **NOT A BUG**
The live `nodes: [null, null]` was a **diagnostic-script key mismatch**, not a
framework defect: the gateway correctly returns each node keyed `"node"` (with the
real name), and my throwaway MCP test client read `n.get("name")`. `get_topology` /
`list_targets` are internally consistent on `"node"`. Locked with a test
(`test_get_topology_returns_named_nodes`) asserting non-null names + the `"node"` key.

### A5 — Active probe assumes `curl` on the foothold · 🟡 · **FIXED**
`api._arena_http_fn` shelled `curl` only. **Fix:** the probe now prefers `curl`
(real HTTP status) and falls back to `wget --content-on-error` (status-unknown → a
`200` sentinel; the reflected-XSS/marker validators check the body, not the code);
no tool or no response still yields *unknown*, never a false *refuted*. Widens the
foothold images active validation works from.

---

## B. Improvement vectors (open)

### B1 — Full-compose-stack verification · 🟢 · **VERIFIED (2026-07-14)**
Ran end-to-end through the live `docker-compose` stack (orchestrator + Celery worker +
beat + redis + webui, `docker-local`, real containers): import scenario → **worker
deploy** → active → **the monitor beat autonomously recorded a `crash` signal** (not a
manual trigger) → operator bind → agent finding → **crash correlation confirmed it** →
discovery score `1.0` → eval-export; plus the live **MCP gateway** path (real
`docker exec`, A3 forwarding). No defects — the three apparent "issues" during
verification were diagnostic-script errors on my side (wrong container-label key
`nidavellir.lab_id`, a bad jq filter, and misreading validation *inputs* as stored
fields). One real finding: **v3 `command` is string-only** (docker-py shlex-splits it),
not a list — the API validator rejects a list.

### UI-1 — Console didn't surface discovery-mode score or findings · 🟠 · **FIXED**
`webui/app.py::_score` returned `None` whenever there was no manifest, so **discovery /
SUT arenas showed no score at all**, and there was no findings list. **Fix:** `_score`
now returns the structured scorecard in both modes; the arena page has a compact,
mode-aware **Assessment** panel (benchmark = hidden known-vuln list matched by a parser;
discovery/SUT = agent-generated findings verified by the crash oracle / validators),
proper empty states, and a **Findings** list with per-finding verification. Live-verified.

### UI-2 — Configurator (agent-proposed steps) had no output console · 🟠 · **FIXED**
The `setup_step` event stored `command`/`exit_code` but **not stdout/stderr** — so an
operator approving an agent-proposed setup step saw no real output. **Fix:** the event
now persists bounded stdout/stderr, and the configurator card renders a **Setup
console** (command + exit + real output, terminal-style). Live-verified end-to-end.

### B2 — Headless-browser XSS execution oracle · 🟠 · M (M4)
The `reflected_xss` validator confirms a nonce reflected **unescaped in an executable
context** — a strong deterministic baseline, but not proof the payload *executed*. The
authoritative oracle is a headless browser, deliberately deferred to **M4** (and
shared with M4's browser tool — build once). Until then, a maximally airtight demo
should lean on a crash/ASan bug or benchmark-manifest rediscovery rather than a
headless XSS claim.

### B3 — Companion model-provider breadth (BACKLOG P3-4) · 🟢 · **DONE**
Fully shipped and live-verified. `openrouter` + `huggingface` + `custom` providers
added everywhere (`OPENAI_COMPAT_BASE`, api `MODEL_PROVIDERS`, webui picker/brands);
a generic `openai_base()` resolver reads `NIDAVELLIR_MODEL_BASE_URL`; and a
**per-connection `base_url`** now threads model → migration (0004) → `database` →
api (`/agent/model` + verify) → `model_chat`/`model_verify` (per-call base_url wins
over preset/env) → the webui modal (a Base-URL field shown for OpenAI-compatible
providers). Live: PUT `openrouter` + `base_url` → stored + masked read-back.
`make check` 684 green; scope stays companion-only (the BYO-agent path is untouched).

### UI-3 — Arena page + configurator UX overhaul · 🟢 · **DONE**
The arena detail page was a messy pile of ad-hoc-styled cards using an invalid
`var(--border)` token (invisible bars/borders). Rebuilt on the real design system
(`.usage-stat`, `.bar`, `.chips`, `.cfg-out`), reordered to an operator flow (arena →
configure → position → results → activity), and the **Configurator moved into a wide
modal overlay** — the page shows a compact overview (mode + steps + status) and the
method chooser (operator / agent-proposal / autonomous) + live setup console open in
the pop-up. Live-verified.

### B4 — Reference-agent auth matrix · 🟡 · S–M
`AnthropicBrain` (Messages API) needs an API key and hasn't been run against the real
API (no key available in dev). The subscription path (Claude Code) is wired and
flag-validated but its `claude -p` reasoning run is user-triggered (spending + nesting
make it inappropriate to auto-run). Optional: an `OpenAICompatBrain` so the harness
can drive OpenRouter/HF/DeepSeek models for API-key runs.

### B5 — Build tiers beyond Dockerfile · 🟡 · M (ADR-0008)
`build_planner` classifies **compose / devcontainer / buildpack** tiers but only the
Dockerfile tier + LLM synthesis are *executed*. Wiring a compose runtime, the
`devcontainer` CLI, or `pack`/Paketo would widen the set of repos that stand up
without synthesis.

### B6 — M3 remaining deliverables · 🟠 · M
Difficulty tiers + First-Solve-Time, guided-vs-unguided modes, a held-out
(non-public) set, and the **SSE live feed** (retire the 5s console polling) — plus the
headline: the **recorded flagship demo**. The engine is ready; these are polish +
presentation.

### B7 — First-class `runs` record for regression (M5) · 🟡 · M
Eval rows are derived on demand from events. M5's agent-version comparison (vN vs
vN+1) will want a materialized `runs` table + a batch replay/diff. The row schema is
already stable (ADR-0010), so this is additive.

### B8 — VM / cloud providers are skeletons · 🟡 · L (deferred)
`openstack`/`aws`/`libvirt` pass `tofu validate` but have **no live apply**;
docker-local is the whole substrate today. Real VM arenas (libvirt/QEMU increment 2 —
live boot + `exec_in_node` + egress) unblock VM-class scenarios. Deliberately deferred
until the H1 spine is compelling.

### B9 — Doc/tree drift guardrail · 🟡 · S
Several times this cycle the ROADMAP/ADR status lagged the code (e.g. M2 "not yet
built" while `monitor.py` existed; ADR-0007/0008 stuck "Proposed" after shipping). A
lightweight check (or discipline) to reconcile ADR/ROADMAP status against the tree at
each milestone would prevent stale planning docs.

---

## C. What's solid (so the list above is in proportion)

- The **moat is real and proven**: crash oracle → deterministic validators →
  structured score, live-verified against real Docker arenas (a real crash detected,
  a real reflected-XSS confirmed over a socket, a real MCP finding scored).
- **Containment** is default-on and CI-tested (no-egress + canary).
- **No AI shipped** — the scope boundary holds across generation, validation, and the
  harness; the reference agent is thin, optional wiring.
- **671 tests, `make check` green**; event-backed design meant M2/M3 needed no
  migrations.

---

## D. Suggested order

1. **A3** (forward validation inputs through MCP `report_finding`) — small, unlocks
   active proof for real agents.
2. **B6 flagship demo** — the M3 acceptance artifact.
3. **B3 / P3-4** (companion providers) — small, self-contained, unblocks non-Anthropic
   companion use.
4. **B1** (one real compose-stack run) — retires the verification caveat.
5. **A4/A5** (recon polish) alongside the above.
6. Then **M4** (headless browser + code-exec sandbox + fail-closed budgets) — B2 rides
   with it, and it's the Horizon-2 graduation gate.
