"""
Configurator setup-phase state (ADR-0007 / P2-10, increment 1).

The arena setup phase is an event-backed overlay on an ACTIVE arena — no new
LabStatus, no migration (mirrors `agent_session`): a `setup_session` event opens
the phase, `setup_step` events record each gated step, `setup_finished` closes it
(operator-finished or time-box-expired). The current state is *derived* from the
event stream so it survives restarts, and the orchestrator is the single
enforcement point (consent + victim-scope + time-box + step budget).

Increment 1 is the **operator-scripted** mode — the AI-optional human path: a
human operator drives the steps through the orchestrator API; no gateway, no AI,
no HITL approval flow (those are increments 2/3).
"""
from datetime import datetime

SETUP_OPEN = "setup_session"
SETUP_STEP = "setup_step"
SETUP_FINISHED = "setup_finished"

DEFAULT_TIME_BOX_SECONDS = 1800          # 30 min
MAX_TIME_BOX_SECONDS = 6 * 3600          # hard ceiling
DEFAULT_COMMAND_BUDGET = 50
MAX_COMMAND_BUDGET = 500                 # also the events fetch window


def current_session(events: list[dict]) -> dict | None:
    """The open setup session derived from an arena's events (newest-first), or
    None if there is no open session. The most-recent setup *lifecycle* event
    decides: a `setup_finished` means closed; a `setup_session` means open."""
    open_evt = None
    for e in events:  # newest-first (Database.list_events orders by id desc)
        t = e.get("type")
        if t == SETUP_FINISHED:
            return None
        if t == SETUP_OPEN:
            open_evt = e
            break
    if open_evt is None:
        return None

    p = open_evt.get("payload") or {}
    open_id = open_evt.get("id") or 0
    steps_run = sum(
        1
        for e in events
        if e.get("type") == SETUP_STEP and (e.get("id") or 0) > open_id
    )
    return {
        "session_id": p.get("session_id"),
        "started_at": p.get("started_at"),
        "expires_at": p.get("expires_at"),
        "nodes": list(p.get("nodes") or []),
        "command_budget": p.get("command_budget", DEFAULT_COMMAND_BUDGET),
        "setup_egress": bool(p.get("setup_egress")),
        "actor": p.get("actor"),
        "steps_run": steps_run,
        "open_event_id": open_id,
    }


def is_expired(session: dict, now: datetime) -> bool:
    """True if the session's time-box has elapsed (fail-safe auto-revoke)."""
    exp = session.get("expires_at")
    if not exp:
        return False
    try:
        return now > datetime.fromisoformat(exp)
    except (TypeError, ValueError):
        return False


def budget_remaining(session: dict) -> int:
    return max(0, int(session.get("command_budget", 0)) - int(session.get("steps_run", 0)))
