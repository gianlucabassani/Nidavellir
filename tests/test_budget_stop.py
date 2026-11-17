"""NV-04 durable budget and stop admission invariants."""
import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from database import Database
import poc_execution


def _arena(db):
    arena = str(uuid.uuid4())
    db.create_deployment(arena, arena, "custom", expires_at=datetime.now() + timedelta(hours=1))
    db.update_deployment(arena, status="deploying")
    db.update_deployment(arena, status="active")
    return arena


def _reserve(db, arena, key):
    return db.reserve_budget_action(
        arena, key=key, digest=hashlib.sha256(key.encode()).hexdigest(),
        kind="exec", actor="researcher",
    )[0]


def test_reconnect_and_reset_share_spent_budget():
    db = Database()
    source = _arena(db)
    status = db.budget_status(source)
    db.revise_budget_policy(
        source, action_cap=1,
        deadline=datetime.now() + timedelta(minutes=30),
        actor="operator", reason="one action test",
    )
    action = _reserve(db, source, "first-action")
    assert db.settle_budget_action(action, outcome="spent")
    assert db.budget_status(source)["policy"]["remaining"] == 0
    with pytest.raises(ValueError, match="exhausted"):
        _reserve(db, source, "second-action")
    replacement = _arena(db)
    db.inherit_budget_scope(source, replacement)
    assert db.budget_status(replacement)["policy"]["remaining"] == 0
    assert status["policy"]["remaining"] > 0


def test_competing_reservations_never_overcommit():
    db = Database()
    arena = _arena(db)
    db.revise_budget_policy(
        arena, action_cap=1,
        deadline=datetime.now() + timedelta(minutes=30),
        actor="operator", reason="one slot race",
    )

    def attempt(key):
        try:
            return _reserve(db, arena, key)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = list(pool.map(attempt, ["race-one", "race-two"]))
    assert len([action for action in admitted if action]) == 1
    policy = db.budget_status(arena)["policy"]
    assert policy["spent"] + policy["reserved"] == 1


def test_stop_blocks_admission_and_queued_job_claim():
    db = Database()
    arena = _arena(db)
    epoch = db.stop_budget_gate(arena, actor="operator", reason="stop test",
                                key="stop-key-0001")
    assert epoch == 1
    assert db.stop_budget_gate(arena, actor="operator", reason="stop test",
                               key="stop-key-0001") == epoch
    with pytest.raises(ValueError, match="different input"):
        db.stop_budget_gate(arena, actor="operator", reason="changed",
                            key="stop-key-0001")
    with pytest.raises(ValueError, match="stopped"):
        _reserve(db, arena, "after-stop")
    assert db.reconcile_budget_stop(arena)
    assert db.budget_status(arena)["arena"]["state"] == "stopped"
    db.resume_budget_gate(arena, actor="operator", reason="verified clear",
                          key="clear-key-0001")
    assert db.budget_status(arena)["arena"]["epoch"] == 2
    assert _reserve(db, arena, "after-resume")


def test_queued_poc_refunds_and_claimed_poc_spends():
    db = Database()
    arena = _arena(db)
    db.revise_budget_policy(
        arena, action_cap=1, deadline=datetime.now() + timedelta(minutes=30),
        actor="operator", reason="PoC settlement test",
    )
    payload, digest = poc_execution.canonical_payload("print('proof')\n", [])

    def create(key):
        return db.create_poc_job(
            job_id=str(uuid.uuid4()), arena_id=arena, principal="operator",
            principal_role="operator", binding_stance=None,
            idempotency_key=key, input_digest=digest, payload=payload,
            runner_image="runner@test", target_node=None, target_policy=None,
            limits={"timeout_seconds": 5}, deadline=datetime.now() + timedelta(minutes=1),
            max_arena_jobs=2, max_global_jobs=8,
        )[0]

    queued = create("cancel-before-run")
    assert db.budget_status(arena)["policy"]["reserved"] == 1
    with pytest.raises(ValueError, match="exhausted"):
        create("cannot-overbook")
    assert db.request_cancel_poc_job(queued["id"])["state"] == "cancelled"
    assert db.budget_status(arena)["policy"]["remaining"] == 1
    running = create("execute-proof")
    assert db.claim_poc_job(running["id"], "worker")
    db.finish_poc_job(running["id"], state="succeeded", result={"success": True})
    assert db.budget_status(arena)["policy"]["spent"] == 1


def test_setup_step_limit_serializes_competing_requests():
    db = Database()
    arena = _arena(db)
    db.record_event(arena, "setup_session", {
        "session_id": str(uuid.uuid4()), "command_budget": 1,
        "started_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(minutes=10)).isoformat(),
        "nodes": ["target"],
    }, actor="operator")

    def attempt(key):
        try:
            return db.reserve_budget_action(
                arena, key=key, digest=key, kind="setup/step", actor="operator",
            )[0]
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = list(pool.map(attempt, ["setup-race-1", "setup-race-2"]))
    assert len([action for action in admitted if action]) == 1


def test_repeated_stop_cancel_does_not_keep_dead_worker_claim_fresh():
    db = Database()
    arena = _arena(db)
    payload, digest = poc_execution.canonical_payload("while True: pass\n", [])
    job, _ = db.create_poc_job(
        job_id=str(uuid.uuid4()), arena_id=arena, principal="operator",
        principal_role="operator", binding_stance=None,
        idempotency_key=f"stale-{uuid.uuid4().hex}", input_digest=digest,
        payload=payload, runner_image="runner@test", target_node=None,
        target_policy=None, limits={"timeout_seconds": 5},
        deadline=datetime.now() + timedelta(minutes=1),
        max_arena_jobs=2, max_global_jobs=8,
    )
    assert db.claim_poc_job(job["id"], "dead-worker")
    first = db.request_cancel_poc_job(job["id"])
    second = db.request_cancel_poc_job(job["id"])
    assert second["updated_at"] == first["updated_at"]
    recovered = db.recover_stale_poc_jobs(datetime.now() + timedelta(seconds=1))
    assert job["id"] in recovered
    assert db.budget_status(arena)["policy"]["spent"] == 1


def test_stop_waits_for_slow_helper_create_guard():
    db = Database()
    arena = _arena(db)
    payload, digest = poc_execution.canonical_payload("print('guard')\n", [])
    job, _ = db.create_poc_job(
        job_id=str(uuid.uuid4()), arena_id=arena, principal="operator",
        principal_role="operator", binding_stance=None,
        idempotency_key=f"guard-{uuid.uuid4().hex}", input_digest=digest,
        payload=payload, runner_image="runner@test", target_node=None,
        target_policy=None, limits={"timeout_seconds": 5},
        deadline=datetime.now() + timedelta(minutes=1),
        max_arena_jobs=2, max_global_jobs=8,
    )
    assert db.claim_poc_job(job["id"], "worker")
    entered, release = threading.Event(), threading.Event()

    def slow_create():
        with db.helper_start_guard(arena, job["id"]):
            entered.set()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        helper = pool.submit(slow_create)
        assert entered.wait(5)
        stop = pool.submit(db.stop_budget_gate, arena, actor="operator",
                           reason="slow create race")
        time.sleep(.1)
        assert not stop.done()
        release.set()
        helper.result()
        assert stop.result() == 1
    with pytest.raises(ValueError, match="stopped"):
        with db.helper_start_guard(arena, job["id"]):
            pass
    db.request_cancel_poc_job(job["id"])
    db.finish_poc_job(job["id"], state="cancelled", cleanup_state="not_started")


def test_postgres_stop_races_admission():
    db = Database()
    if db._engine.dialect.name != "postgresql":
        pytest.skip("requires real PostgreSQL row locking")
    arena = _arena(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reserved = pool.submit(lambda: _reserve(db, arena, "postgres-race"))
        stopped = pool.submit(lambda: db.stop_budget_gate(
            arena, actor="operator", reason="PostgreSQL stop race"))
        try:
            action = reserved.result()
        except ValueError:
            action = None
        stopped.result()
    assert db.budget_status(arena)["arena"]["state"] == "stopping"
    with pytest.raises(ValueError, match="stopped"):
        _reserve(db, arena, "postgres-late")
    if action:
        db.settle_budget_action(action, outcome="unknown")
    assert db.reconcile_budget_stop(arena)
