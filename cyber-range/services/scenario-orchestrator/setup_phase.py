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
SETUP_PROPOSAL = "setup_proposal"            # HITL: an agent-proposed step (pending)
SETUP_PROPOSAL_DECISION = "setup_proposal_decision"  # operator approve/reject + result

DEFAULT_TIME_BOX_SECONDS = 1800          # 30 min
MAX_TIME_BOX_SECONDS = 6 * 3600          # hard ceiling
DEFAULT_COMMAND_BUDGET = 50
MAX_COMMAND_BUDGET = 500                 # also the events fetch window

# Setup modes — how the service is brought up (consent recorded at setup/start).
MODE_OPERATOR = "operator"        # operator runs steps directly (AI-optional, inc. 1)
MODE_HITL = "hitl"                # agent proposes, operator approves each (inc. 2)
MODE_AUTONOMOUS = "autonomous"    # agent runs directly — double-locked (inc. 3)
MODES = (MODE_OPERATOR, MODE_HITL, MODE_AUTONOMOUS)


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
        "mode": p.get("mode", MODE_OPERATOR),
        "actor": p.get("actor"),
        "steps_run": steps_run,
        "open_event_id": open_id,
    }


def pending_proposals(events: list[dict], session_id: str) -> list[dict]:
    """HITL proposals for the current session that have not been decided yet."""
    decided = {
        (e.get("payload") or {}).get("step_id")
        for e in events
        if e.get("type") == SETUP_PROPOSAL_DECISION
    }
    out = []
    for e in events:  # newest-first
        if e.get("type") != SETUP_PROPOSAL:
            continue
        p = e.get("payload") or {}
        if p.get("session_id") != session_id or p.get("step_id") in decided:
            continue
        out.append({
            "step_id": p.get("step_id"), "node": p.get("node"),
            "command": p.get("command"), "rationale": p.get("rationale"),
            "actor": p.get("actor"), "ts": e.get("ts"),
        })
    return out


def proposal_status(events: list[dict], step_id: str) -> dict | None:
    """The lifecycle of one proposal: pending, or the operator's decision +
    (for an approved step) the captured exec result. None if no such proposal."""
    proposal = None
    decision = None
    for e in events:  # newest-first
        p = e.get("payload") or {}
        if p.get("step_id") != step_id:
            continue
        if e.get("type") == SETUP_PROPOSAL_DECISION and decision is None:
            decision = p
        elif e.get("type") == SETUP_PROPOSAL and proposal is None:
            proposal = p
    if proposal is None:
        return None
    if decision is None:
        return {"step_id": step_id, "status": "pending", "node": proposal.get("node"),
                "command": proposal.get("command")}
    return {
        "step_id": step_id,
        "status": decision.get("decision", "decided"),  # approved | rejected
        "node": proposal.get("node"),
        "command": proposal.get("command"),
        "exit_code": decision.get("exit_code"),
        "stdout": decision.get("stdout"),
        "stderr": decision.get("stderr"),
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
