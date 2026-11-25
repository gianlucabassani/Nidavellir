"""Global operator search (UX-13, FR-18): arenas, findings, HTTP transactions
and spans, by text or by digest prefix.

Operator-only by construction: the caller checks the role, and every source
here is operator-visible material (span previews are redacted at write time).
On PostgreSQL text matching uses the full-text indexes of migration 0013 (the
SQL expressions below must stay identical to the index expressions); elsewhere
it falls back to LIKE. Each group is bounded and newest first.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import or_, select, text

from models import Deployment, Event, Span

LIMIT = 10
MAX_QUERY = 200
_DIGEST = re.compile(r"(?:sha256:)?([0-9a-f]{6,64})\Z")
_WORD = re.compile(r"[a-z0-9_]+")

EVENTS_FTS = ("to_tsvector('simple', regexp_replace(coalesce(events.payload, ''), "
              "'[^[:alnum:]_]+', ' ', 'g')) @@ to_tsquery('simple', :tsq)")
SPANS_FTS = ("to_tsvector('simple', regexp_replace(spans.name || ' ' || "
             "coalesce(spans.input_preview, ''), '[^[:alnum:]_]+', ' ', 'g'))"
             " @@ to_tsquery('simple', :tsq)")


def _like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _payload(row) -> dict:
    try:
        data = json.loads(row.payload) if row.payload else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _words(query: str) -> list[str]:
    return _WORD.findall(query.lower())[:8]


def search(session, query: str, limit: int = LIMIT) -> dict:
    query = (query or "").strip()[:MAX_QUERY]
    digest = _DIGEST.fullmatch(query.lower())
    words = _words(query)
    empty = {"query": query, "mode": "none", "arenas": [], "findings": [],
             "transactions": [], "spans": []}
    if not digest and not words:
        return empty
    postgres = session.bind.dialect.name == "postgresql"
    if digest:
        return {**empty, "mode": "digest",
                **_by_digest(session, digest.group(1), limit)}
    return {**empty, "mode": "text", **_by_text(session, query, words, postgres, limit)}


def _by_text(session, query, words, postgres, limit) -> dict:
    tsq = " & ".join(f"{word}:*" for word in words)

    def events(kind):
        stmt = select(Event).where(Event.type == kind)
        if postgres:
            stmt = stmt.where(text(EVENTS_FTS).bindparams(tsq=tsq))
        else:
            for word in words:
                stmt = stmt.where(Event.payload.ilike(f"%{_like(word)}%", escape="\\"))
        return session.scalars(stmt.order_by(Event.id.desc()).limit(limit)).all()

    span_stmt = select(Span)
    if postgres:
        span_stmt = span_stmt.where(text(SPANS_FTS).bindparams(tsq=tsq))
    else:
        for word in words:
            pattern = f"%{_like(word)}%"
            span_stmt = span_stmt.where(or_(Span.name.ilike(pattern, escape="\\"),
                                            Span.input_preview.ilike(pattern, escape="\\")))
    spans = session.scalars(span_stmt.order_by(Span.id.desc()).limit(limit)).all()
    pattern = f"%{_like(query.lower())}%"
    arenas = session.scalars(select(Deployment).where(or_(
        Deployment.id.ilike(pattern, escape="\\"),
        Deployment.scenario.ilike(pattern, escape="\\"),
        Deployment.user_id.ilike(pattern, escape="\\"))).order_by(
        Deployment.created_at.desc()).limit(limit)).all()
    return {"arenas": [_arena(row) for row in arenas],
            "findings": [_finding(row) for row in events("finding")],
            "transactions": [_transaction(row) for row in events("http_request")],
            "spans": [_span(row) for row in spans]}


def _by_digest(session, hexpart: str, limit: int) -> dict:
    full = f"sha256:{hexpart}"
    prefix = f"{_like(full)}%"
    spans = session.scalars(select(Span).where(or_(
        Span.input_digest.like(prefix, escape="\\"),
        Span.output_digest.like(prefix, escape="\\"),
        Span.span_id.like(f"{_like(hexpart)}%", escape="\\"),
        Span.attrs.like(f'%"nv.transaction_digest":"{prefix}', escape="\\"),
    )).order_by(Span.id.desc()).limit(limit)).all()
    transactions = session.scalars(select(Event).where(
        Event.type == "http_request",
        Event.payload.like(f'%"transaction_digest": "{prefix}', escape="\\"),
    ).order_by(Event.id.desc()).limit(limit)).all()
    findings = session.scalars(select(Event).where(
        Event.type == "finding",
        Event.payload.like(f"%{_like(hexpart)}%", escape="\\"),
    ).order_by(Event.id.desc()).limit(limit)).all()
    arenas = session.scalars(select(Deployment).where(
        Deployment.id.like(f"{_like(hexpart)}%", escape="\\")).limit(limit)).all()
    return {"arenas": [_arena(row) for row in arenas],
            "findings": [_finding(row) for row in findings],
            "transactions": [_transaction(row) for row in transactions],
            "spans": [_span(row) for row in spans]}


def _arena(row) -> dict:
    return {"id": row.id, "scenario": row.scenario, "status": row.status}


def _finding(row) -> dict:
    data = _payload(row)
    return {"arena_id": row.lab_id, "finding_id": data.get("finding_id"),
            "title": str(data.get("title") or "")[:200], "at": str(row.ts)}


def _transaction(row) -> dict:
    data = _payload(row)
    return {"arena_id": row.lab_id, "digest": data.get("transaction_digest"),
            "method": data.get("method"), "path": str(data.get("path") or "")[:300],
            "status": data.get("status"), "at": str(row.ts)}


def _span(row) -> dict:
    return {"arena_id": row.arena_id, "span_id": row.span_id, "name": row.name,
            "kind": row.kind, "status": row.status, "actor": row.actor,
            "at": str(row.started_at)}
