"""
PF-02 (#22): open-egress arenas reach host services on non-loopback addresses.

PF-01 U1 showed that locked arenas are contained, while a scenario with
``requires.egress: open`` runs on a normal Docker bridge and reaches the host's LAN,
VPN and other bridge addresses. The provider cannot restrict that per destination,
so deploying one now takes an operator's explicit, audited acknowledgement. The
worker refuses an unacknowledged open-egress deploy, whichever route queued it.
"""
import copy
import uuid

import pytest
from fastapi.testclient import TestClient

import api
import tasks
from auth import generate_api_key, hash_api_key
from database import Database

SPEC = {
    "schema": "nidavellir/v3",
    "name": "Open egress lab",
    "requires": {"provider_class": "container", "egress": "open"},
    "network": {"segments": [{"name": "lab"}]},
    "nodes": [
        {"name": "kali", "role": "attacker", "image": "kali", "segments": ["lab"],
         "entrypoint": True},
        {"name": "web", "role": "victim", "image": "dvwa", "segments": ["lab"]},
    ],
}


def _client(role):
    name = f"pf02-{role}-{uuid.uuid4().hex[:8]}"
    key = generate_api_key()
    Database().create_api_key(hash_api_key(key), name, role)
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.name = name
    return c


@pytest.fixture()
def env(monkeypatch):
    queued = []
    monkeypatch.setattr(api.deploy_lab, "delay", lambda **kw: queued.append(kw))
    operator = _client("operator")
    ids = {}
    for label, egress in (("open", "open"), ("locked", "none")):
        spec = copy.deepcopy(SPEC)
        spec["requires"]["egress"] = egress
        spec["name"] = f"PF02 {label} {uuid.uuid4().hex[:6]}"
        scenario_id = f"pf02-{label}-{uuid.uuid4().hex[:6]}"
        r = operator.post("/scenarios", json={"spec": spec, "id": scenario_id})
        assert r.status_code in (200, 201), r.text
        ids[label] = scenario_id
    yield operator, queued, ids
    for scenario_id in ids.values():
        operator.delete(f"/scenarios/{scenario_id}")


def _deploy(c, scenario, **extra):
    return c.post("/deploy", json={"scenario": scenario,
                                   "instance_id": f"pf02-{uuid.uuid4().hex[:6]}", **extra})


def test_operator_must_acknowledge_open_egress(env):
    operator, queued, ids = env
    refused = _deploy(operator, ids["open"])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "open_egress_unacknowledged"
    assert "host's own non-loopback addresses" in refused.json()["detail"]["message"]
    assert queued == []


def test_acknowledged_deploy_is_queued_and_audited(env):
    operator, queued, ids = env
    r = _deploy(operator, ids["open"], acknowledge_open_egress=True)
    assert r.status_code == 200, r.text
    arena = r.json()["instance_id"]
    assert len(queued) == 1
    (ack,) = Database().list_events(arena, limit=None, types=(tasks.OPEN_EGRESS_ACK_EVENT,))
    assert ack["actor"] == operator.name and ack["payload"]["scenario"] == ids["open"]


def test_agents_cannot_deploy_open_egress_even_when_acknowledging(env):
    _, queued, ids = env
    agent = _client("agent")
    r = _deploy(agent, ids["open"], acknowledge_open_egress=True)
    assert r.status_code == 403, r.text
    assert queued == []


def test_locked_scenarios_need_no_acknowledgement(env):
    operator, queued, ids = env
    assert _deploy(operator, ids["locked"]).status_code == 200
    assert len(queued) == 1


def test_worker_refuses_an_unacknowledged_open_egress_deploy(monkeypatch):
    db = Database()
    arena = uuid.uuid4().hex[:16]
    db.create_deployment(arena, arena, "custom", provider=None, actor="test")
    called = []

    class _Orchestrator:
        def __init__(self, provider_name=None):
            pass

        def deploy(self, *args, **kwargs):
            called.append(args)
            return {"success": True, "outputs": {}}

        def destroy(self, instance_id):  # the failure path reclaims; nothing exists
            return {"success": True}

    monkeypatch.setattr(tasks, "Orchestrator", _Orchestrator)
    result = tasks.deploy_lab.run(arena, "custom", arena, scenario_config=copy.deepcopy(SPEC))
    assert result["success"] is False and "not acknowledged" in result["error"]
    assert called == [], "nothing may be provisioned"
    assert db.get_deployment(arena)["status"] == "failed"


def test_worker_deploys_once_acknowledged(monkeypatch):
    db = Database()
    arena = uuid.uuid4().hex[:16]
    db.create_deployment(arena, arena, "custom", provider=None, actor="test")
    db.record_event(arena, tasks.OPEN_EGRESS_ACK_EVENT, {"scenario": "x"}, actor="op")
    assert not tasks.open_egress_unacknowledged(db, arena, "custom", copy.deepcopy(SPEC))
