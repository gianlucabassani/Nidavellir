"""
Agent ↔ arena bindings — server-enforced key↔arena/session binding
(ROADMAP §2.1 **D1**; ADR-0005 guardrail "per-arena key↔session binding").

The orchestrator — not just the gateway — must decide whether an *agent* key may
drive a given arena, and in what stance. Without this, any valid agent key could
run commands / configure the victim / report findings on **any** arena: the
gateway's stance gate is client-side only and a direct REST call bypassed it.

A **binding** authorizes one agent principal to act on one arena. State is
event-backed (no migration — mirrors `setup_phase` / `agent_session`): an
``agent_binding`` event grants, ``agent_binding_revoked`` revokes. The current
set is *derived* newest-first from the arena's event stream, so it survives
restarts and the orchestrator stays the single enforcement point.

Bindings constrain the **agent** role only — operators/admins author and run
engagements and manage every arena, so they are never bound (the API bypasses the
check for them).

A binding carries a **stance** (or ``None``):
  - ``None``       — unrestricted within the arena. Granted automatically to the
                     agent that *deployed* the arena (its own sandbox).
  - stance-scoped  — an operator grant (or a ``setup/start`` configurator grant)
                     that permits only that stance's capabilities — the
                     server-side stance enforcement D1 calls for.
"""

BINDING_GRANT = "agent_binding"
BINDING_REVOKE = "agent_binding_revoked"
BINDING_EVENT_TYPES = (BINDING_GRANT, BINDING_REVOKE)
# Bindings are few per arena (≈ one per agent); a generous window covers any arena
# without engagement noise mattering (these types are fetched on their own anyway).
BINDING_EVENT_WINDOW = 256

# Stances an operator may grant. Kept in lockstep with the gateway's `Stance`
# enum, but defined here so the orchestrator does not depend on the gateway pkg.
STANCES = ("attacker", "mitm", "defender", "configurator")

# Capability classes a bound agent may exercise, and which stances permit each.
CAP_EXEC = "exec"        # run_command / report_finding (attacker)
CAP_SETUP = "setup"      # configurator setup steps (configurator)
CAP_OBSERVE = "observe"  # in-path traffic capture on a shared segment (mitm)

# stance -> permitted capabilities. `None` (own-sandbox) permits everything;
# a stance-scoped binding permits only its stance's class. Reads (status/events)
# are intentionally NOT capability-gated — D1 is about *driving* an arena.
_STANCE_CAPS: dict[str | None, set[str]] = {
    None: {CAP_EXEC, CAP_SETUP, CAP_OBSERVE},
    "attacker": {CAP_EXEC},
    "configurator": {CAP_SETUP},
    "defender": set(),
    "mitm": {CAP_OBSERVE},
}


def stance_permits(stance: str | None, capability: str) -> bool:
    """True if a binding with `stance` may perform `capability`."""
    return capability in _STANCE_CAPS.get(stance, set())


def _binding_view(agent_name: str, payload: dict, ts) -> dict:
    return {
        "agent_name": agent_name,
        "stance": payload.get("stance"),
        "granted_by": payload.get("granted_by"),
        "session_id": payload.get("session_id"),
        "auto": bool(payload.get("auto")),
        "ts": ts,
    }


def binding_for(events: list[dict], agent_name: str) -> dict | None:
    """The active binding for `agent_name`, derived newest-first, or None. The
    most-recent grant/revoke for that agent decides: a ``agent_binding_revoked``
    (or no grant at all) means not bound."""
    for e in events:  # newest-first (Database.list_events orders by id desc)
        p = e.get("payload") or {}
        if p.get("agent_name") != agent_name:
            continue
        t = e.get("type")
        if t == BINDING_REVOKE:
            return None
        if t == BINDING_GRANT:
            return _binding_view(agent_name, p, e.get("ts"))
    return None


def active_bindings(events: list[dict]) -> list[dict]:
    """All currently-active bindings (one per agent), newest grant first. An agent
    whose most-recent binding event is a revoke is omitted."""
    seen: set[str] = set()
    out: list[dict] = []
    for e in events:  # newest-first
        p = e.get("payload") or {}
        name = p.get("agent_name")
        if not name or name in seen:
            continue
        seen.add(name)
        if e.get("type") == BINDING_GRANT:
            out.append(_binding_view(name, p, e.get("ts")))
    return out
