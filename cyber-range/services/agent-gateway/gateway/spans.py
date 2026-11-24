"""OBS-03: gateway tool calls in the orchestrator's trace.

Each MCP tool call that names an arena gets a span ID. While the call runs, the
REST client sends it as a W3C ``traceparent`` so the orchestrator's action spans
nest under it; afterwards the gateway reports the call itself to
``POST /arenas/{id}/spans``. Reporting is best-effort: it never fails a tool.
"""
from __future__ import annotations

import functools
import hashlib
import logging
import secrets
import time
from contextvars import ContextVar
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CURRENT: ContextVar[tuple[str, str] | None] = ContextVar("nv_span", default=None)


def trace_id_for_arena(arena_id: str) -> str:
    """Same derivation as the orchestrator's ``spans.trace_id_for`` (ADR-0018)."""
    return hashlib.sha256(f"arena:{arena_id}".encode()).hexdigest()[:32]


def traceparent() -> str | None:
    current = CURRENT.get()
    if current is None:
        return None
    trace_id, span_id = current
    return f"00-{trace_id}-{span_id}-01"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def traced(fn, ctx_factory):
    """Wrap one MCP tool so its call becomes a span in the arena's trace."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        arena_id = kwargs.get("arena_id")
        if not isinstance(arena_id, str) or not arena_id:
            return fn(*args, **kwargs)
        span_id = secrets.token_hex(8)
        token = CURRENT.set((trace_id_for_arena(arena_id), span_id))
        started = time.time()
        error = None
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            CURRENT.reset(token)
            _report(ctx_factory, arena_id, fn.__name__, span_id, started, time.time(),
                    error, {k: v for k, v in kwargs.items() if k != "arena_id"})
    return inner


def _report(ctx_factory, arena_id, tool, span_id, started, ended, error, args):
    try:
        ctx = ctx_factory()
        ctx.client.report_span(ctx.session.api_key, arena_id, {
            "span_id": span_id, "name": tool, "kind": "agent",
            "started_at": _iso(started), "ended_at": _iso(ended),
            "status": "error" if error else "ok", "error_class": error,
            "input": args,
            "attrs": {"nv.source": "gateway", "tool.name": tool,
                      "openinference.span.kind": "TOOL",
                      "gen_ai.operation.name": "execute_tool",
                      "nv.stance": ctx.session.stance.value if ctx.session.stance else None},
        })
    except Exception as exc:  # noqa: BLE001 - tracing must never break a tool call
        logger.warning("span report failed for %s: %s", tool, type(exc).__name__)
