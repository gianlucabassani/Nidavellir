"""Spans: one durable record per action (ADR-0018, OBS-01).

``build`` turns an action into a storable row: W3C-sized identifiers, digests of
the full input and output, bounded previews redacted at write time, and the
visibility the truth rule requires. ``record`` stores it without ever failing the
caller. ``visible_to`` is the single read rule for agent keys.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from datetime import datetime

from redaction import MASK, redact
from timeutil import db_now

logger = logging.getLogger(__name__)

KINDS = ("tool", "model", "lifecycle", "validation", "agent")
STATUSES = ("ok", "error", "denied", "budget_refused")
ACTOR_KINDS = ("human", "agent", "system")
VISIBILITIES = ("agent", "operator")
# Kinds that can only ever be operator material (truth rule).
OPERATOR_ONLY_KINDS = frozenset({"validation"})
PREVIEW_LIMIT = 2048

# Mapping keys whose values never reach a preview, beyond redaction's own list.
_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|apikey|credential|authorization"
    r"|cookie|session|private[_-]?key)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_HEADER_LINE = re.compile(
    r"(?im)^(\s*(?:set-)?cookie|\s*(?:proxy-)?authorization)(\s*:\s*).*$")


def trace_id_for(*, arena_id: str | None = None, trial_id: str | None = None) -> str:
    """One trace per run: a trial's trace, else the arena's (deterministic)."""
    seed = f"trial:{trial_id}" if trial_id else f"arena:{arena_id}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def new_span_id() -> str:
    return secrets.token_hex(8)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value) -> str | None:
    if value is None:
        return None
    data = value if isinstance(value, (bytes, bytearray)) else _canonical(value).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _scrub(value, depth=0):
    if depth > 8:
        return "…"
    if isinstance(value, dict):
        return {str(k): (MASK if _SENSITIVE_KEY.search(str(k)) else _scrub(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in value]
    return value


def redact_preview(value) -> str | None:
    """A bounded, redacted preview. Masks sensitive keys, header lines, bearer
    tokens and JWTs, then applies the platform's known-secret redaction."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    text = value if isinstance(value, str) else _canonical(_scrub(value))
    text = _HEADER_LINE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    text = _JWT.sub(MASK, text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", text)
    text = redact(text)
    if len(text) > PREVIEW_LIMIT:
        text = text[: PREVIEW_LIMIT - 1] + "…"
    return text


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def build(*, name: str, kind: str, actor: str, actor_kind: str,
          status: str = "ok", arena_id: str | None = None,
          evaluation_id: str | None = None, trial_id: str | None = None,
          trace_id: str | None = None, parent_span_id: str | None = None,
          span_id: str | None = None, stance: str | None = None,
          started_at: datetime | None = None, ended_at: datetime | None = None,
          input=None, output=None, error_class: str | None = None,
          attrs: dict | None = None, visibility: str = "agent") -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown span kind {kind!r}")
    if status not in STATUSES:
        raise ValueError(f"unknown span status {status!r}")
    if actor_kind not in ACTOR_KINDS:
        raise ValueError(f"unknown actor kind {actor_kind!r}")
    if visibility not in VISIBILITIES:
        raise ValueError(f"unknown visibility {visibility!r}")
    if kind in OPERATOR_ONLY_KINDS:
        visibility = "operator"
    started = _naive(started_at) or _naive(db_now())
    ended = _naive(ended_at) or started
    duration = max(0, int((ended - started).total_seconds() * 1000))
    return {
        "span_id": span_id or new_span_id(),
        "trace_id": trace_id or trace_id_for(arena_id=arena_id, trial_id=trial_id),
        "parent_span_id": parent_span_id,
        "arena_id": arena_id, "evaluation_id": evaluation_id, "trial_id": trial_id,
        "actor": actor[:128], "actor_kind": actor_kind, "stance": stance,
        "kind": kind, "name": name[:128],
        "started_at": started, "ended_at": ended, "duration_ms": duration,
        "status": status, "error_class": (error_class or None) and error_class[:128],
        "input_digest": digest(input), "output_digest": digest(output),
        "input_preview": redact_preview(input), "output_preview": redact_preview(output),
        "attrs": _canonical(_scrub(attrs)) if attrs else None,
        "visibility": visibility,
    }


def record(db, **fields) -> int | None:
    """Build and store a span. Never raises: a span must not fail its action."""
    try:
        return db.insert_span(build(**fields))
    except Exception:  # noqa: BLE001 - observability is best-effort for the caller
        logger.warning("span write failed for %s", fields.get("name"), exc_info=True)
        return None


def visible_to(role: str) -> tuple[str, ...]:
    """Visibility values a principal role may read (agents: agent spans only)."""
    return VISIBILITIES if role != "agent" else ("agent",)
