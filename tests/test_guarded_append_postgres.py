"""
Issue #13: PostgreSQL concurrency gate for ``Database.guarded_append``.

The research integrity layer (R1–R4) makes check-then-append decisions under
``guarded_append``: a PostgreSQL advisory transaction lock per key, or SQLite's
single writer lock. The SQLite suite cannot show that competing PostgreSQL
transactions really serialise, so these tests run only in the PostgreSQL gate
(CI "Tests on PostgreSQL" and ``make release-check``), like the NV-04/NV-05
race tests.
"""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL advisory-lock race")

WORKERS = 8
TYPE = "guarded_append_probe"
# Widens the gap between a decision's read and its append, so an unserialised
# writer loses the race deterministically instead of by chance.
WINDOW = 0.05


def _slow(fn):
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        time.sleep(WINDOW)
        return result
    return wrapper


def _db():
    from database import Database
    return Database()


def _arena():
    from tests.research_support import active_arena
    return active_arena()


def _claim_once(db, arena, key, barrier):
    """Append one claim event only if none exists: the decision under test."""
    def decide(read):
        seen = read(lab_id=arena, types=(TYPE,))
        time.sleep(WINDOW)
        if seen:
            return [], False
        return [(arena, "race", TYPE, {"claimed_by": uuid.uuid4().hex})], True

    barrier.wait(5)
    return db.guarded_append(key, decide)


def test_competing_check_then_append_has_one_winner():
    db, arena = _db(), _arena()
    barrier = Barrier(WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(
            lambda _: _claim_once(db, arena, f"race\x1f{arena}", barrier), range(WORKERS)))
    assert results.count(True) == 1
    assert len(db.list_events(arena, limit=None, types=(TYPE,))) == 1


def test_a_waiter_sees_the_winners_write():
    db, arena = _db(), _arena()
    key = f"race\x1f{arena}"
    entered, release = Event(), Event()

    def holder(read):
        entered.set()
        assert release.wait(5)
        return [(arena, "holder", TYPE, {"n": 1})], None

    def waiter(read):
        return [], len(read(lab_id=arena, types=(TYPE,)))

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(db.guarded_append, key, holder)
        assert entered.wait(5)
        waited = pool.submit(db.guarded_append, key, waiter)
        time.sleep(0.2)
        assert not waited.done(), "a second writer entered while the key was held"
        release.set()
        held.result(5)
        assert waited.result(5) == 1, "the waiter decided on a stale read"


def test_different_keys_do_not_block_each_other():
    db, arena = _db(), _arena()
    entered, release = Event(), Event()

    def holder(read):
        entered.set()
        assert release.wait(5)
        return [], None

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(db.guarded_append, f"a\x1f{arena}", holder)
        assert entered.wait(5)
        other = pool.submit(db.guarded_append, f"b\x1f{arena}", lambda read: ([], "done"))
        try:
            assert other.result(3) == "done"
        finally:
            release.set()
            held.result(5)


def test_an_exception_in_decide_appends_nothing_and_releases_the_key():
    db, arena = _db(), _arena()
    key = f"race\x1f{arena}"

    def fails(read):
        raise RuntimeError("refused")

    with pytest.raises(RuntimeError):
        db.guarded_append(key, fails)
    assert db.list_events(arena, limit=None, types=(TYPE,)) == []
    assert db.guarded_append(key, lambda read: ([], "free")) == "free"


def test_racing_reports_of_one_root_cause_yield_one_independent_finding(monkeypatch):
    import research_integrity
    from tests.research_support import bind, client, research_mode
    from tests.test_r2_fingerprint_dedup import BASE

    # Outcome-level: same-arena finding reports are also serialised earlier in
    # the finding path, so this test holds even without the advisory lock. The
    # lock itself is isolated by the claim, waiter and sweep tests in this file.
    monkeypatch.setattr(research_integrity, "classify", _slow(research_integrity.classify))

    operator, agent = client("operator"), client("agent")
    arena = _arena()
    bind(operator, arena, agent)
    research_mode(operator, arena)
    barrier = Barrier(WORKERS)

    def report(i):
        barrier.wait(5)
        r = agent.post(f"/arenas/{arena}/findings",
                       json={"title": f"race {i}", "root_cause": BASE})
        assert r.status_code in (200, 201), r.text
        return r.json()["finding_id"]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(report, range(WORKERS)))
    relations = [e["payload"]["dedup"]["relation"]
                 for e in _db().list_events(arena, limit=None, types=("finding",))]
    assert sorted(relations) == ["duplicate"] * (WORKERS - 1) + ["independent"]


def test_racing_zero_yield_sweeps_shelve_exactly_once(monkeypatch):
    import research_integrity
    from tests.research_support import bind, client, research_mode

    operator, agent = client("operator"), client("agent")
    arena = _arena()
    bind(operator, arena, agent)
    research_mode(operator, arena)
    surfaces = [f"/s{i}" for i in range(5)]
    first = agent.post(f"/arenas/{arena}/sweeps", json={
        "source": "fix-diff", "surfaces_planned": surfaces, "surfaces_reviewed": surfaces})
    assert first.status_code == 201, first.text
    monkeypatch.setattr(research_integrity, "sweep_payload",
                        _slow(research_integrity.sweep_payload))
    barrier = Barrier(WORKERS)

    def sweep(_):
        barrier.wait(5)
        return agent.post(f"/arenas/{arena}/sweeps", json={"source": "fuzz"})

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        responses = list(pool.map(sweep, range(WORKERS)))
    shelving = [r for r in responses if r.status_code == 201
                and r.json()["shelved_by_this_sweep"]]
    refused = [r for r in responses if r.status_code == 409]
    assert len(shelving) == 1
    assert len(shelving) + len(refused) == WORKERS
    assert all(r.json()["detail"]["code"] == "research_shelved" for r in refused)
    shelved = _db().list_events(arena, limit=None, types=("research_shelved",))
    assert len(shelved) == 1
