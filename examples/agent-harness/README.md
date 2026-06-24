# Reference agent harness — bring your own model, over the MCP gateway

A **thin wiring sample**: a bring-your-own agent that connects to the Nidavellir
[MCP agent gateway](../../cyber-range/services/agent-gateway/) over streamable
HTTP and drives a contained engagement end-to-end. Every action goes through the
gateway's scoped, audited tools — there is no other path into the arena.

> **This is not "Nidavellir's AI."** Nidavellir ships the gateway and the arena;
> the model, the key, and the prompt are yours. Reference connectors like this
> one are samples to copy from, not a product — see the scope boundary in
> [`.agent/proposals/VISION.md`](../../.agent/proposals/VISION.md).

## Bring your own model

One `--provider` flag picks the backend. Two backends cover the field:

| `--provider` | Backend | Key env | Default model |
|--------------|---------|---------|---------------|
| `anthropic` *(default)* | native Anthropic SDK (adaptive thinking) | `ANTHROPIC_API_KEY` | `claude-opus-4-8` |
| `openai` | OpenAI Chat Completions | `OPENAI_API_KEY` | `gpt-4o` |
| `deepseek` | OpenAI-compatible | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `gemini` | OpenAI-compatible (Gemini's OpenAI endpoint) | `GEMINI_API_KEY` | `gemini-2.0-flash` |
| `ollama` | OpenAI-compatible (local, `:11434/v1`) | — (none) | `llama3.1` |
| `local` | OpenAI-compatible, any `--base-url` | `LLM_API_KEY` (opt) | — (`--model` required) |

The single **OpenAI-compatible** backend speaks to anything that implements the
OpenAI tool-calling API — DeepSeek, Gemini's OpenAI endpoint, local servers
(Ollama / vLLM / LM Studio), or OpenAI itself. Override any preset with
`--model`, `--base-url`, `--api-key`. (The chosen model must support tool/function
calling.)

## What it does

1. Opens an MCP session to the gateway (streamable HTTP, default
   `http://localhost:9000/mcp`).
2. Lists the tools the bound **stance** exposes (attacker, by default) and hands
   them to your model.
3. Runs a **manual tool-use loop** until the agent finishes or hits the step cap.
   The goal is to **discover the arena's known vulnerabilities** and report each
   with `report_finding` (matched against the hidden manifest by CWE + node;
   neutral ack — no oracle).
4. **Announces the connected model** to the platform (gateway `announce_agent`),
   so the operator console shows which AI is driving the arena (see below).

By default the agent runs the whole lifecycle through the gateway:
`deploy_arena` → poll `arena_status` → `get_briefing`/`get_topology` →
`run_command` (recon + exploit from the foothold) → `report_finding` →
`destroy_arena`.

## Prerequisites

- The Nidavellir stack with the gateway profile (attacker stance, streamable
  HTTP on `:9000`):
  ```bash
  docker compose --profile agent-gateway up -d --build
  ```
- Python 3.10+ and an API key (or a local model) for the provider you pick.

## Run

```bash
cd examples/agent-harness
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt        # mcp + anthropic + openai

# Claude (default)
export ANTHROPIC_API_KEY=sk-ant-...
python agent.py

# DeepSeek
export DEEPSEEK_API_KEY=sk-...
python agent.py --provider deepseek

# Gemini
export GEMINI_API_KEY=...
python agent.py --provider gemini --model gemini-2.0-flash

# Local model via Ollama (no key)
python agent.py --provider ollama --model qwen2.5

# Any OpenAI-compatible server
python agent.py --provider local --base-url http://host:8000/v1 --model my-model

# Attach to a running arena instead of deploying
python agent.py --arena-id <id> --keep
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--provider` | `anthropic` | backend/preset (see table above) |
| `--model` | preset's model | model id |
| `--base-url` | preset's URL | OpenAI-compatible endpoint (required for `local`) |
| `--api-key` | from key env | BYO key (overrides the env var) |
| `--gateway-url` | `http://localhost:9000/mcp` | MCP gateway endpoint |
| `--scenario` | `container_web_pentest` | scenario to deploy (no `--arena-id`) |
| `--arena-id` | — | attach to a running arena (implies `--keep`) |
| `--provider-arena` | gateway default | provider for `deploy_arena` (the *arena* backend) |
| `--keep` | off | don't destroy the arena at the end |
| `--max-steps` | `40` | max tool-use rounds |

The only secret the harness needs is your model key. The gateway holds its own
Nidavellir credential (`NIDAVELLIR_AGENT_KEY`) and forwards it to the
orchestrator, which stays the authorization + audit authority.

## Connected-model indicator in the console

When the harness connects, it calls the gateway's `announce_agent` tool with the
model + provider it's driving. The operator console (WebUI) shows this as a
**chip in the topbar** — a provider logo bubble + model name — that you can click
for details (provider, model, stance, arena, when it connected). After a run,
inspect everything as the operator: the topbar chip, the **Audit** page (every
`agent_exec`), and the arena's **Challenges** panel (reported vulnerabilities).

## Notes & variations

- **Manual loop vs. tool runner.** We use a manual loop so each tool call is
  visible and the run reads like a transcript. The Anthropic SDK
  (`anthropic.lib.tools.mcp` + `client.beta.messages.tool_runner`) and OpenAI's
  own loops can drive MCP too if you'd rather the SDK own the loop.
- **`announce_agent` is harness plumbing**, not an agent action — it's hidden
  from the model and called by the harness itself once it knows the arena id.
- **Not hardened.** A real harness would stream long turns, enforce token/step
  budgets, and add retries — out of scope for a wiring sample. The gateway
  enforces scope, containment, and per-key step budgets server-side.
