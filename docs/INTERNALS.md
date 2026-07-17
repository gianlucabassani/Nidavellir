# Internals

How every subsystem works, end to end. Companion to [`OVERVIEW.md`](./OVERVIEW.md)
(the high-level tour) and the ADRs in [`adr/`](./adr) (the decisions). Paths are
relative to the repo root; the orchestrator service lives at
`cyber-range/services/scenario-orchestrator/`.

---

## 1. Topology of the system

```
Console (Flask)            Orchestrator (FastAPI)            Worker (Celery)
cyber-range/webui   ──HTTP──▶  api.py  ──enqueue via Redis──▶  tasks.py
     ▲                          │  │                              │
     │ 5s poll                  │  │ Database (SQLAlchemy)        │ Orchestrator
     │                          │  └──▶ events / deployments      │   → provider
 BYO agent ──MCP──▶ agent-gateway ──REST──▶ api.py               ▼
 (reference-harness  gateway/server.py                     providers/{mock,
  or any MCP client)  stance-gated tools                    docker_local,aws,...}
```

- **Control plane** = FastAPI (`api.py`) + Redis/Celery (`tasks.py`) + a provider
  abstraction (`providers/`). Decoupled: the API enqueues, the worker executes.
- **Data plane** = the provider driver (docker-local for real container arenas).
- **Agent seam** = the MCP gateway (`agent-gateway/gateway/`), a *separate* service
  that proxies the orchestrator's REST API forwarding the agent's key.
- **State** = PostgreSQL/SQLite via SQLAlchemy, with an append-only `events` audit
  table as the spine that scoring, bindings, setup-phase, and the defender feed all
  read from.

---

## 2. Persistence & the event spine (`database.py`, `models.py`, `states.py`)

- **Models:** `Deployment` (arena record: id, scenario, status, outputs, provider,
  expires_at), `ApiKey` (SHA-256 hash only — plaintext keys never stored),
  `ModelConnection` (operator's BYO model key, Fernet-encrypted), and `Event` (the
  append-only audit stream). `Event.lab_id` is deliberately **not** a foreign key so
  the audit trail survives arena deletion.
- **The events stream is load-bearing.** Every create/transition/deletion appends an
  event with the acting principal. Higher-level state is *derived* from events
  rather than stored in new tables: agent bindings, the SUT setup phase, findings,
  monitor signals, and the eval score are all event projections. This is why M2/M3
  needed **no migrations**.
- **Lifecycle state machine (`states.py`).** Status writes validate against a
  transition graph (`IllegalTransition` on violation): `pending → deploying →
  active → destroying → destroyed`, with `error`/`failed`/`error_destroying` edges.
- **Reaper (`tasks.reap_labs`, Celery beat).** Drives toward destruction any lab
  that is **expired** (TTL `expires_at` elapsed) or **stuck** (sitting in a transient
  state with no live worker). Idempotent; one bad lab never aborts the sweep. Also
  closes any lapsed setup-egress (safety net).
- **Secrets at rest.** Arena `outputs` and model keys are Fernet-encrypted when
  `SECRETS_ENCRYPTION_KEY` is set (`crypto.py`); plaintext passthrough otherwise.
  Log redaction (`redaction.py`) keeps keys out of logs.

---

## 3. Auth, roles & bindings (`auth.py`, `bindings.py`, ADR-0002/0005)

- **API-key auth**, three roles: `admin`, `operator`, `agent`. Only SHA-256 digests
  are stored; a bootstrap admin key is minted on first run.
- **Bindings (D1 guardrail).** A `binding` authorizes **one agent principal to act
  on one arena**, in a stance. State is event-backed: `agent_binding` grants,
  `agent_binding_revoked` revokes, `agent_binding_paused`/`_resumed` toggle a
  reversible kill-switch. `_require_binding` gates `/exec`, `/findings`, and the
  configurator endpoints — an unbound or wrong-stance agent can't touch an arena.
  Operators bypass (they *are* the control plane).
- **Two-audience split.** Agents use API keys over MCP; the human console's SSO is a
  deferred Horizon-2 item (ADR-0002 stands for the agent path).

---

## 4. The MCP agent gateway (`agent-gateway/gateway/`, ADR-0005)

The seam where a bring-your-own agent connects. Built on the official MCP SDK
(`FastMCP`), stdio or streamable-HTTP transport.

- **`server.py`** registers tools per the bound **stance** and delegates to
  `tools.py` (the testable logic). It never imports the orchestrator — it calls the
  REST API via `rest_client.py`, forwarding the agent key so the orchestrator stays
  the authn/authz + audit authority.
- **Stances (`stances.py`)** — the single source of truth for what a session may
  call:
  - **attacker** — `get_topology`, `list_targets`, `run_command`, `report_finding`.
  - **defender** — `get_topology`, `query_events` (reads the audit/detection feed).
  - **mitm** — `get_topology`, `observe_traffic` (in-path capture; modify deferred).
  - **configurator** — victim setup tools during the SUT setup phase (no attacker
    tools — a hard privilege boundary).
  - **operator** — authoring (`scaffold_scenario`, `import_scenario`); never an
    in-arena agent.
  Plus shared lifecycle tools (`deploy_arena`, `arena_status`, `announce_agent`, …).
- **Guardrails:** a per-session step budget, per-command timeout, foothold-scope for
  the attacker (`run_command` only on the foothold node), and a JSONL trace.
- **Trace (`trace.py`)** — every tool call is recorded to `traces/<arena>.jsonl`
  with the non-reversible `agent_id` (never the raw key), and now carries
  **OpenInference / OTel-GenAI** fields (`span_kind`, `gen_ai.*`, `tool.name`) so a
  run imports into Langfuse/Phoenix unmodified (ADR-0010).

---

## 5. Providers & containment (`providers/`, ADR-0003)

A provider compiles a validated scenario into real infrastructure. `docker-local` is
the mature path; `mock` is the no-infra test path; `openstack`/`aws`/`libvirt` are
Terraform skeletons (deferred — no live apply).

**`docker_local.py` (the workhorse):**

- **Compilation.** One bridge network **per segment**, one container **per node**,
  keyed by unique node name; multi-segment straddle supported. Node `image` resolves
  through the per-provider **image map** (`images.py`; logical `dvwa`/`kali` → real
  tags; unknown names pass through, so concrete tags work too).
- **Containment (default-on).** Locked arenas use `internal` (no-egress) segment
  networks + a **no-masquerade ingress bridge** so an operator's browser can reach a
  published web port without the node getting egress. A default-on **allowlisted
  apt/pip mirror** (squid sidecar) lets the foothold install tooling under
  containment. `requires.egress: open` opts out. A CI containment test proves a
  locked node can't reach an external canary.
- **Liveness guardrail.** A headless container whose foreground process exits gets
  reaped by Docker; `_keepalive_run_args` re-runs the image's own entrypoint then
  blocks, so "VM-in-a-container" images don't die on boot. An explicit `command`
  wins.
- **Exec.** `exec_in_node` runs `timeout <t> sh -c <cmd>` in the container (real
  `docker exec`), returning exit code + stdout/stderr — the backend for the attacker
  stance's `run_command` and for the validator's active probe.
- **SUT machinery.** `_build_service_image` (build from a remote git context, gated
  by `NIDAVELLIR_ALLOW_SOURCE_BUILD`), `_build_package_image` (apt-install a
  `service.package`), `verify_build_dockerfile` (the synthesis loop's build),
  `_prepare_whitebox_sources` (read-only source mount into footholds),
  `set_node_egress` (open/close setup-time NAT), and `collect_monitor_signals` (the
  M2 collector — see §8).
- **Outputs.** `_collect_outputs` emits flat `node_<name>_*` keys: container name,
  private IP, published/floating host port, a web "Open" URL, SSH/exec command,
  white-box source path, and state — the addressing every other subsystem reads.

---

## 6. Scenarios & authoring (`scenario_spec.py`, `scenarios.py`, `catalog.py`, `generator.py`, `vulhub_import.py`)

- **Schema v3 (`scenario_spec.py`).** A validated `ScenarioSpec`: `nodes[]` (name,
  role, image, ports, segments, entrypoint, command, optional `service` block for
  SUT), network `segments[]`, `agents[]` stance bindings, `objectives[]`, and a
  **`vulnerabilities[]` manifest** (the hidden ground truth: id, cwe, node, points).
  Pydantic with hard cross-field checks; `normalized_nodes()` gives providers one
  shape. Published as `docs/scenario.schema.json`.
- **Registry (`scenarios.py`).** Loads/validates packs from `templates/*.yaml`;
  `scenario_manifest(id)` returns the ground-truth manifest (operator-only reveal).
- **Generation (`generator.py`, BYO key).** Prompt → v3 spec via the operator's own
  model (`model_chat.complete_chat`, JSON mode), validated round-trip, **never
  auto-deployed** (review gate). Exposed as the operator-stance `scaffold_scenario`.
- **Vulhub import (`vulhub_import.py`).** Deterministic compose → v3 conversion for
  container CVE environments, SSRF-guarded fetch.

---

## 7. The SUT pipeline — repo → running service (M1, ADR-0007/0008)

Four pure/injectable modules plus provider execution turn an arbitrary repo into a
running, testable arena:

1. **`repo_introspect.py`** — shallow SSRF-guarded clone, then a pure `analyze()`
   detects language, build system, base runtime, declared ports (+ source),
   run-hints, README excerpt. Grounds everything so the model stops guessing.
2. **`build_planner.py`** — maps introspection to a `BuildPlan` with a deterministic
   tier: **dockerfile** (executable now) > compose > devcontainer > buildpack
   (classified, not yet executed) > **none** (→ synthesis).
3. **`dockerfile_synth.py`** — the Repo2Run pattern: the operator's model drafts a
   Dockerfile, the platform **actually builds it**, feeds errors back to fix, and
   only returns one that built green. Pure prompt-building + extraction; `complete_fn`
   / `build_fn` injected.
4. **`setup_proposer.py` + `setup_phase.py`** — the configurator: an operator-gated,
   time-boxed, victim-scoped, budgeted phase to bring a service up, in three modes —
   `operator` (scripted), `hitl` (agent proposes, operator approves), `autonomous`
   (double-locked behind a flag + per-arena consent). Egress is opened only during
   setup and revoked four ways (finish/expiry/reaper/destroy). Event-backed.

---

## 8. Monitor / crash oracle (M2 part 1, `monitor.py`, ADR-0009)

- **Pure detector.** `monitor.detect_signals(observations)` turns per-node runtime
  observations (container state + a bounded log tail) into structured signals:
  `crash`, `sanitizer_abort`, `unhandled_5xx`, `resource_exhaustion`, each with
  `{kind, node, severity, summary, evidence, key}`. Deterministic **state** signals
  (non-zero exit, OOM-kill, crash-loop) are authoritative; **log** heuristics
  (panic/ASan/traceback/5xx patterns) are conservative best-effort.
- **Dedup.** `key` is a stable fingerprint so a persistent fault is recorded once,
  not every tick.
- **Collector + sweep.** The provider's `collect_monitor_signals` reads State +
  RestartCount + log tail for SUT nodes (skips foothold + mirror). The Celery-beat
  `monitor_arenas` task polls every ACTIVE arena, runs the detector, and appends each
  **new** signal to `events` as `monitor_signal` (`actor: "monitor"`) — feeding the
  defender stance and the scorer.

---

## 9. Deterministic validators (M2 part 2, `validators.py`, ADR-0009)

"Perfect verification": a finding is *confirmed* only when programmatically proven,
never on the agent's word.

- **Active validators** (run at report time, injected effect fns):
  - `reflected_xss` — a unique nonce reflected **unescaped** in an executable HTML
    context (pluggable headless-browser confirmer for M4).
  - `marker` — a planted secret disclosed by injection (e.g. SQLi).
  - `oast_callback` — an out-of-band callback observed.
- **Passive** `correlate_crash` — ties a finding to a crash-oracle signal on its
  node (the no-manifest credit path).
- **SSRF-safe probe.** The API binds the active `http_fn` to the arena's **own
  victim** (path+params only, host fixed), backed by a foothold `curl` over the arena
  network. It raises on unreachable so the verdict is *unknown*, never a false
  *refuted*.
- **Tri-state `confirmed`:** `true` (verified) / `false` (refuted — probe ran, effect
  absent) / `null` (unknown — no applicable validator or the probe couldn't run).
  Only `true` earns confirmed credit. The verdict is redacted from the agent's event
  feed (neutral ack).

---

## 10. Structured scoring (M2 part 3, `scoring.py`, ADR-0009)

- **`Score`** — Inspect-style: typed `value` (binary/numeric/categorical) + `answer`
  + `explanation` + `evidence` + `metadata`. Never free text.
- **Two modes, auto-selected by manifest presence** (operator-overridable via
  `?mode=`):
  - **benchmark** — CVE-rediscovery vs the manifest: `found` (matched by CWE+node),
    `confirmed` (validator-verified subset), points + confirmed-points.
  - **discovery** — no manifest: distinct crash-oracle **fault sites** +
    `confirmed_findings` drive the score.
- **Partial credit.** An ordered milestone ladder (foothold → recon → first blood →
  verified exploit → full clear) yields a **Progress Rate** that scores even a failed
  run — distinguishing a weak agent from a strong one.
- **Metrics.** Steps and wall-clock derived from events; token/cost when announced
  (or, for the Claude Code path, folded in from its reported usage).
- Endpoints: `POST /arenas/{id}/findings` (report + validate), `GET /arenas/{id}/score`
  (structured scorecard), `GET /scenarios/{id}/vulnerabilities` (operator manifest
  reveal).

---

## 11. Eval layer (M3, `eval_export.py`, ADR-0010)

- **`build_eval_record(...)`** projects a run into the convergent dataset shape:
  `input` (task/target/stance), `expected_output` (the hidden manifest — ground
  truth), `metadata`, `tags`, `source_trace_id`, and the embedded `Score`.
- **The full result tuple** rides in `metadata` (`gen_ai.request.model`,
  `gen_ai.system`, harness/scaffold, stance, mode, score, progress-rate, steps,
  wall-clock, tokens, cost, `pass@1`, difficulty) so a number never stands alone —
  scaffold is a first-class field (the METR/AISI/SWE-bench lesson). Unannounced
  agents are flagged `attributed: false`, not guessed.
- Served operator-only at `GET /arenas/{id}/eval-export`. Event-backed, derived on
  demand — no `runs` table yet (deferred to M5 if query cost demands it).

---

## 12. The reference harness (M3, `reference-harness/harness/`, ADR-0010)

An **optional** BYO agent that plays arenas and produces scored rows. Nidavellir
ships no AI — this is thin wiring over the operator's model.

- **`loop.py`** — an injectable async engagement loop over a `ToolsInterface` + a
  `Brain` + a `Budget` (steps / findings / wall-clock, fail-safe). Returns a
  `RunResult` transcript.
- **`brains.py`** — `ScriptedBrain` (deterministic, keyless smoke agent) and
  `AnthropicBrain` (BYO Claude via the Messages API — needs an API key — bridging
  SDK tool-use ↔ MCP).
- **`mcp_tools.py`** — a `ToolsInterface` over the real gateway stdio transport;
  arena-scoped (auto-injects `arena_id`).
- **`claude_code.py`** — the **subscription path**: builds the `--mcp-config`
  pointing Claude Code at the gateway and the headless `claude -p` command
  (`--allowedTools mcp__nidavellir-arena__*`, `--strict-mcp-config`,
  `--output-format json`). Auth is inherited from the operator's Claude Code login;
  no key is set. (A subscription may only legally drive Claude Code — not the SDK or
  Messages API — per Anthropic's Consumer ToS.)
- **`runner.py`** — `run_single` / `run_suite` (concurrency-capped fan-out → dataset
  JSONL + aggregate summary) and `run_single_claude_code`; a control plane and tools
  factory are injected (`rest_control.py` is the production REST control plane).
- **`replay.py`** — deterministic replay: re-run a recorded transcript against a
  fresh identical arena and check the score reproduces.

---

## 13. Companion model layer (`model_chat.py`, `model_verify.py`)

Distinct from the BYO-agent path: features where **Nidavellir itself** calls a model
on the operator's key — the co-pilot, `/scenarios/generate`, Dockerfile synthesis.

- Providers: `anthropic` natively, plus an OpenAI-compatible map (`openai`,
  `deepseek`, `gemini`'s OpenAI endpoint, `ollama`, a `local` placeholder). JSON
  mode is normalized across providers.
- The operator's key is stored Fernet-encrypted (`ModelConnection`); a verify-ping
  lists the provider's models without inference.
- **Scope note:** this is the *only* place provider breadth matters — a BYO agent
  brings its own provider over MCP, so OpenRouter/HF there never touch Nidavellir.
  Broadening this layer (OpenRouter/HF/generic `base_url`) is BACKLOG **P3-4**.

---

## 14. Cross-cutting safety

- **Containment first** (§5): no-egress by default, allowlisted mirror, CI canary
  test.
- **SSRF guards:** `netguard.py` for repo clones; the validator `http_fn` is bound to
  the arena's own victim (no arbitrary host).
- **Never-auto-deploy** generated/synthesized infra (review gate).
- **Consent-gated, HITL, time-boxed configurator** with a hard privilege boundary.
- **Neutral findings ack** — ground-truth match *and* validation verdict are
  redacted from the agent so it can't enumerate the manifest.
- **`MOCK_MODE`** makes the whole flow demoable/testable with no infra; `make check`
  = ruff + bandit + pytest, green in CI on SQLite + Postgres.

---

## 15. Request lifecycle (worked example: a benchmark run)

1. Operator `POST /deploy {scenario, instance_id}` → `deploy_lab` (Celery) →
   `docker_local.deploy` builds the arena → status `active`, outputs recorded.
2. Operator `POST /arenas/{id}/bindings {agent_name, stance:"attacker"}`.
3. Agent (over MCP) `get_topology` / `list_targets` → `run_command` (foothold exec) →
   `report_finding {cwe, node, [path,param,payload]}`.
4. `report_finding`: match vs hidden manifest (CWE+node) → run the applicable
   validator (active probe or, at score time, crash correlation) → record a `finding`
   event with `matched_vuln_id` + `validation` (operator-only).
5. `monitor_arenas` (beat) records any `monitor_signal` from the target's faults.
6. Operator `GET /arenas/{id}/score` → `scoring.score_arena` folds findings + signals
   + metrics into the `Score`; `GET /arenas/{id}/eval-export` emits the dataset row.
7. Reaper or explicit `DELETE /destroy/{id}` tears the arena down; the event trail
   persists.
