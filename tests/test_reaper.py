"""
Lifecycle reaper tests (P2-3 / audit #9).

Covers `Database.find_reapable` (which labs get reaped and why) and the
`reap_labs` Celery task (transition → event → enqueue destroy), without Redis.
"""
import uuid
from datetime import datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy")

from database import Database  # noqa: E402


def _now():
    return datetime.now()


def _lab(db, status_chain=(), expires_at=None):
    """Create a lab and walk it through `status_chain` via legal transitions."""
    lab_id = str(uuid.uuid4())
    db.create_deployment(lab_id, "reaper-test", "basic_pentest", expires_at=expires_at)
    for step in status_chain:
        db.update_deployment(lab_id, status=step)
    return lab_id


def _force_updated_at(db, lab_id, when):
    """Backdate updated_at to simulate a lab that's been stuck a while."""
    from models import Deployment

    with db._session() as session:
        dep = session.get(Deployment, lab_id)
        dep.updated_at = when
        session.commit()


# --- find_reapable -----------------------------------------------------------

def test_expired_active_lab_is_reapable():
    db = Database()
    now = _now()
    lab_id = _lab(db, ("deploying", "active"), expires_at=now - timedelta(minutes=1))

    reapable = {r["id"]: r for r in db.find_reapable(now, now - timedelta(minutes=30))}
    assert lab_id in reapable
    assert reapable[lab_id]["reason"] == "expired"


def test_unexpired_active_lab_is_not_reapable():
    db = Database()
    now = _now()
    lab_id = _lab(db, ("deploying", "active"), expires_at=now + timedelta(hours=2))

    ids = {r["id"] for r in db.find_reapable(now, now - timedelta(minutes=30))}
    assert lab_id not in ids


def test_null_expiry_active_lab_is_not_expiry_reaped():
    """A live lab with no TTL must never be auto-destroyed on the expiry path."""
    db = Database()
    now = _now()
    lab_id = _lab(db, ("deploying", "active"), expires_at=None)

    ids = {r["id"] for r in db.find_reapable(now, now - timedelta(minutes=30))}
    assert lab_id not in ids


def test_stuck_pending_lab_is_reapable():
    """The 'stuck pending forever' failure: a lab whose worker was lost."""
    db = Database()
    now = _now()
    lab_id = _lab(db, expires_at=now + timedelta(hours=2))  # stays pending
    _force_updated_at(db, lab_id, now - timedelta(minutes=45))

    reapable = {r["id"]: r for r in db.find_reapable(now, now - timedelta(minutes=30))}
    assert lab_id in reapable
    assert reapable[lab_id]["reason"] == "stuck"


def test_fresh_pending_lab_is_not_stuck():
    db = Database()
    now = _now()
    lab_id = _lab(db, expires_at=now + timedelta(hours=2))  # just created, fresh
    ids = {r["id"] for r in db.find_reapable(now, now - timedelta(minutes=30))}
    assert lab_id not in ids


def test_stuck_destroying_lab_is_reapable():
    db = Database()
    now = _now()
    lab_id = _lab(db, ("destroying",), expires_at=now + timedelta(hours=2))
    _force_updated_at(db, lab_id, now - timedelta(minutes=45))

    reapable = {r["id"]: r for r in db.find_reapable(now, now - timedelta(minutes=30))}
    assert lab_id in reapable
    assert reapable[lab_id]["reason"] == "stuck"


def test_terminal_labs_are_never_reapable():
    db = Database()
    now = _now()
    destroyed = _lab(db, ("destroying", "destroyed"), expires_at=now - timedelta(days=1))
    failed = _lab(db, ("failed",), expires_at=now - timedelta(days=1))
    _force_updated_at(db, destroyed, now - timedelta(days=1))
    _force_updated_at(db, failed, now - timedelta(days=1))

    ids = {r["id"] for r in db.find_reapable(now, now - timedelta(minutes=30))}
    assert destroyed not in ids
    assert failed not in ids


# --- reap_labs task ----------------------------------------------------------

class _FakeDestroy:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_reap_labs_transitions_records_and_enqueues(monkeypatch):
    import tasks

    fake = _FakeDestroy()
    monkeypatch.setattr(tasks, "destroy_lab", fake)

    db = Database()
    now = _now()
    expired = _lab(db, ("deploying", "active"), expires_at=now - timedelta(minutes=1))
    stuck = _lab(db, expires_at=now + timedelta(hours=2))
    _force_updated_at(db, stuck, now - timedelta(hours=1))
    healthy = _lab(db, ("deploying", "active"), expires_at=now + timedelta(hours=2))

    result = tasks.reap_labs()

    assert result["reaped"] >= 2
    enqueued = {args[0] for args, _ in fake.calls}
    assert {expired, stuck} <= enqueued
    assert healthy not in enqueued

    # Both reaped labs moved to destroying and carry a 'reaped' event w/ reason
    assert db.get_deployment(expired)["status"] == "destroying"
    assert db.get_deployment(stuck)["status"] == "destroying"
    assert db.get_deployment(healthy)["status"] == "active"

    expired_events = [e for e in db.list_events(lab_id=expired) if e["type"] == "reaped"]
    assert expired_events and expired_events[0]["payload"]["reason"] == "expired"
    assert expired_events[0]["actor"] == "reaper"
    stuck_events = [e for e in db.list_events(lab_id=stuck) if e["type"] == "reaped"]
    assert stuck_events and stuck_events[0]["payload"]["reason"] == "stuck"


def test_reap_labs_is_a_noop_when_nothing_is_reapable(monkeypatch):
    import tasks

    fake = _FakeDestroy()
    monkeypatch.setattr(tasks, "destroy_lab", fake)

    db = Database()
    now = _now()
    _lab(db, ("deploying", "active"), expires_at=now + timedelta(hours=2))  # healthy

    before = len(fake.calls)
    tasks.reap_labs()
    assert len(fake.calls) == before  # nothing enqueued for healthy labs
