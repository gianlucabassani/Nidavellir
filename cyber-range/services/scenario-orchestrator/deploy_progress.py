"""UX-05: per-phase deploy progress as `deploy_phase` events.

The worker wraps a deploy in ``reporting(db, instance_id)``; providers call
``phase(name)`` at each boundary without any signature change. Outside a
reporting context ``phase`` is a no-op, so providers stay usable directly.

Events are informational and best-effort: a failure to record progress never
fails the deploy. The arena state machine stays authoritative.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

EVENT = "deploy_phase"
# Display order. Providers report the subset that applies to them.
PHASES = ("network", "pull", "nodes", "readiness")
STATES = ("started", "done", "skipped", "failed")

_current: ContextVar[dict | None] = ContextVar("deploy_progress", default=None)


@contextmanager
def reporting(db, instance_id: str):
    token = _current.set({"db": db, "instance_id": instance_id, "open": None})
    try:
        yield
    finally:
        _current.reset(token)


def _record(name: str, state: str, detail: dict) -> None:
    ctx = _current.get()
    if ctx is None:
        return
    if name not in PHASES or state not in STATES:
        raise ValueError(f"unknown deploy phase {name}/{state}")
    payload = {"phase": name, "state": state}
    payload.update({k: v for k, v in detail.items() if isinstance(v, (str, int, float, bool))})
    try:
        ctx["db"].record_event(ctx["instance_id"], EVENT, payload, actor="worker")
    except Exception:  # noqa: BLE001 - progress is best-effort
        logger.warning("[%s] could not record deploy phase %s/%s",
                       ctx["instance_id"], name, state, exc_info=True)


def mark(name: str, state: str, **detail) -> None:
    """Record a sub-step (e.g. a pull inside ``nodes``) without changing the open phase."""
    _record(name, state, detail)


def phase(name: str, **detail) -> None:
    """Mark ``name`` started, closing the previously open phase as done."""
    ctx = _current.get()
    if ctx is None:
        return
    if ctx["open"] == name and not detail:
        return
    if ctx["open"] and ctx["open"] != name:
        _record(ctx["open"], "done", {})
    ctx["open"] = name
    _record(name, "started", detail)


def done(name: str | None = None, **detail) -> None:
    """Close ``name`` (default: the open phase) as done."""
    ctx = _current.get()
    if ctx is None:
        return
    name = name or ctx["open"]
    if not name:
        return
    if ctx["open"] == name:
        ctx["open"] = None
    _record(name, "done", detail)


def skipped(name: str, **detail) -> None:
    _record(name, "skipped", detail)


def failed(error: str = "") -> None:
    """Mark the open phase failed (the deploy result carries the full error)."""
    ctx = _current.get()
    if ctx is None or not ctx["open"]:
        return
    name, ctx["open"] = ctx["open"], None
    _record(name, "failed", {"error": error[:300]})


def record(db, instance_id: str, name: str, state: str, **detail) -> None:
    """Record one phase transition directly, outside a reporting context."""
    with reporting(db, instance_id):
        _record(name, state, detail)
