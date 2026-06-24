"""
Tests for the manual scenario creator: the curated image catalog, the
selection→v3 compiler, the /catalog + /arenas/custom endpoints, and inline
scenario dispatch (ROADMAP P1-3).
"""
import pytest

import catalog
from scenario_spec import ScenarioSpec


# --- catalog + builder -------------------------------------------------------


def test_catalog_lists_attackers_and_victims():
    kinds = {i["kind"] for i in catalog.list_catalog()}
    assert kinds == {"attacker", "victim"}
    attackers = {i["id"] for i in catalog.list_catalog("attacker")}
    assert {"kali-cli", "kali-gui", "ubuntu"} <= attackers


def test_build_custom_scenario_is_valid_v3():
    raw = catalog.build_custom_scenario("my-lab", "kali-cli", ["dvwa"])
    spec = ScenarioSpec.from_raw(raw)  # must validate
    assert spec.requires.provider_class.value == "container"
    names = [n.name for n in spec.nodes]
    assert names == ["kali-cli", "dvwa"]
    # attacker is the entrypoint + bound as the attacker stance
    attacker = next(n for n in spec.nodes if n.name == "kali-cli")
    assert attacker.entrypoint is True
    assert spec.agents[0].stance.value == "attacker"
    # the victim publishes its service port
    dvwa = next(n for n in spec.nodes if n.name == "dvwa")
    assert dvwa.ports == [80]


def test_build_rejects_unknown_wrong_kind_and_vm_only():
    with pytest.raises(catalog.CatalogError, match="unknown catalog image"):
        catalog.build_custom_scenario("x", "nope", ["dvwa"])
    with pytest.raises(catalog.CatalogError, match="not an attacker"):
        catalog.build_custom_scenario("x", "dvwa", ["dvwa"])
    with pytest.raises(catalog.CatalogError, match="not a victim"):
        catalog.build_custom_scenario("x", "ubuntu", ["kali-cli"])
    # Mr Robot is a VulnHub VM image — not runnable on docker-local.
    with pytest.raises(catalog.CatalogError, match="not runnable on docker-local"):
        catalog.build_custom_scenario("x", "kali-cli", ["mr-robot"])


def test_build_requires_at_least_one_victim_and_rejects_dupes():
    with pytest.raises(catalog.CatalogError, match="at least one victim"):
        catalog.build_custom_scenario("x", "kali-cli", [])
    with pytest.raises(catalog.CatalogError, match="duplicate"):
        catalog.build_custom_scenario("x", "kali-cli", ["dvwa", "dvwa"])


def test_multi_victim_topology():
    raw = catalog.build_custom_scenario("mesh", "kali-cli", ["dvwa", "juice-shop"])
    spec = ScenarioSpec.from_raw(raw)
    assert [n.name for n in spec.nodes] == ["kali-cli", "dvwa", "juice-shop"]


# --- API ---------------------------------------------------------------------


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
    Database().create_api_key(auth.hash_api_key(key), name="catalog-tests", role="operator")

    from fastapi.testclient import TestClient

    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.dispatched = dispatched
    return c


def test_catalog_endpoint_requires_auth():
    import api
    from fastapi.testclient import TestClient

    assert TestClient(api.app).get("/catalog").status_code == 401


def test_catalog_endpoint_lists_images(client):
    resp = client.get("/catalog")
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["images"]}
    assert "kali-cli" in ids and "dvwa" in ids


def test_custom_arena_accepts_and_dispatches_inline_spec(client):
    resp = client.post(
        "/arenas/custom",
        json={"instance_id": "my-lab", "attacker": "kali-cli", "victims": ["dvwa"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"
    # the worker is handed a validated inline scenario, not a registry id
    spec = client.dispatched["scenario_config"]
    assert spec["schema"] == "nidavellir/v3"
    assert {n["name"] for n in spec["nodes"]} == {"kali-cli", "dvwa"}
    assert client.dispatched["provider"] == "docker-local"


def test_custom_arena_rejects_bad_selection(client):
    resp = client.post(
        "/arenas/custom",
        json={"instance_id": "bad-lab", "attacker": "kali-cli", "victims": ["mr-robot"]},
    )
    assert resp.status_code == 422
    assert "docker-local" in resp.text


def test_custom_arena_rejects_bad_instance_name(client):
    resp = client.post(
        "/arenas/custom",
        json={"instance_id": "Bad Name", "attacker": "kali-cli", "victims": ["dvwa"]},
    )
    assert resp.status_code == 422


# --- inline deploy through the orchestrator ----------------------------------


def test_orchestrator_uses_inline_scenario_config_over_registry():
    from orchestrator import Orchestrator

    class _Recorder:
        name = "rec"

        def __init__(self):
            self.got = None

        def deploy(self, scenario_config, instance_id, user_vars=None):
            self.got = scenario_config
            return {"success": True, "outputs": {}}

        def destroy(self, instance_id):
            return {"success": True}

    rec = _Recorder()
    inline = {"schema": "nidavellir/v3", "nodes": [{"name": "n", "image": "i"}]}
    # scenario_name is bogus on purpose: the inline config must win, no load.
    Orchestrator(provider=rec).deploy("no-such-scenario", "id-1", {}, scenario_config=inline)
    assert rec.got is inline
