"""
Append-only JSONL trace of agent tool calls.

Every gateway tool call is recorded (`traces/<arena_id>.jsonl`) for replay,
audit, and eval datasets (ROADMAP M3, ADR-0010). The agent is identified by its
non-reversible `agent_id`, never its raw key; lifecycle args (scenario / arena
id / provider) carry no secrets, so they are recorded verbatim.

Each entry additionally carries **OpenInference / OpenTelemetry-GenAI** fields —
`span_kind` + an `attributes` block (`openinference.span.kind`, `tool.name`,
`gen_ai.operation.name`) — so a trace flows into Langfuse / Phoenix / Braintrust
without reshaping. The extra fields are additive: existing consumers that read
`tool`/`args`/`ok` are unaffected.
"""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Tools that act at the agent/session scope map to an OpenInference AGENT span;
# every other gateway tool is a TOOL execution. `report_finding` is the agent
# emitting its result, so it reads as agent-scope too.
_AGENT_SCOPE_TOOLS = frozenset({"announce_agent", "get_briefing", "report_finding"})


def _span(tool: str) -> tuple[str, str]:
    """(gen_ai operation name, OpenInference span kind) for a gateway tool."""
    if tool in _AGENT_SCOPE_TOOLS:
        return "invoke_agent", "AGENT"
    return "execute_tool", "TOOL"


def record(
    trace_dir: str | None,
    *,
    agent_id: str,
    stance: str | None,
    tool: str,
    args: dict,
    ok: bool,
    arena_id: str | None = None,
    now: float | None = None,
) -> Path | None:
    """Append one trace entry; a no-op (returns None) when tracing is off."""
    if not trace_dir:
        return None
    operation, span_kind = _span(tool)
    entry = {
        "ts": now if now is not None else time.time(),
        "agent_id": agent_id,
        "stance": stance,
        "tool": tool,
        "args": args,
        "ok": ok,
        "arena_id": arena_id,
        # OpenInference / OTel-GenAI alignment (ADR-0010) — zero-reshape import.
        "span_kind": operation,
        "attributes": {
            "openinference.span.kind": span_kind,
            "gen_ai.operation.name": operation,
            "gen_ai.conversation.id": arena_id,
            "tool.name": tool,
        },
    }
    path = Path(trace_dir) / f"{arena_id or 'session'}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as e:
        # Tracing must never break a tool call.
        logger.warning("trace write failed (%s): %s", path, e)
        return None
    return path
