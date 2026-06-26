"""
Software-under-test (SUT) launch wizard (P2-10): the GitHub-clone-into-Ubuntu
builder, the operator-only POST /arenas/sut endpoint (config captured at
creation — review 1.1), and the worker's pre-armed setup auto-open.
"""
import pytest
from fastapi.testclient import TestClient

import catalog
from scenario_spec import ScenarioSpec, normalized_nodes


# --- builder -----------------------------------------------------------------


def test_build_sut_scenario_is_valid_v3():
    raw = catalog.build_sut_scenario(
        "demo", "https://github.com/org/proj", ref="main", ports=[3000],
    )
    spec = ScenarioSpec.from_raw(raw)  # must validate
    assert spec.requires.provider_class.value == "container"
    victim = next(n for n in spec.nodes if n.name == "sut")
    assert victim.image == "ubuntu:22.04"
    assert victim.command == "sleep infinity"   # bare box stays up; no service yet
    assert victim.ports == [3000]
    # the kali foothold is the entrypoint + bound as the attacker stance
    assert any(n.name == "kali-cli" and n.entrypoint for n in spec.nodes)
    assert spec.agents[0].stance.value == "attacker"


def test_build_sut_clone_passes_through_normalized_nodes():
    raw = catalog.build_sut_scenario("demo", "https://github.com/org/proj", ref="v1.2")
    victim = next(n for n in normalized_nodes(raw) if n["name"] == "sut")
    assert victim["sut_clone"] == {
        "repo": "https://github.com/org/proj", "ref": "v1.2", "path": "/opt/sut",
    }


def test_build_sut_without_attacker_is_single_victim():
    raw = catalog.build_sut_scenario("solo", "https://github.com/org/proj",
                                     include_attacker=False)
    assert [n["name"] for n in raw["nodes"]] == ["sut"]
    assert raw["agents"] == []


# --- endpoint ----------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    import api
    import auth
    from database import Database

    dispatched = {}

    class _FakeTask:
        def delay(self, *args, **kwargs):
            dispatched.update(kwargs)
            return None

    monkeypatch.setattr(api, "deploy_lab", _FakeTask())
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="sut-tests", role="operator")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.dispatched = dispatched
    return c


def test_sut_endpoint_accepts_and_dispatches_with_prearm(client):
    from database import Database

    resp = client.post("/arenas/sut", json={
        "instance_id": "sut-lab", "repo": "https://github.com/org/proj",
        "ref": "main", "ports": [3000], "setup_mode": "hitl",
        "command_budget": 20, "time_box_seconds": 900,
    })
    assert resp.status_code == 200, resp.text
    sysid = resp.json()["instance_id"]

    # the worker is handed the inline topology AND the setup config
    spec = client.dispatched["scenario_config"]
    assert {n["name"] for n in spec["nodes"]} == {"sut", "kali-cli"}
    prearm = client.dispatched["setup_prearm"]
    assert prearm["mode"] == "hitl" and prearm["command_budget"] == 20
    assert prearm["setup_egress"] is True  # default

    # config is captured at creation as an audit breadcrumb (review 1.1)
    events = Database().list_events(sysid)
    prearm_evt = next(e for e in events if e["type"] == "setup_prearm")
    assert prearm_evt["payload"]["repo"] == "https://github.com/org/proj"
    assert prearm_evt["payload"]["mode"] == "hitl"


def test_sut_endpoint_rejects_non_https_repo(client):
    resp = client.post("/arenas/sut", json={
        "instance_id": "bad-repo", "repo": "git@github.com:org/proj.git",
    })
    assert resp.status_code == 422
    assert "https" in resp.text


def test_sut_endpoint_rejects_autonomous_mode(client):
    resp = client.post("/arenas/sut", json={
        "instance_id": "auto-lab", "repo": "https://github.com/org/proj",
        "setup_mode": "autonomous",
    })
    assert resp.status_code == 422
    assert "autonomous" in resp.text


def test_sut_endpoint_is_operator_only():
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="sut-agent", role="agent")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    resp = c.post("/arenas/sut", json={
        "instance_id": "agent-sut", "repo": "https://github.com/org/proj",
    })
    assert resp.status_code == 403


# --- worker auto-open of the pre-armed setup ---------------------------------


def test_prearmed_setup_auto_opens_scoped_to_victim():
    import tasks
    from database import Database

    db = Database()
    iid = "sut-prearm"
    db.create_deployment(iid, iid, "sut:proj", provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    outputs = {
        "node_sut_name": "nv-sut",
        "node_sut_setup_shell": "docker exec -it nv-sut /bin/bash",
        "node_sut_sut_source": "/opt/sut",
        "node_kali-cli_name": "nv-kali",
        "node_kali-cli_ssh_command": "docker exec -it nv-kali /bin/bash",
    }
    db.update_deployment(iid, status="active", outputs=outputs, actor="test")

    tasks._open_prearmed_setup(
        db, None, iid, outputs,
        {"mode": "operator", "time_box_seconds": 600, "command_budget": 10,
         "setup_egress": True, "actor": "op"},
    )

    import setup_phase
    sess = setup_phase.current_session(db.list_events(iid))
    assert sess is not None
    assert sess["nodes"] == ["sut"]      # kali foothold excluded from victim scope
    assert sess["mode"] == "operator"
    assert sess["setup_egress"] is True


def test_prearmed_setup_surfaces_connect_command():
    """After auto-open, GET /setup includes the victim's connect command."""
    import api
    import auth
    import tasks
    from database import Database

    db = Database()
    iid = "sut-connect"
    db.create_deployment(iid, iid, "sut:proj", provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    outputs = {
        "node_sut_name": "nv-sut",
        "node_sut_setup_shell": "docker exec -it nv-sut /bin/bash",
        "node_kali-cli_name": "nv-kali",
        "node_kali-cli_ssh_command": "docker exec -it nv-kali /bin/bash",
    }
    db.update_deployment(iid, status="active", outputs=outputs, actor="test")
    tasks._open_prearmed_setup(
        db, None, iid, outputs,
        {"mode": "operator", "time_box_seconds": 600, "command_budget": 10,
         "setup_egress": False, "actor": "op"},
    )

    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name="sut-op2", role="operator")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    body = c.get(f"/arenas/{iid}/setup").json()
    assert body["open"] is True
    assert body["connect"]["sut"] == "docker exec -it nv-sut /bin/bash"


# --- wizard: no-deploy preview (P3-3) ----------------------------------------


def test_sut_preview_returns_topology_without_deploying(client, monkeypatch):
    import image_check

    monkeypatch.setattr(image_check, "exists_on_hub", lambda ref: None)  # no network
    resp = client.post("/arenas/sut/preview", json={
        "instance_id": "sut-prev", "repo": "https://github.com/org/proj",
        "ports": [8000], "include_attacker": True,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["summary"]["nodes"] == 2
    assert body["topology"] is not None
    assert client.dispatched == {}   # review only — nothing deployed


def test_sut_preview_is_operator_only():
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="sut-prev-agent", role="agent")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    resp = c.post("/arenas/sut/preview", json={
        "instance_id": "x", "repo": "https://github.com/o/proj",
    })
    assert resp.status_code == 403
