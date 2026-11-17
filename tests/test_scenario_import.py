"""
Tests for the scenario authoring & import seam (P1-7) and the pre-deploy
topology preview (P7-9):

  * scenarios.save_scenario / delete_scenario / dual-source discovery,
  * POST /scenarios (import), DELETE /scenarios/{id},
  * POST /scenarios/preview (dry-run validate + topology),
  * GET /scenarios/{id}/topology,
  * the multi-attacker custom builder.
"""
import pytest

import catalog
import config
import scenarios
from scenario_spec import ScenarioSpec, topology_view

MINIMAL_SPEC = {
    "schema": "nidavellir/v3",
    "name": "Imported Web Lab",
    "difficulty": "easy",
    "network": {"segments": [{"name": "lab"}]},
    "nodes": [
        {"name": "kali", "role": "attacker", "image": "kali",
         "segments": ["lab"], "entrypoint": True},
        {"name": "web", "role": "victim", "image": "dvwa",
         "segments": ["lab"], "ports": [80]},
    ],
    "agents": [{"stance": "attacker", "node": "kali"}],
}


@pytest.fixture(autouse=True)
def _clean_imported():
    """Each test starts with an empty imported-scenarios dir."""
    config.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    for f in config.SCENARIOS_DIR.glob("*.yaml"):
        f.unlink()
    yield
    for f in config.SCENARIOS_DIR.glob("*.yaml"):
        f.unlink()


# --- registry layer ----------------------------------------------------------


def test_save_and_discover_imported_scenario():
    summary = scenarios.save_scenario("imp-web", MINIMAL_SPEC)
    assert summary["source"] == "imported"
    assert summary["valid"] is True

    listing = {s["id"]: s for s in scenarios.list_scenarios()}
    assert listing["imp-web"]["source"] == "imported"
    # built-ins are still present and tagged builtin
    assert listing["container_web_pentest"]["source"] == "builtin"
    # round-trips through the loader
    assert scenarios.load_scenario_spec("imp-web") is not None


def test_save_refuses_builtin_id():
    with pytest.raises(ValueError, match="built-in"):
        scenarios.save_scenario("container_web_pentest", MINIMAL_SPEC)


def test_save_refuses_existing_without_overwrite_then_overwrites():
    scenarios.save_scenario("imp-web", MINIMAL_SPEC)
    with pytest.raises(FileExistsError):
        scenarios.save_scenario("imp-web", MINIMAL_SPEC)
    # overwrite=True replaces it
    scenarios.save_scenario("imp-web", MINIMAL_SPEC, overwrite=True)


def test_save_rejects_invalid_spec():
    from pydantic import ValidationError

    bad = {"schema": "nidavellir/v3", "name": "x", "nodes": []}
    with pytest.raises(ValidationError):
        scenarios.save_scenario("imp-bad", bad)


def test_delete_imported_and_protects_builtin():
    scenarios.save_scenario("imp-web", MINIMAL_SPEC)
    assert scenarios.delete_scenario("imp-web") is True
    assert scenarios.delete_scenario("imp-web") is False  # already gone
    with pytest.raises(ValueError, match="built-in"):
        scenarios.delete_scenario("container_web_pentest")


def test_imported_id_cannot_shadow_builtin_in_listing():
    # writing a file with a built-in's id directly into SCENARIOS_DIR must not
    # shadow the built-in (built-in wins; the import is ignored)
    (config.SCENARIOS_DIR / "container_web_pentest.yaml").write_text(
        "schema: nidavellir/v3\nname: evil\nnodes: [{name: n, image: i}]\n"
    )
    listing = {s["id"]: s for s in scenarios.list_scenarios()}
    assert listing["container_web_pentest"]["source"] == "builtin"


# --- topology_view -----------------------------------------------------------


def test_topology_view_shape():
    spec = ScenarioSpec.from_raw(MINIMAL_SPEC)
    topo = topology_view(spec)
    assert {s["name"] for s in topo["segments"]} == {"lab"}
    kinds = {n["name"]: n["kind"] for n in topo["nodes"]}
    assert kinds["kali"] == "foothold"   # entrypoint + attacker stance
    assert kinds["web"] == "target"      # has a published port
    # every node→segment membership is an edge
    assert {"node": "kali", "segment": "lab"} in topo["edges"]
    assert topo["egress"] == "blocked"


# --- multi-attacker builder --------------------------------------------------


def test_build_custom_multiple_attackers():
    raw = catalog.build_custom_scenario("mesh", ["kali-cli", "ubuntu"], ["dvwa"])
    spec = ScenarioSpec.from_raw(raw)
    assert [n.name for n in spec.nodes] == ["kali-cli", "ubuntu", "dvwa"]
    # both attackers are entrypoints + bound as the attacker stance
    entrypoints = {n.name for n in spec.nodes if n.entrypoint}
    assert entrypoints == {"kali-cli", "ubuntu"}
    bound = {b.node for b in spec.agents if b.stance.value == "attacker"}
    assert bound == {"kali-cli", "ubuntu"}


def test_build_custom_single_attacker_str_still_works():
    raw = catalog.build_custom_scenario("solo", "kali-cli", ["dvwa"])
    assert [n["name"] for n in raw["nodes"]] == ["kali-cli", "dvwa"]


def test_build_custom_rejects_empty_attackers_and_dupes():
    with pytest.raises(catalog.CatalogError, match="at least one attacker"):
        catalog.build_custom_scenario("x", [], ["dvwa"])
    with pytest.raises(catalog.CatalogError, match="duplicate"):
        catalog.build_custom_scenario("x", ["kali-cli", "kali-cli"], ["dvwa"])


# --- API ---------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    import api
    import auth
    from database import Database
    from fastapi.testclient import TestClient

    dispatched = {}

    class _FakeTask:
        def delay(self, *args, **kwargs):
            dispatched.update(kwargs)
            return None

    monkeypatch.setattr(api, "deploy_lab", _FakeTask())
    op_key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(op_key), name="import-op", role="operator")
    ag_key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(ag_key), name="import-agent", role="agent")

    c = TestClient(api.app)
    c.headers["X-API-Key"] = op_key
    c.agent_key = ag_key
    c.dispatched = dispatched
    return c


def test_import_scenario_persists_and_lists(client):
    resp = client.post("/scenarios", json={"spec": MINIMAL_SPEC})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "imported"
    assert body["id"] == "imported-web-lab"  # derived from the name
    # it now shows up in the registry as imported
    listing = client.get("/scenarios").json()["scenarios"]
    entry = next(s for s in listing if s["id"] == "imported-web-lab")
    assert entry["source"] == "imported"


def test_import_accepts_yaml_string(client):
    yaml_text = (
        "schema: nidavellir/v3\n"
        "name: yaml-lab\n"
        "network: {segments: [{name: lab}]}\n"
        "nodes:\n"
        "  - {name: box, role: victim, image: dvwa, segments: [lab], ports: [80]}\n"
    )
    resp = client.post("/scenarios", json={"spec": yaml_text, "id": "yaml-lab"})
    assert resp.status_code == 200, resp.text
    assert scenarios.load_scenario_spec("yaml-lab") is not None


def test_import_rejects_invalid_spec_422(client):
    resp = client.post("/scenarios", json={"spec": {"schema": "nidavellir/v3", "name": "x", "nodes": []}})
    assert resp.status_code == 422


def test_import_rejects_builtin_collision_422(client):
    resp = client.post("/scenarios", json={"spec": MINIMAL_SPEC, "id": "container_web_pentest"})
    assert resp.status_code == 422
    assert "built-in" in resp.text


def test_import_duplicate_409(client):
    client.post("/scenarios", json={"spec": MINIMAL_SPEC, "id": "dup-lab"})
    again = client.post("/scenarios", json={"spec": MINIMAL_SPEC, "id": "dup-lab"})
    assert again.status_code == 409


def test_import_requires_operator(client):
    resp = client.post(
        "/scenarios", json={"spec": MINIMAL_SPEC},
        headers={"X-API-Key": client.agent_key},
    )
    assert resp.status_code == 403


def test_delete_imported_scenario(client):
    client.post("/scenarios", json={"spec": MINIMAL_SPEC, "id": "del-lab"})
    resp = client.delete("/scenarios/del-lab")
    assert resp.status_code == 200
    assert client.delete("/scenarios/del-lab").status_code == 404
    # built-ins cannot be deleted
    assert client.delete("/scenarios/container_web_pentest").status_code == 422


def test_preview_from_picks(client):
    resp = client.post(
        "/scenarios/preview",
        json={"picks": {"attackers": ["kali-cli", "ubuntu"], "victims": ["dvwa"]}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    footholds = [n for n in body["topology"]["nodes"] if n["kind"] == "foothold"]
    assert len(footholds) == 2


def test_preview_from_spec_and_invalid(client):
    ok = client.post("/scenarios/preview", json={"spec": MINIMAL_SPEC}).json()
    assert ok["valid"] is True
    assert ok["summary"]["nodes"] == 2

    bad = client.post(
        "/scenarios/preview",
        json={"spec": {"schema": "nidavellir/v3", "name": "x", "nodes": []}},
    ).json()
    assert bad["valid"] is False
    assert bad["errors"]


def test_preview_requires_operator(client):
    resp = client.post(
        "/scenarios/preview", json={"spec": MINIMAL_SPEC},
        headers={"X-API-Key": client.agent_key},
    )
    assert resp.status_code == 403


def test_topology_of_registered_scenario(client):
    resp = client.get("/scenarios/container_web_pentest/topology")
    assert resp.status_code == 200, resp.text
    assert resp.json()["topology"]["nodes"]
    assert client.get("/scenarios/no-such-scenario/topology").status_code == 404


def test_custom_arena_multi_attacker_dispatch(client):
    resp = client.post(
        "/arenas/custom",
        json={"instance_id": "multi", "attackers": ["kali-cli", "ubuntu"], "victims": ["dvwa"]},
    )
    assert resp.status_code == 200, resp.text
    spec = client.dispatched["scenario_config"]
    names = {n["name"] for n in spec["nodes"]}
    assert {"kali-cli", "ubuntu", "dvwa"} <= names
    bound = {a["node"] for a in spec["agents"]}
    assert {"kali-cli", "ubuntu"} == bound
