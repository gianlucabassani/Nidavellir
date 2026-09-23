"""NV-05 scope, manifest filtering and PostgreSQL lease races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from threading import Event
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import api
import lifecycle_manifest
from auth import generate_api_key, hash_api_key
from database import Database
from scenario_spec import ScenarioSpec, normalized_nodes


SCENARIO = {
    "schema": "nidavellir/v3", "name": "nv05-scope",
    "requires": {"provider_class": "container"},
    "network": {"segments": [
        {"name": "research", "cidr": "10.31.1.0/24"},
        {"name": "private", "cidr": "10.31.2.0/24"},
    ]},
    "nodes": [
        {"name": "jump", "role": "attacker", "image": "alpine:3.21",
         "entrypoint": True, "segments": ["research"]},
        {"name": "fixture", "role": "victim", "image": "alpine:3.21",
         "segments": ["research", "private"], "ports": [],
         "forward_services": [{"id": "internal", "port": 8123}]},
        {"name": "peer", "role": "victim", "image": "alpine:3.21",
         "segments": ["private"],
         "forward_services": [{"id": "peer", "port": 8124}]},
    ],
}


def _client(role, name):
    key = generate_api_key()
    Database().create_api_key(hash_api_key(key), name, role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    return client


def _arena():
    arena_id = str(uuid.uuid4())
    db = Database()
    db.create_deployment(arena_id, arena_id, "custom", provider="docker-local",
                         effective_provider="docker-local",
                         expires_at=datetime.now() + timedelta(hours=1))
    db.update_deployment(arena_id, status="deploying")
    db.update_deployment(arena_id, status="active", outputs={
        "node_jump_state": "running", "node_fixture_state": "running",
        "node_peer_state": "running",
    })
    db.save_lifecycle_recipe(arena_id, lifecycle_manifest.build_recipe(
        scenario=SCENARIO, scenario_name="custom", requested_provider="docker-local",
        effective_provider="docker-local"))
    return arena_id


def _request(**changes):
    return {"foothold": "jump", "target": "fixture", "service_id": "internal",
            "lifetime_seconds": 30, "idempotency_key": uuid.uuid4().hex, **changes}


def test_declared_service_is_preserved_in_recipe_and_normalization():
    spec = ScenarioSpec.from_raw(SCENARIO)
    assert spec.nodes[1].forward_services[0].port == 8123
    assert normalized_nodes(SCENARIO)[1]["forward_services"] == [
        {"id": "internal", "port": 8123}]
    recipe = lifecycle_manifest.build_recipe(
        scenario=SCENARIO, scenario_name="custom", requested_provider=None,
        effective_provider="docker-local")
    assert recipe["nodes"][1]["forward_services"][0]["id"] == "internal"
    bad = {**SCENARIO, "nodes": [{**SCENARIO["nodes"][1],
           "forward_services": [{"id": "internal", "port": 0}]}]}
    with pytest.raises(ValueError):
        ScenarioSpec.from_raw(bad)


def test_manifest_and_direct_rest_scope():
    arena = _arena()
    operator = _client("operator", f"op-{uuid.uuid4().hex[:8]}")
    agent_name = f"agent-{uuid.uuid4().hex[:8]}"
    agent = _client("agent", agent_name)
    outsider = _client("agent", f"other-{uuid.uuid4().hex[:8]}")
    assert outsider.get(f"/arenas/{arena}/capabilities").status_code == 403
    operator.post(f"/arenas/{arena}/bindings", json={
        "agent_name": agent_name, "stance": "defender"})
    denied = agent.get(f"/arenas/{arena}/capabilities").json()
    assert denied["operations"]["forward"]["state"] == "unavailable"
    assert all(not target["forward_services"] for target in denied["targets"])
    assert agent.post(f"/arenas/{arena}/forwards", json=_request()).status_code == 403
    operator.post(f"/arenas/{arena}/bindings", json={
        "agent_name": agent_name, "stance": "attacker"})
    manifest = agent.get(f"/arenas/{arena}/capabilities").json()
    assert manifest["schema"] == "nidavellir.runtime-capabilities.v1"
    assert manifest["operations"]["forward"]["state"] == "ready"
    assert manifest["targets"][0]["forward_services"] == ["internal"]
    assert manifest["targets"][1]["forward_services"] == []
    assert "vulnerabilities" not in str(manifest)
    for changes in ({"target": "peer", "service_id": "peer"},
                    {"target": "fixture", "service_id": "other"},
                    {"port": 8123}, {"host": "127.0.0.1"}):
        assert agent.post(f"/arenas/{arena}/forwards", json=_request(**changes)).status_code == 422
    request = _request()
    opened = agent.post(f"/arenas/{arena}/forwards", json=request)
    assert opened.status_code == 200, opened.text
    lease = opened.json()
    assert lease["service_id"] == "internal" and "binding_generation" not in lease
    assert agent.post(f"/arenas/{arena}/forwards", json=request).json()["id"] == lease["id"]
    assert outsider.get(f"/arenas/{arena}/forwards/{lease['id']}").status_code == 404
    assert agent.post(f"/arenas/{arena}/forwards/{lease['id']}/revoke").status_code == 200
    assert agent.get(f"/arenas/{arena}/forwards/{lease['id']}").json()["state"] == "revoked"


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"),
                    reason="PostgreSQL row-lock race")
def test_postgres_competing_create_claim_stop_and_revoke():
    arena = _arena()
    db = Database()
    key = uuid.uuid4().hex

    def create():
        return db.create_forward_lease(
            arena, principal="operator", role="operator", binding_generation=None,
            key=key, digest="same", foothold="jump", target="fixture",
            service_id="internal", segment="research", port=8123,
            lifetime_seconds=30)

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: create(), range(8)))
    assert len({row["id"] for row in rows}) == 1
    lease_id = rows[0]["id"]
    with pytest.raises(ValueError):
        db.create_forward_lease(
            arena, principal="operator", role="operator", binding_generation=None,
            key=key, digest="changed", foothold="jump", target="fixture",
            service_id="internal", segment="research", port=8123,
            lifetime_seconds=30)

    def claim():
        try:
            return db.claim_forward_stream(
                lease_id, principal="operator", binding_generation=None)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: claim(), range(8)))
    assert sum(row is not None for row in claimed) == 1
    assert db.claim_forward_worker(lease_id, "worker-1")
    assert not db.claim_forward_worker(lease_id, "worker-2")
    entered, release = Event(), Event()

    def helper_start():
        with db.forward_start_guard(lease_id):
            entered.set()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        helper = pool.submit(helper_start)
        assert entered.wait(5)
        stop = pool.submit(db.stop_budget_gate, arena, actor="operator", reason="race")
        time.sleep(.1)
        assert not stop.done(), "stop committed across an in-progress helper start"
        release.set()
        helper.result()
        stop.result()
    with pytest.raises(ValueError):
        with db.forward_start_guard(lease_id):
            pass
    db.revoke_forward_lease(lease_id, actor="operator")
    assert not db.forward_stream_valid(lease_id)


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"),
                    reason="PostgreSQL revoke/connect race")
def test_postgres_revoke_races_connect_and_never_reopens():
    arena = _arena()
    db = Database()
    lease = db.create_forward_lease(
        arena, principal="operator", role="operator", binding_generation=None,
        key=uuid.uuid4().hex, digest="same", foothold="jump", target="fixture",
        service_id="internal", segment="research", port=8123,
        lifetime_seconds=30)

    def claim():
        try:
            return db.claim_forward_stream(
                lease["id"], principal="operator", binding_generation=None)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        claim_future = pool.submit(claim)
        revoke_future = pool.submit(db.revoke_forward_lease, lease["id"], actor="operator")
        claim_future.result()
        revoke_future.result()
    current = db.get_forward_lease(lease["id"])
    assert current["state"] == "revoked"
    assert not db.forward_stream_valid(lease["id"])
    with pytest.raises(ValueError):
        db.claim_forward_stream(lease["id"], principal="operator", binding_generation=None)
