"""NV-02 immutable recipe, durable claim and replacement-reset behavior."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import lifecycle_manifest
import pytest
from database import Database
from models import ResetOperation
from states import LabStatus


def _scenario(image="example/reset@sha256:" + "a" * 64, seed_value=0):
    return {
        "schema": "nidavellir/v3",
        "name": "reset-fixture",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{
            "name": "target", "role": "victim", "image": image,
            "segments": ["lab"], "ports": [8080],
        }],
        "lifecycle": {
            "seed": {"schema": "fixture/v1", "value": seed_value},
            "readiness": {
                "type": "http", "node": "target", "port": 8080,
                "path": "/state", "expected_status": 200,
                "expected_state": {"seed": "baseline", "value": seed_value},
            },
        },
    }


def _recipe(scenario=None):
    scenario = scenario or _scenario()
    lifecycle = scenario["lifecycle"]
    return lifecycle_manifest.build_recipe(
        scenario=scenario,
        scenario_name="reset-fixture",
        requested_provider="docker-local",
        effective_provider="docker-local",
        expires_at=(datetime.now() + timedelta(hours=1)).isoformat(),
        readiness=lifecycle["readiness"],
        seed=lifecycle["seed"],
    )


def test_recipe_digest_ignores_runtime_ids_but_changes_with_seed_or_image():
    first = _recipe()
    second = _recipe()
    assert first["equivalence_digest"] == second["equivalence_digest"]
    assert first["runtime_reset"]["status"] == "eligible"
    assert _recipe(_scenario(seed_value=1))["equivalence_digest"] != first["equivalence_digest"]
    assert _recipe(_scenario(image="example/reset@sha256:" + "b" * 64))[
        "equivalence_digest"
    ] != first["equivalence_digest"]
    changed_platform = _scenario()
    changed_platform["nodes"][0]["platform"] = "linux/arm64"
    assert _recipe(changed_platform)["equivalence_digest"] != first["equivalence_digest"]


def test_public_recipe_redacts_seed_environment_commands_and_authorization_notes():
    scenario = _scenario()
    scenario["nodes"][0]["environment"] = {"APP_SECRET": "do-not-publish"}
    scenario["nodes"][0]["command"] = "server --token do-not-publish"
    recipe = lifecycle_manifest.build_recipe(
        scenario=scenario, scenario_name="redaction", requested_provider="docker-local",
        effective_provider="docker-local", readiness=scenario["lifecycle"]["readiness"],
        seed={"secret_seed": "do-not-publish"},
        target_manifest={
            "kind": "oci", "identity": {"digest": "sha256:" + "c" * 64},
            "reset": {"immutable_source": True},
            "authorization": {
                "confirmed": True, "basis": "owned", "scope_note": "do-not-publish",
                "confirmed_by": "private-operator",
            },
        },
    )
    public = lifecycle_manifest.public_recipe(recipe)
    serialized = lifecycle_manifest.canonical_json(public)
    assert b"do-not-publish" not in serialized
    assert b"private-operator" not in serialized
    assert public["nodes"][0]["environment_keys"] == ["APP_SECRET"]
    assert "expected_state" not in public["readiness"]


def test_mutable_or_manual_inputs_are_honestly_not_reset_eligible():
    mutable = _scenario(image="example/reset:latest")
    recipe = lifecycle_manifest.build_recipe(
        scenario=mutable,
        scenario_name="mutable",
        requested_provider="docker-local",
        effective_provider="docker-local",
        readiness=mutable["lifecycle"]["readiness"],
        setup={"open_setup": True},
    )
    assert recipe["build_reproducibility"]["status"] == "unverified"
    assert recipe["runtime_reset"] == {
        "status": "unsupported", "reason": "manual_setup_has_no_replayable_baseline"
    }


def test_reset_operation_is_idempotent_and_exclusive():
    db = Database()
    deadline = datetime.now() + timedelta(minutes=5)
    first, created = db.create_reset_operation(
        operation_id="op-1", source_id="source", replacement_id="replacement-1",
        idempotency_key="same-key", recipe_digest="sha256:abc", deadline=deadline,
    )
    assert created is True
    replay, created = db.create_reset_operation(
        operation_id="op-2", source_id="source", replacement_id="replacement-2",
        idempotency_key="same-key", recipe_digest="sha256:abc", deadline=deadline,
    )
    assert created is False
    assert replay["id"] == first["id"]

    try:
        db.create_reset_operation(
            operation_id="op-3", source_id="source", replacement_id="replacement-3",
            idempotency_key="different-key", recipe_digest="sha256:abc", deadline=deadline,
        )
    except ValueError as exc:
        assert "already in flight" in str(exc)
    else:
        raise AssertionError("a second in-flight reset must be rejected atomically")
    db.update_reset_operation(first["id"], status="failed", terminal=True)


def test_reset_delivery_has_one_atomic_claim_and_stale_claim_is_recoverable():
    db = Database()
    operation, _ = db.create_reset_operation(
        operation_id="claim-op", source_id="claim-source", replacement_id="claim-replacement",
        idempotency_key="claim-key", recipe_digest="sha256:abc",
        deadline=datetime.now() + timedelta(minutes=5),
    )
    assert db.claim_reset_operation(operation["id"]) is True
    assert db.claim_reset_operation(operation["id"]) is False

    with db._session() as session:
        row = session.get(ResetOperation, operation["id"])
        row.updated_at = datetime.now() - timedelta(hours=1)
        session.commit()
    assert db.recover_stale_reset_operations(datetime.now() - timedelta(minutes=30)) == [
        operation["id"]
    ]
    assert db.get_reset_operation(operation["id"])["status"] == "pending"
    assert db.claim_reset_operation(operation["id"]) is True
    db.update_reset_operation(operation["id"], status="failed", terminal=True)


def test_postgres_competing_reset_transactions_have_one_winner():
    db = Database()
    if db._engine.dialect.name != "postgresql":
        pytest.skip("real competing-transaction assertion runs in the PostgreSQL gate")
    barrier = Barrier(2)

    def compete(index):
        barrier.wait()
        try:
            operation, created = db.create_reset_operation(
                operation_id=f"pg-op-{index}", source_id="pg-source",
                replacement_id=f"pg-replacement-{index}", idempotency_key=f"pg-key-{index}",
                recipe_digest="sha256:abc",
                deadline=datetime.now() + timedelta(minutes=5),
            )
            return operation, created
        except ValueError:
            return None, False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (1, 2)))
    winners = [operation for operation, created in results if created]
    assert len(winners) == 1
    db.update_reset_operation(winners[0]["id"], status="failed", terminal=True)


def test_reset_task_replaces_arena_and_preserves_source_record(monkeypatch):
    import tasks

    db = Database()
    recipe = _recipe()
    expires = datetime.now() + timedelta(hours=1)
    db.create_deployment(
        "source-run", "fixture", "reset-fixture", provider="docker-local",
        effective_provider="docker-local", expires_at=expires,
    )
    db.transition_deployment("source-run", (LabStatus.PENDING,), LabStatus.DEPLOYING)
    db.transition_deployment("source-run", (LabStatus.DEPLOYING,), LabStatus.ACTIVE)
    db.save_lifecycle_recipe("source-run", recipe)
    provider_observation = {
        "provider": "docker-local",
        "nodes": [{
            "node": "target", "role": "victim", "image_id": "sha256:" + "a" * 64,
            "os": "linux", "architecture": "amd64", "state": "running",
        }],
    }
    readiness = {
        "ready": True, "status": "passed",
        "state_digest": lifecycle_manifest.digest({"seed": "baseline", "value": 0}),
    }
    baseline = lifecycle_manifest.observation(
        recipe=recipe, provider_observation=provider_observation, readiness_result=readiness
    )
    db.record_event("source-run", "lifecycle_observation", baseline)

    db.create_deployment(
        "replacement", "fixture-reset", "reset-fixture",
        provider="docker-local", effective_provider="docker-local", expires_at=expires,
    )
    db.save_lifecycle_recipe("replacement", recipe)
    db.create_reset_operation(
        operation_id="op", source_id="source-run", replacement_id="replacement",
        idempotency_key="reset-key", recipe_digest=recipe["recipe_digest"],
        deadline=datetime.now() + timedelta(minutes=5),
    )

    class FakeOrchestrator:
        def __init__(self, provider=None, provider_name=None):
            pass

        def destroy(self, instance_id):
            return {"success": True}

        def deploy(self, *args, **kwargs):
            return {"success": True, "outputs": {"node_target_state": "running"}}

        def check_readiness(self, instance_id, outputs, policy):
            return readiness

        def observe_lifecycle(self, instance_id):
            return provider_observation

    monkeypatch.setattr(tasks, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(tasks, "resolve_provider_name", lambda _name=None: "docker-local")
    result = tasks.reset_arena("op")
    assert result["success"] is True
    assert db.get_deployment("source-run")["status"] == LabStatus.DESTROYED
    assert db.get_deployment("replacement")["status"] == LabStatus.ACTIVE
    assert db.get_reset_operation("op")["status"] == "succeeded"
    assert db.list_events("source-run", types=("reset_replaced_by",))
