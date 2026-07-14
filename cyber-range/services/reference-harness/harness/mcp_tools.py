"""
harness.mcp_tools — a `ToolsInterface` backed by the Nidavellir MCP gateway.

Dogfoods the real seam: the harness talks to the arena the same way any BYO agent
does — over MCP, through the stance-gated, traced, budget-enforced gateway — rather
than reaching into the orchestrator. Opens one stdio session to
`python -m gateway.server` and keeps it open for the whole engagement.

The `mcp` SDK is imported lazily so the harness package (and its pure-loop unit
tests) import without a live MCP install.
"""
from __future__ import annotations

import json
import os


def gateway_env(*, agent_key: str, stance: str, api_url: str,
                gateway_pythonpath: str, extra: dict | None = None) -> dict:
    """Environment for the gateway subprocess (agent key + stance + upstream API)."""
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": gateway_pythonpath,
        "NIDAVELLIR_AGENT_KEY": agent_key,
        "NIDAVELLIR_STANCE": stance,
        "NIDAVELLIR_API_URL": api_url,
        "NIDAVELLIR_GATEWAY_TRANSPORT": "stdio",
    })
    env.update(extra or {})
    return env


def _unwrap(result) -> dict:
    """Coerce an MCP tool result to a plain dict."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    content = getattr(result, "content", None) or []
    if content and getattr(content[0], "text", None) is not None:
        try:
            return json.loads(content[0].text)
        except (ValueError, TypeError):
            return {"text": content[0].text}
    return {}


class McpToolsInterface:
    """Async context manager: `async with McpToolsInterface(...) as tools:` opens a
    gateway stdio session; `list_tools()` / `call()` implement the loop's
    `ToolsInterface`."""

    def __init__(self, *, command: str, args: list[str], env: dict,
                 arena_id: str | None = None):
        self._command = command
        self._args = args
        self._env = env
        # When set, arena_id is auto-injected into every tool call whose schema
        # takes it — so a brain calls `get_topology()` / `report_finding(...)`
        # without threading the arena id through every step.
        self._arena_id = arena_id
        self._tool_defs: list[dict] = []
        self._stdio_cm = None
        self._session_cm = None
        self._session = None

    async def __aenter__(self) -> "McpToolsInterface":
        from mcp import ClientSession, StdioServerParameters  # noqa: PLC0415 - lazy
        from mcp.client.stdio import stdio_client  # noqa: PLC0415

        params = StdioServerParameters(command=self._command, args=self._args, env=self._env)
        self._stdio_cm = stdio_client(params)
        read, write = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc):
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(*exc)
        finally:
            if self._stdio_cm is not None:
                await self._stdio_cm.__aexit__(*exc)

    async def list_tools(self) -> list[dict]:
        res = await self._session.list_tools()
        self._tool_defs = [
            {"name": t.name, "description": t.description or "",
             "input_schema": t.inputSchema or {"type": "object", "properties": {}}}
            for t in res.tools
        ]
        return self._tool_defs

    def _takes_arena_id(self, name: str) -> bool:
        for t in self._tool_defs:
            if t["name"] == name:
                return "arena_id" in ((t.get("input_schema") or {}).get("properties") or {})
        return False

    async def call(self, name: str, args: dict) -> dict:
        args = dict(args or {})
        if self._arena_id and "arena_id" not in args and self._takes_arena_id(name):
            args["arena_id"] = self._arena_id
        res = await self._session.call_tool(name, args)
        return _unwrap(res)
