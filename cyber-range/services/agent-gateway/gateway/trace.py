"""
Append-only JSONL trace of agent tool calls.

Every gateway tool call is recorded (`traces/<arena_id>.jsonl`) for replay,
audit, and — once scoring lands — eval datasets. The agent is identified by its
non-reversible `agent_id`, never its raw key; lifecycle args (scenario / arena
id / provider) carry no secrets, so they are recorded verbatim.
"""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


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
    entry = {
        "ts": now if now is not None else time.time(),
        "agent_id": agent_id,
        "stance": stance,
        "tool": tool,
        "args": args,
        "ok": ok,
        "arena_id": arena_id,
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
