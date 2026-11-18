"""
F3 (work order 2026-11-18): a bounded research digest.

One deterministic read that replaces an agent re-reading its own multi-megabyte
run log every cycle. Built only from sources of truth already held by the
orchestrator (deployment row, budget account, audit events) — no model call, no
summarisation. The serialized document never exceeds ``MAX_BYTES``.

What a caller sees is decided before this module runs: an agent's events have
already passed ``event_visibility.redact_for_agent`` (so no validator matches or
operator verdicts), and ``verdicts`` is only supplied for operator callers.

Vocabulary:
  - *cycle*: one ``agent_session`` announcement (a harness run calls
    ``announce_agent`` once at start).
  - *hypothesis*: a participant finding claim. ``evidenced`` claims cite a
    recorded HTTP transaction or evidence artifact; ``asserted`` ones cite none.
"""
from __future__ import annotations

import json
from datetime import datetime

SCHEMA = "nidavellir.research-digest.v1"
MAX_BYTES = 2048
MAX_TITLES = 10
MAX_RECENT = 3
MAX_NEXT_ACTIONS = 3
LOW_TIME_SECONDS = 900

# Activity worth showing as a "last log line"; lifecycle noise is skipped.
MEANINGFUL_TYPES = (
    "agent_exec", "http_request", "browser_visit", "file_upload", "file_download",
    "mitm_observe", "workspace_diff", "evidence_artifact", "poc_job_submitted",
    "forward_opened", "finding", "arena_extended",
)

# Which payload keys summarise each activity line (first present wins order).
_LINE_KEYS = ("title", "command", "method", "path", "url", "status_code",
              "exit_code", "node", "target", "seconds")


def _seconds_until(value, now: datetime) -> int | None:
    if not value:
        return None
    moment = datetime.fromisoformat(str(value))
    return max(0, int((moment - now).total_seconds()))


def _clip(text, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _line(event: dict, limit: int) -> str:
    payload = event.get("payload") or {}
    parts = [f"{k}={payload[k]}" for k in _LINE_KEYS
             if isinstance(payload, dict) and payload.get(k) not in (None, "")]
    ts = str(event.get("ts") or "")[11:19]
    return _clip(f"{ts} {event.get('type')} " + " ".join(parts), limit)


def _evidenced(payload: dict) -> bool:
    return bool(payload.get("transaction_digests") or payload.get("evidence_artifact_digests"))


def _next_actions(*, status, stopped, seconds_left, remaining, cap, asserted,
                  findings, can_extend) -> list[str]:
    actions = []
    if status in ("pending", "deploying"):
        actions.append(f"arena is {status}: poll arena_status until active")
    elif status != "active":
        actions.append(f"arena is {status}: no research possible; ask the operator")
    if stopped:
        actions.append("research is stopped: wait for the operator to resume")
    if seconds_left is not None and seconds_left < LOW_TIME_SECONDS and status in (
            "pending", "deploying", "active"):
        actions.append("time box nearly over: extend_arena(seconds=3600)" if can_extend
                       else "time box nearly over: ask the operator to extend")
    if remaining is not None and cap and remaining <= max(1, cap // 10):
        actions.append(f"action budget low ({remaining} left): prioritise confirmation")
    if asserted:
        actions.append(f"attach transaction_digests to {asserted} asserted finding(s)")
    if not findings and status == "active" and not stopped:
        actions.append("no findings yet: get_topology, then probe the targets")
    return actions[:MAX_NEXT_ACTIONS]


def build(*, arena: dict, budget: dict, finding_events: list[dict],
          activity_events: list[dict], session_count: int, now: datetime,
          verdicts: dict[str, str] | None = None, can_extend: bool = False) -> dict:
    """Assemble the digest (unbounded); ``render`` enforces the byte cap.

    ``finding_events`` and ``activity_events`` are newest-first and already
    filtered to what the caller may see."""
    policy = (budget or {}).get("policy") or {}
    gate = (budget or {}).get("arena") or {}
    system = (budget or {}).get("system") or {}
    stopped = gate.get("state", "open") != "open" or system.get("state", "open") != "open"
    seconds_left = _seconds_until(arena.get("expires_at"), now)
    findings = [e.get("payload") or {} for e in finding_events]
    evidenced = sum(1 for p in findings if _evidenced(p))
    hypotheses = {"evidenced": evidenced, "asserted": len(findings) - evidenced}
    if verdicts is not None:
        counts = {"confirmed": 0, "refuted": 0, "unreviewed": 0}
        for p in findings:
            verdict = verdicts.get(p.get("finding_id"), "unreviewed")
            counts[verdict if verdict in counts else "unreviewed"] += 1
        hypotheses["verdicts"] = counts
    recent = [e for e in activity_events if e.get("type") in MEANINGFUL_TYPES][:MAX_RECENT]
    return {
        "schema": SCHEMA,
        "arena": {"id": arena.get("id"), "status": arena.get("status"),
                  "scenario": arena.get("scenario")},
        "seconds_left": seconds_left,
        "budget": {"remaining": policy.get("remaining"), "cap": policy.get("action_cap"),
                   "deadline_seconds_left": _seconds_until(policy.get("deadline"), now),
                   "stopped": stopped},
        "cycles": session_count,
        "hypotheses": hypotheses,
        "findings": {"count": len(findings),
                     "titles": [str(p.get("title") or "") for p in findings[:MAX_TITLES]]},
        "recent": recent,
        "next_actions": _next_actions(
            status=arena.get("status"), stopped=stopped, seconds_left=seconds_left,
            remaining=policy.get("remaining"), cap=policy.get("action_cap"),
            asserted=hypotheses["asserted"], findings=len(findings),
            can_extend=can_extend),
    }


def _encode(doc: dict) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def render(digest: dict, max_bytes: int = MAX_BYTES) -> bytes:
    """Serialize ``digest`` compactly within ``max_bytes``.

    Shrinks deterministically, least valuable first: line and title lengths,
    then the number of recent lines and titles, then the advice text. The
    counts (findings, hypotheses, budget, time) are never dropped."""
    recent_events = digest["recent"]
    titles = digest["findings"]["titles"]
    steps = [(120, 80, MAX_RECENT, MAX_TITLES, 160), (80, 60, MAX_RECENT, MAX_TITLES, 120),
             (60, 40, MAX_RECENT, 6, 100), (48, 32, 2, 4, 80), (40, 24, 1, 2, 64),
             (32, 16, 1, 1, 48), (0, 0, 0, 0, 40)]
    for line_len, title_len, n_recent, n_titles, advice_len in steps:
        doc = dict(digest)
        doc["recent"] = [_line(e, line_len) for e in recent_events[:n_recent]] if line_len else []
        doc["findings"] = {**digest["findings"],
                           "titles": [_clip(t, title_len) for t in titles[:n_titles]],
                           # True when not every finding's title is listed.
                           "titles_truncated": min(n_titles, len(titles))
                           < digest["findings"]["count"]}
        doc["next_actions"] = [_clip(a, advice_len) for a in digest["next_actions"]]
        body = _encode(doc)
        if len(body) <= max_bytes:
            return body
    # Unreachable with sane ids; fail closed rather than exceed the contract.
    raise ValueError("digest cannot be rendered within its byte cap")
