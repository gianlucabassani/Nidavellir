"""
F4 (work order 2026-11-18): configurator-scoped deploy, opt-in and allowlisted.

An ``agent`` key may ``POST /deploy`` only when the install allowlists the scenario
(empty allowlist = disabled), the runtime kill switch is clear, its current grant
for that scenario is ``configurator`` and its hourly / live quotas hold. Every
admitted deploy is audited with the agent and scenario. An attacker is refused in
every configuration; FR-04's operator-only default is unchanged.
"""
import os
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
import bindings
import config
import database
from auth import generate_api_key, hash_api_key
from database import Database

OPENCMS = "opencms-22-whitebox"
OTHER = "container_web_pentest"


def _client(role):
    name = f"f4-{role}-{uuid.uuid4().hex[:8]}"
    key = generate_api_key()
    Database().create_api_key(hash_api_key(key), name, role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    client.name = name
    return client


_OPENCMS_YAML = Path(__file__).resolve().parent.parent / "scenarios" / f"{OPENCMS}.yaml"


@pytest.fixture()
def env(monkeypatch):
    import scenarios

    # Register the real OpenCMS pack in the hermetic scenario store for this test.
    scenarios.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    installed = scenarios.SCENARIOS_DIR / _OPENCMS_YAML.name
    shutil.copyfile(_OPENCMS_YAML, installed)
    queued = []
    monkeypatch.setattr(api.deploy_lab, "delay", lambda **kw: queued.append(kw))
    monkeypatch.setattr(config, "AGENT_DEPLOY_SCENARIOS", (OPENCMS,))
    monkeypatch.setattr(config, "AGENT_DEPLOY_MAX_PER_HOUR", 3)
    monkeypatch.setattr(config, "AGENT_DEPLOY_MAX_LIVE", 2)
    operator = _client("operator")
    created = []
    yield operator, queued, created
    installed.unlink(missing_ok=True)
    db = Database()
    if (api._agent_deploy_kill_switch() or {}).get("payload", {}).get("engaged"):
        db.record_event("system", database.AGENT_DEPLOY_KILL_EVENT,
                        {"engaged": False, "reason": "test teardown"}, actor="test")
    for dep in db.list_deployments():
        if dep["id"] in created and dep["status"] in ("pending", "active"):
            db.update_deployment(dep["id"], status="destroying")
            db.update_deployment(dep["id"], status="destroyed")


def _seed_arena(operator, created, scenario, agent, stance):
    """An earlier operator-created arena of `scenario` where `agent` holds `stance`."""
    arena = str(uuid.uuid4())
    created.append(arena)
    Database().create_deployment(arena, "f4-seed", scenario, provider="mock")
    assert operator.post(f"/arenas/{arena}/bindings", json={
        "agent_name": agent.name, "stance": stance}).status_code == 200
    return arena


def _deploy(client, created, scenario=OPENCMS):
    response = client.post("/deploy", json={"scenario": scenario,
                                            "instance_id": f"f4-{uuid.uuid4().hex[:6]}"})
    if response.status_code == 200:
        created.append(response.json()["instance_id"])
    return response


def _code(response):
    return response.json()["detail"]["code"]


def test_configurator_deploys_an_allowlisted_scenario(env):
    operator, queued, created = env
    agent = _client("agent")
    _seed_arena(operator, created, OPENCMS, agent, "configurator")

    response = _deploy(agent, created)
    assert response.status_code == 200, response.text
    arena = response.json()["instance_id"]
    assert len(queued) == 1 and queued[0]["scenario_name"] == OPENCMS
    # Same worker path and scenario config as an operator deploy, so the FR-05
    # node limits and the default TTL/budget apply unchanged.
    assert queued[0]["scenario_config"]["nodes"][0]["resources"]["memory_mb"] == 2560
    record = Database().get_deployment(arena)
    assert record["expires_at"] is not None
    assert Database().budget_status(arena)["policy"]["action_cap"] >= 1

    db = Database()
    audit = db.list_events(arena, types=(database.AGENT_DEPLOY_EVENT,))
    assert audit[0]["payload"] == {"agent_name": agent.name, "scenario": OPENCMS}
    assert audit[0]["actor"] == agent.name
    assert db.list_events(arena, types=("created",))[0]["actor"] == agent.name

    # The deployer drives its arena as configurator only — never attacker.
    binding = bindings.binding_for(
        db.list_events(arena, types=bindings.BINDING_EVENT_TYPES), agent.name)
    assert binding["stance"] == "configurator" and binding["auto"]
    assert agent.get(f"/status/{arena}").status_code == 200
    assert agent.post(f"/arenas/{arena}/findings", json={"title": "x"}).status_code == 403


def test_empty_allowlist_refuses_the_same_call(env, monkeypatch):
    operator, queued, created = env
    monkeypatch.setattr(config, "AGENT_DEPLOY_SCENARIOS", ())
    agent = _client("agent")
    _seed_arena(operator, created, OPENCMS, agent, "configurator")
    before = len(Database().list_deployments())
    response = _deploy(agent, created)
    assert response.status_code == 403 and _code(response) == "agent_deploy_disabled"
    assert queued == [] and len(Database().list_deployments()) == before


@pytest.mark.parametrize("allowlist", [(OPENCMS,), ()])
def test_attacker_is_refused_in_both_cases(env, monkeypatch, allowlist):
    operator, queued, created = env
    monkeypatch.setattr(config, "AGENT_DEPLOY_SCENARIOS", allowlist)
    attacker = _client("agent")
    _seed_arena(operator, created, OPENCMS, attacker, "attacker")
    response = _deploy(attacker, created)
    assert response.status_code == 403
    assert _code(response) == ("stance_not_permitted" if allowlist else "agent_deploy_disabled")
    assert queued == []


def test_unbound_agent_and_revoked_configurator_are_refused(env):
    operator, queued, created = env
    agent = _client("agent")
    assert _code(_deploy(agent, created)) == "stance_not_permitted"
    seed = _seed_arena(operator, created, OPENCMS, agent, "configurator")
    operator.delete(f"/arenas/{seed}/bindings/{agent.name}")
    assert _code(_deploy(agent, created)) == "stance_not_permitted"
    assert queued == []


def test_configurator_of_another_scenario_cannot_deploy_this_one(env):
    operator, queued, created = env
    agent = _client("agent")
    _seed_arena(operator, created, OTHER, agent, "configurator")
    assert _code(_deploy(agent, created)) == "stance_not_permitted"  # no OpenCMS grant
    response = _deploy(agent, created, scenario=OTHER)
    assert response.status_code == 403 and _code(response) == "scenario_not_allowlisted"
    assert queued == []


def test_paused_configurator_is_refused(env):
    operator, _, created = env
    agent = _client("agent")
    seed = _seed_arena(operator, created, OPENCMS, agent, "configurator")
    operator.post(f"/arenas/{seed}/bindings/{agent.name}/pause")
    response = _deploy(agent, created)
    assert response.status_code == 423 and _code(response) == "binding_paused"


def test_hourly_quota(env, monkeypatch):
    operator, queued, created = env
    monkeypatch.setattr(config, "AGENT_DEPLOY_MAX_PER_HOUR", 2)
    monkeypatch.setattr(config, "AGENT_DEPLOY_MAX_LIVE", 10)
    agent = _client("agent")
    _seed_arena(operator, created, OPENCMS, agent, "configurator")
    assert _deploy(agent, created).status_code == 200
    assert _deploy(agent, created).status_code == 200
    refused = _deploy(agent, created)
    assert refused.status_code == 429 and _code(refused) == "agent_deploy_quota_exceeded"
    assert len(queued) == 2
    # The quota is per agent.
    other = _client("agent")
    _seed_arena(operator, created, OPENCMS, other, "configurator")
    assert _deploy(other, created).status_code == 200


def test_live_arena_limit_frees_up_after_destroy(env, monkeypatch):
    operator, _, created = env
    monkeypatch.setattr(config, "AGENT_DEPLOY_MAX_LIVE", 1)
    agent = _client("agent")
    _seed_arena(operator, created, OPENCMS, agent, "configurator")
    first = _deploy(agent, created).json()["instance_id"]
    refused = _deploy(agent, created)
    assert refused.status_code == 429 and _code(refused) == "agent_deploy_live_limit"
    db = Database()
    db.update_deployment(first, status="destroying")
    db.update_deployment(first, status="destroyed")
    assert _deploy(agent, created).status_code == 200


def test_runtime_kill_switch(env):
    operator, queued, created = env
    agent = _client("agent")
    _seed_arena(operator, created, OPENCMS, agent, "configurator")
    body = {"engaged": True, "reason": "incident"}
    assert agent.post("/system/agent-deploy/kill-switch", json=body).status_code == 403
    status = operator.post("/system/agent-deploy/kill-switch", json=body).json()
    assert status["enabled"] is False and status["kill_switch"]["engaged"] is True
    refused = _deploy(agent, created)
    assert refused.status_code == 403 and _code(refused) == "agent_deploy_disabled"
    operator.post("/system/agent-deploy/kill-switch", json={"engaged": False, "reason": "ok"})
    assert operator.get("/system/agent-deploy").json()["enabled"] is True
    assert _deploy(agent, created).status_code == 200
    assert len(queued) == 1
    switches = Database().list_events("system", types=(database.AGENT_DEPLOY_KILL_EVENT,))
    assert [e["payload"]["engaged"] for e in switches[:2]] == [False, True]


def test_operator_deploy_is_unaffected(env, monkeypatch):
    operator, queued, created = env
    monkeypatch.setattr(config, "AGENT_DEPLOY_SCENARIOS", ())
    assert _deploy(operator, created).status_code == 200
    assert len(queued) == 1


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"),
                    reason="PostgreSQL quota race")
def test_racing_agent_deploys_never_exceed_the_hourly_quota(env, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    operator, queued, created = env
    monkeypatch.setattr(config, "AGENT_DEPLOY_MAX_PER_HOUR", 2)
    monkeypatch.setattr(config, "AGENT_DEPLOY_MAX_LIVE", 10)
    agent = _client("agent")
    _seed_arena(operator, created, OPENCMS, agent, "configurator")
    workers = 8
    barrier = Barrier(workers)

    def deploy(_):
        barrier.wait(5)
        return _deploy(agent, created)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        responses = list(pool.map(deploy, range(workers)))
    accepted = [r for r in responses if r.status_code == 200]
    assert len(accepted) == 2, [r.text for r in responses]
    assert all(r.status_code == 429 for r in responses if r.status_code != 200)
    assert len(queued) == 2
