# Reference harness (ROADMAP M3 · ADR-0010)

A thin, **optional** bring-your-own-agent that plays a Nidavellir arena and turns
the run into a scored eval-dataset row. Nidavellir ships **no AI of its own** — the
model is always yours. This harness is wiring, not a product; it also serves as the
neutral baseline an agent-under-test is compared against.

A run = **deploy → bind → engage → `eval-export` → destroy**, producing the
`GET /arenas/{id}/eval-export` row (the M2 `Score` + the model+scaffold+cost tuple).

## Two ways to bring the model

| Path | Auth | Use it when |
|------|------|-------------|
| **Claude Code (subscription)** | your Claude Pro/Max login — **no API key** | you have a subscription; the demo |
| **Anthropic / OpenAI-compatible SDK** | a pay-per-use API key | CI, batch suites, non-Anthropic models |

> **Why the split (Anthropic ToS, Feb 2026).** A Claude **subscription** may only
> drive **Claude Code / claude.ai** — using a subscription OAuth token with the
> Agent SDK or the raw Messages API violates the Consumer ToS. So on a subscription
> the BYO agent *is* Claude Code, connecting to the gateway over MCP. The
> `AnthropicBrain` (Messages API) and the operator companion features need a real
> API key (Anthropic, or any OpenAI-compatible provider — see BACKLOG P3-4).

## Prerequisites

- The stack running (orchestrator API reachable, e.g. `http://127.0.0.1:8099`).
- An **operator** key (deploy/bind/score) and an **agent** key (drives the arena).
- A scenario id (e.g. `container_web_pentest`).

## Subscription path — Claude Code as the agent

```bash
# 1) One-time: make sure Claude Code is logged in on your subscription
#    (interactive `claude` login, or a token for a non-interactive shell):
claude setup-token          # optional; only if the shell isn't already logged in

# 2) Run the arena with Claude Code as the BYO agent (no API key):
python -m harness \
  --api-url http://127.0.0.1:8099 \
  --operator-key "$OPERATOR_KEY" \
  --agent-key "$AGENT_KEY" \
  --scenario container_web_pentest \
  --claude-code --model opus \
  --out dataset.jsonl
```

The harness deploys the arena, binds the agent, writes a `--mcp-config` pointing
Claude Code at the gateway, runs `claude -p` (auto-approving the arena's
`mcp__nidavellir-arena__*` tools, JSON output), then prints the aggregate summary
and writes one eval row per scenario. Claude Code's reported `total_cost_usd` /
token usage are folded into each row's metadata.

Under the hood the equivalent raw command is:

```bash
claude -p "Assess the arena (arena_id=<id>) and report vulnerabilities…" \
  --mcp-config ./nvmcp.json \
  --allowedTools "mcp__nidavellir-arena__*" \
  --output-format json
```

…where `nvmcp.json` is:

```json
{
  "mcpServers": {
    "nidavellir-arena": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "gateway.server"],
      "env": {
        "PYTHONPATH": "/abs/path/to/cyber-range/services/agent-gateway",
        "NIDAVELLIR_AGENT_KEY": "cg_…",
        "NIDAVELLIR_STANCE": "attacker",
        "NIDAVELLIR_API_URL": "http://127.0.0.1:8099",
        "NIDAVELLIR_GATEWAY_TRANSPORT": "stdio"
      }
    }
  }
}
```

## API-key path — Anthropic SDK agent

```bash
export ANTHROPIC_API_KEY=sk-ant-…
python -m harness --api-url http://127.0.0.1:8099 \
  --operator-key "$OPERATOR_KEY" --agent-key "$AGENT_KEY" \
  --scenario container_web_pentest --scenario juice_shop \
  --model claude-fable-5 --concurrency 4 --out dataset.jsonl
```

With no `--model` and no `--claude-code`, the harness runs a **scripted smoke
agent** (recon → probe → one report) — a keyless end-to-end check of the whole
arena → gateway → score path.

## Library API

```python
from harness import run_single, run_suite, run_single_claude_code, replay_run
from harness import ScriptedBrain, AnthropicBrain, Budget
```

- `run_engagement` — the injectable loop (ToolsInterface + Brain + Budget).
- `run_single` / `run_suite` — one arena / a concurrency-capped batch → dataset + summary.
- `run_single_claude_code` — the subscription path (Claude Code as agent).
- `replay_run` — re-run a recorded transcript and check the score reproduces.

## Modules

`loop.py` engagement loop · `brains.py` Scripted/Anthropic brains · `mcp_tools.py`
gateway MCP binding · `claude_code.py` Claude Code launcher · `runner.py`
single/suite + Claude Code runner · `rest_control.py` REST control plane ·
`replay.py` deterministic replay · `__main__.py` CLI.
