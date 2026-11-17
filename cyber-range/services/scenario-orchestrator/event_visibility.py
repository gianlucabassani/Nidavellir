"""
Which audit events an agent key may read (review item FR-04).

Deny by default. An ``agent`` principal reads events only for an arena it is
bound to, and only the types listed here: the arena's lifecycle status and the
research activity performed in it, with body-free payloads, plus participant
finding claims with the validator's match and verdict removed. Everything else is
operator material and stays hidden: operator judgment (verification, request
groups, review state, campaigns), validator and referee internals (helper jobs,
lifecycle recipes and observations, monitor log evidence), engagement intent,
bindings, budgets, stops, setup sessions and resets. An event type added later is
hidden until it is reviewed and listed here.

This replaces the denylist that ``api._redact_findings_for_agent`` used to apply.
Spans (FR-10) and the live stream (FR-14) must reuse this module rather than
define a second rule.
"""

# Visible to every bound agent, whatever its stance.
AGENT_VISIBLE_EVENT_TYPES = frozenset({
    # arena lifecycle status
    "created", "status",
    # participant activity in the arena (metadata and digests, never bodies)
    "agent_session", "agent_exec", "http_request", "browser_visit",
    "file_upload", "file_download", "mitm_observe", "workspace_diff",
    "evidence_artifact", "poc_job_submitted", "poc_job_cancel_requested",
    "forward_opened", "forward_connected", "forward_closed", "forward_revoked",
    # participant claims, redacted below
    "finding",
})

# Extra types a stance needs for its own job. The defender's detection feed
# includes the monitor's fault signals; they carry target log evidence, which
# would be an oracle for an attacker, so no other stance receives them.
STANCE_VISIBLE_EVENT_TYPES = {
    "defender": frozenset({"monitor_signal"}),
}

# Payload keys that carry ground truth and never reach an agent.
HIDDEN_PAYLOAD_KEYS = {
    "finding": ("matched_vuln_id", "validation"),
}


def visible_event_types(stance: str | None) -> frozenset[str]:
    """The event types a bound agent with ``stance`` may read."""
    return AGENT_VISIBLE_EVENT_TYPES | STANCE_VISIBLE_EVENT_TYPES.get(stance or "", frozenset())


def _visible(event: dict, allowed: frozenset[str]) -> bool:
    kind = event.get("type")
    if kind not in allowed:
        return False
    payload = event.get("payload")
    # An operator-entered finding is operator judgment, not a participant claim.
    return not (kind == "finding" and isinstance(payload, dict) and payload.get("manual"))


def redact_for_agent(events: list[dict], stance: str | None) -> list[dict]:
    """Keep only allowlisted events and strip hidden payload keys."""
    allowed = visible_event_types(stance)
    shown = []
    for event in events:
        if not _visible(event, allowed):
            continue
        hidden = HIDDEN_PAYLOAD_KEYS.get(event.get("type") or "", ())
        payload = event.get("payload")
        if hidden and isinstance(payload, dict) and any(key in payload for key in hidden):
            event = {**event, "payload": {k: v for k, v in payload.items() if k not in hidden}}
        shown.append(event)
    return shown
