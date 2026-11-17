"""FR-08 (B9): one source of truth for "now".

Every instant is computed timezone-aware in UTC. The existing database columns are
``DateTime`` without a time zone; migration 0011 records the decision that their
values are **UTC wall-clock** (the services always ran in python:3.11-slim containers
with no ``TZ``, so the old ``datetime.now()`` values were already UTC there). New
writes therefore store the UTC instant with ``tzinfo`` stripped (``db_now``), which
keeps comparisons with values read back from SQLite/PostgreSQL type-compatible and
is unaffected by the host's local time zone or DST transitions.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """The current instant, timezone-aware UTC."""
    return datetime.now(timezone.utc)


def to_db(value: datetime) -> datetime:
    """Normalise an instant for a naive-UTC column.

    Aware values are converted to UTC then made naive; naive values are taken as
    already UTC (the documented column interpretation)."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def db_now() -> datetime:
    """``utcnow()`` for a naive-UTC column."""
    return to_db(utcnow())


def from_db(value: datetime | None) -> datetime | None:
    """Read a naive-UTC column value back as an aware UTC instant."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)
