"""
Agent stances and their tool allow-lists.

A stance is how a bring-your-own agent is wired into an arena. Every session
may call the shared *lifecycle* tools; the per-stance *execution* toolsets
(`run_command`, `observe_stream`, `query_events`, …) are intentionally EMPTY in
this skeleton — they (and their guardrails) land in a later, separately
reviewed increment. `allowed_tools()` is the single source of truth the gateway
uses to gate a call, so an unbound or wrong-stance session cannot reach a tool
it should not.
"""
from enum import Enum


class Stance(str, Enum):
    attacker = "attacker"
    mitm = "mitm"
    defender = "defender"


# Shared lifecycle tools — available to every authenticated session.
LIFECYCLE_TOOLS = frozenset(
    {"list_scenarios", "deploy_arena", "arena_status", "get_briefing", "destroy_arena"}
)

# Per-stance execution/recon toolsets, gated by stance.
#   attacker — recon the arena and run commands from the foothold (offensive).
#   MITM / defender — land in the next increments (intercept / detect).
STANCE_TOOLS: dict[Stance, frozenset[str]] = {
    Stance.attacker: frozenset({"get_topology", "list_targets", "run_command"}),
    Stance.mitm: frozenset(),
    Stance.defender: frozenset(),
}


def parse_stance(value: str | None) -> Stance | None:
    """Coerce a stance string to a Stance, or None when unbound."""
    if value is None or value == "":
        return None
    try:
        return Stance(value)
    except ValueError:
        raise ValueError(
            f"unknown stance {value!r}; expected one of "
            f"{[s.value for s in Stance]}"
        ) from None


def allowed_tools(stance: Stance | None) -> frozenset[str]:
    """The full set of tools a session bound to `stance` may call."""
    tools = set(LIFECYCLE_TOOLS)
    if stance is not None:
        tools |= STANCE_TOOLS.get(stance, frozenset())
    return frozenset(tools)
