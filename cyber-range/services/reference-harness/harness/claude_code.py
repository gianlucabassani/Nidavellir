"""
harness.claude_code — drive an arena with Claude Code as the BYO agent (ADR-0010).

The **subscription path.** A Claude Pro/Max subscription may only legally drive
Claude Code itself (not the Agent SDK or the raw Messages API — that needs a
pay-per-use API key; using a subscription OAuth token elsewhere violates
Anthropic's Consumer ToS). So on a subscription the bring-your-own agent *is*
Claude Code: it connects to the Nidavellir MCP gateway as an MCP server and plays
the arena with its own reasoning loop. That fits the scope boundary exactly — the
AI is the operator's (their Claude Code login), Nidavellir just exposes the arena
over MCP.

This module builds the `--mcp-config` that points Claude Code at our gateway and
the headless `claude -p` command (auto-approving the gateway's tools, JSON
output), and runs it through an **injected** subprocess runner so it is
unit-testable without the `claude` binary or a subscription. Auth is inherited
from the environment (the operator's existing Claude Code login) — we set no key
and no token here on purpose.
"""
from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed argv, no shell; the runner is injectable
from dataclasses import dataclass

DEFAULT_SERVER_NAME = "nidavellir-arena"


def gateway_mcp_server(*, agent_key: str, stance: str, api_url: str,
                       gateway_pythonpath: str, python: str = "python") -> dict:
    """The `.mcp.json` server entry for the Nidavellir gateway (stdio). Only the
    gateway's own env overrides are emitted — NOT the whole environment — so no
    unrelated secrets land in the config file."""
    return {
        "type": "stdio",
        "command": python,
        "args": ["-m", "gateway.server"],
        "env": {
            "PYTHONPATH": gateway_pythonpath,
            "NIDAVELLIR_AGENT_KEY": agent_key,
            "NIDAVELLIR_STANCE": stance,
            "NIDAVELLIR_API_URL": api_url,
            "NIDAVELLIR_GATEWAY_TRANSPORT": "stdio",
        },
    }


def build_mcp_config(server: dict, *, server_name: str = DEFAULT_SERVER_NAME) -> dict:
    """Wrap a server entry in the `{mcpServers: {...}}` shape Claude Code expects."""
    return {"mcpServers": {server_name: server}}


def write_mcp_config(path: str, config: dict) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    return path


def build_claude_command(
    *,
    prompt: str,
    mcp_config: str,
    server_name: str = DEFAULT_SERVER_NAME,
    model: str | None = None,
    output_format: str = "json",
    permission_mode: str | None = None,
    extra_allowed_tools: list[str] | None = None,
    strict_mcp_config: bool = True,
    claude_bin: str = "claude",
) -> list[str]:
    """The headless `claude -p` argv (list form — no shell). Pre-approves the
    gateway's tools with `mcp__<server>__*` so an MCP-only run never blocks on a
    permission prompt. `mcp_config` is a file path or inline JSON (both accepted
    by `--mcp-config`). `strict_mcp_config` uses ONLY our gateway server (ignores
    the operator's other MCP servers) so a benchmark run is hermetic."""
    allowed = [f"mcp__{server_name}__*", *(extra_allowed_tools or [])]
    argv = [
        claude_bin, "-p", prompt,
        "--mcp-config", mcp_config,
        "--allowedTools", ",".join(allowed),
        "--output-format", output_format,
    ]
    if strict_mcp_config:
        argv.append("--strict-mcp-config")
    if model:
        argv += ["--model", model]
    if permission_mode:
        argv += ["--permission-mode", permission_mode]
    return argv


@dataclass
class ClaudeRunResult:
    ok: bool
    result_text: str
    cost_usd: float | None
    usage: dict | None
    session_id: str | None
    returncode: int
    raw: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "result_text": self.result_text[:4000],
            "cost_usd": self.cost_usd,
            "usage": self.usage,
            "session_id": self.session_id,
            "returncode": self.returncode,
        }


def _parse_output(stdout: str) -> dict:
    """Parse Claude Code's `--output-format json` (a single JSON object). Falls
    back to treating the whole stdout as the result text if it isn't JSON."""
    try:
        obj = json.loads(stdout)
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        pass
    return {"result": stdout}


def run_claude_code(
    argv: list[str],
    *,
    runner=None,
    timeout: float = 600.0,
    env: dict | None = None,
) -> ClaudeRunResult:
    """Execute a `claude -p` command and parse its JSON result. `runner` is an
    injected callable with subprocess.run's signature (returns an object with
    `.returncode`/`.stdout`/`.stderr`); defaults to `subprocess.run`. Auth is
    inherited from `env`/the process environment — no key/token is set here."""
    runner = runner or subprocess.run
    proc = runner(argv, capture_output=True, text=True, timeout=timeout, env=env)  # nosec B603
    stdout = getattr(proc, "stdout", "") or ""
    rc = getattr(proc, "returncode", 1)
    obj = _parse_output(stdout)
    return ClaudeRunResult(
        ok=(rc == 0),
        result_text=str(obj.get("result", "")),
        cost_usd=obj.get("total_cost_usd"),
        usage=obj.get("usage"),
        session_id=obj.get("session_id"),
        returncode=rc,
        raw=stdout[:8000],
    )
