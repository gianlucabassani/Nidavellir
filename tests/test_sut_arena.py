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


# --- M1-2: build-plan-driven auto-build vs bare-box fallback -----------------


def test_build_sut_auto_builds_from_executable_dockerfile_plan():
    import build_planner

    plan = build_planner.plan_build(
        {"build_system": "dockerfile", "detected_files": ["Dockerfile"], "declared_ports": [8080]})
    raw = catalog.build_sut_scenario("demo", "https://github.com/org/proj", ref="abc123",
                                     build_plan=plan)
    victim = next(n for n in normalized_nodes(raw) if n["name"] == "sut")
    # auto-build victim: a service.source block (→ needs_build), no bare-box clone
    assert victim["needs_build"] is True
    assert victim.get("sut_clone") is None
    assert victim["service"]["source"]["repo"] == "https://github.com/org/proj"
    assert victim["service"]["source"]["dockerfile"] == "Dockerfile"
    assert victim["service"]["source"]["ref"] == "abc123"
    assert victim["ports"] == [8080]           # detected port carried through
    ScenarioSpec.from_raw(raw)                 # still a valid v3 topology


def test_build_sut_non_executable_plan_keeps_bare_box():
    import build_planner

    # a compose plan is deterministic but NOT executable this increment → fallback
    plan = build_planner.plan_build({"build_system": "compose", "detected_files": ["compose.yml"]})
    raw = catalog.build_sut_scenario("demo", "https://github.com/org/proj", build_plan=plan)
    victim = next(n for n in raw["nodes"] if n["name"] == "sut")
    assert victim["image"] == "ubuntu:22.04" and "sut_clone" in victim


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
    # Stub repo introspection so the endpoints never touch the network in tests
    # (the module itself is unit-tested in test_repo_introspect.py).
    monkeypatch.setattr(
        api.repo_introspect, "introspect",
        lambda repo, ref=None: {"repo": repo, "ref": ref, "language": "node",
                                "build_system": "dockerfile", "declared_ports": [3000],
                                "indicators": ["Dockerfile"]},
    )
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
    # M1-1: the repo introspection is captured once at deploy for the proposer.
    assert prearm_evt["payload"]["introspection"]["language"] == "node"
    assert prearm_evt["payload"]["introspection"]["declared_ports"] == [3000]


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
    # M1-1: the review surfaces the repo introspection so the operator sees the
    # detected build system / declared ports before launch.
    assert body["introspection"]["build_system"] == "dockerfile"
    assert body["introspection"]["declared_ports"] == [3000]
    # M1-2: and the planned build tier (dockerfile → executable; auto_build reflects
    # the source-build gate, off by default).
    assert body["build_plan"]["strategy"] == "dockerfile"
    assert body["build_plan"]["executable"] is True
    assert body["build_plan"]["auto_build"] is False   # ALLOW_SOURCE_BUILD off by default


def test_sut_deploy_auto_builds_when_source_builds_enabled(client, monkeypatch):
    import config

    # With the source-build gate ON and a Dockerfile repo, the dispatched spec's
    # victim auto-builds (service.source) instead of the bare-box + clone flow.
    monkeypatch.setattr(config, "ALLOW_SOURCE_BUILD", True)
    resp = client.post("/arenas/sut", json={
        "instance_id": "sut-autobuild", "repo": "https://github.com/org/proj", "ref": "main",
    })
    assert resp.status_code == 200, resp.text
    spec = client.dispatched["scenario_config"]
    victim = next(n for n in spec["nodes"] if n["name"] == "sut")
    assert victim["service"]["source"]["repo"] == "https://github.com/org/proj"
    assert victim["service"]["source"]["dockerfile"] == "Dockerfile"
    assert "sut_clone" not in victim
    prearm = client.dispatched["setup_prearm"]  # prearm still carries the config
    assert prearm["mode"]  # sanity


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
