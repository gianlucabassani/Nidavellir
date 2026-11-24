"""OBS-04: a real push stream for arena events and spans.

Publishing: after a database commit that inserted audit events or spans, one
small message per row goes to the Redis channel ``nv:arena:<id>``:
``{"kind": "event"|"span", "id": n}``. It is hooked on SQLAlchemy's session
lifecycle, so every writer (API, worker, reaper) publishes without changes, and
it is best-effort: a Redis failure never fails the write.

Streaming: :func:`arena_frames` yields server-sent events. It replays from a
``Last-Event-ID`` cursor (``"<event id>.<span id>"``), then waits on the channel
and reads the database only when a message arrives. Without Redis (SQLite dev)
it falls back to polling behind the same endpoint. Comment keepalives are not
polls.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Iterator

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

CHANNEL = "nv:arena:{}"
KEEPALIVE_SECONDS = float(os.getenv("NIDAVELLIR_STREAM_KEEPALIVE_SECONDS", "15"))
MAX_SECONDS = float(os.getenv("NIDAVELLIR_STREAM_MAX_SECONDS", "1800"))
FALLBACK_POLL_SECONDS = float(os.getenv("NIDAVELLIR_STREAM_FALLBACK_POLL_SECONDS", "2"))
BACKFILL_EVENTS = 40
BACKFILL_SPANS = 200
BATCH = 500

_client = None
_client_failed_at = 0.0


def _redis():
    """A lazily created Redis client, or None (retried at most every 30 s)."""
    global _client, _client_failed_at
    if _client is not None:
        return _client
    if time.monotonic() - _client_failed_at < 30:
        return None
    try:
        import readiness  # noqa: PLC0415 - shares the broker URL and timeouts

        client = readiness.redis_client()
        client.ping()
        _client = client
    except Exception:  # noqa: BLE001 - streaming degrades to polling
        _client_failed_at = time.monotonic()
        return None
    return _client


def publish(messages: list[tuple[str, str, int]]) -> None:
    """Publish (arena_id, kind, id) messages; never raises."""
    if not messages:
        return
    client = _redis()
    if client is None:
        return
    try:
        for arena_id, kind, row_id in messages:
            client.publish(CHANNEL.format(arena_id),
                           json.dumps({"kind": kind, "id": row_id}))
    except Exception:  # noqa: BLE001
        logger.warning("stream publish failed", exc_info=True)


def install() -> None:
    """Publish inserted events and spans after their transaction commits."""
    if getattr(install, "done", False):
        return
    install.done = True
    from models import Event, Span  # noqa: PLC0415

    @sa_event.listens_for(Session, "after_flush")
    def _collect(session, _context):
        pending = session.info.setdefault("nv_stream", [])
        for obj in session.new:
            if isinstance(obj, Event):
                pending.append((obj.lab_id, "event", obj))
            elif isinstance(obj, Span) and obj.arena_id:
                pending.append((obj.arena_id, "span", obj))

    @sa_event.listens_for(Session, "after_commit")
    def _publish(session):
        pending = session.info.pop("nv_stream", [])
        publish([(arena, kind, obj.id) for arena, kind, obj in pending
                 if getattr(obj, "id", None) is not None])

    @sa_event.listens_for(Session, "after_rollback")
    def _drop(session):
        session.info.pop("nv_stream", None)


def parse_cursor(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        event_id, _, span_id = value.partition(".")
        return max(0, int(event_id)), max(0, int(span_id or 0))
    except ValueError:
        return None


def sse(name: str, payload, event_id: str | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {name}\ndata: {json.dumps(payload, default=str)}\n\n"


def arena_frames(*, arena_id: str, cursor: tuple[int, int] | None,
                 read_events: Callable[[int, int], list[dict]],
                 read_spans: Callable[[int, int], list[dict]],
                 read_state: Callable[[], dict | None],
                 latest: Callable[[], tuple[int, int]],
                 subscribe: Callable[[str], object | None] | None = None,
                 max_seconds: float | None = None) -> Iterator[str]:
    """Server-sent frames for one arena: ``state``, ``activity`` and ``spans``.

    ``read_events(after, limit)`` / ``read_spans(after, limit)`` return rows
    oldest-first that the caller is allowed to see; ``read_state`` the arena's
    current ``{status, outputs}`` or None when it is gone."""
    deadline = time.monotonic() + (MAX_SECONDS if max_seconds is None else max_seconds)
    pubsub = subscribe(arena_id) if subscribe else None
    try:
        yield "retry: 3000\n\n"
        state = read_state()
        if state is None:
            return
        yield sse("state", state)
        if cursor is None:
            newest_event, newest_span = latest()
            cursor = (max(0, newest_event - BACKFILL_EVENTS),
                      max(0, newest_span - BACKFILL_SPANS))
        event_cursor, span_cursor = cursor
        changed = True
        while True:
            if not changed:
                if time.monotonic() >= deadline:
                    return
                yield ": keepalive\n\n"
                changed = _wait(pubsub, deadline)
                continue
            # Drain everything after the cursor; the cursor only moves forward.
            status_changed = False
            while True:
                events = read_events(event_cursor, BATCH)
                rows = read_spans(span_cursor, BATCH)
                if not events and not rows:
                    break
                if events:
                    event_cursor = events[-1]["id"]
                    status_changed |= any(e.get("type") == "status" for e in events)
                    yield sse("activity", {"events": events},
                              event_id=f"{event_cursor}.{span_cursor}")
                if rows:
                    span_cursor = rows[-1]["id"]
                    yield sse("spans", {"spans": rows},
                              event_id=f"{event_cursor}.{span_cursor}")
            if status_changed:
                state = read_state()
                if state is None:
                    return
                yield sse("state", state)
            if time.monotonic() >= deadline:
                return
            changed = _wait(pubsub, deadline)
    finally:
        if pubsub is not None:
            try:
                pubsub.close()
            except Exception:  # noqa: BLE001 - a dead connection needs no closing
                logger.debug("pubsub close failed", exc_info=True)


def _wait(pubsub, deadline: float) -> bool:
    """Block until a message (True) or a keepalive tick (False). Without a
    subscription, sleep the fallback interval and report a change to re-read."""
    timeout = max(0.0, min(KEEPALIVE_SECONDS, deadline - time.monotonic()))
    if pubsub is None:
        time.sleep(min(FALLBACK_POLL_SECONDS, timeout))
        return True
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            message = pubsub.get_message(ignore_subscribe_messages=True,
                                         timeout=max(0.0, end - time.monotonic()))
        except Exception:  # noqa: BLE001 - lost Redis: re-read, then poll
            return True
        if message is not None:
            return True
    return False


def redis_subscribe(arena_id: str):
    client = _redis()
    if client is None:
        return None
    try:
        pubsub = client.pubsub()
        pubsub.subscribe(CHANNEL.format(arena_id))
        return pubsub
    except Exception:  # noqa: BLE001
        return None
