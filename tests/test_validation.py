"""
Tests for input validation and the scenario registry (ROADMAP audit #4).

Pins the contract: deploy requests with malformed friendly names or
unregistered scenario ids are rejected with 422 before anything reaches the
queue or the filesystem; GET /scenarios serves the registry; the orchestrator
independently refuses path-traversal scenario names (defense in depth).
"""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import scenarios  # noqa: E402
from database import Database  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    import api

    class _FakeTask:
        def delay(self, *args, **kwargs):
            return None

    monkeypatch.setattr(api, "deploy_lab", _FakeTask())
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="validation-tests", role="admin")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


# --- registry ---------------------------------------------------------------


def test_registry_lists_known_scenarios(client):
    resp = client.get("/scenarios")
    assert resp.status_code == 200
    by_id = {s["id"]: s for s in resp.json()["scenarios"]}
    assert "basic_pentest" in by_id
    assert "random_vulnhub" in by_id
    assert by_id["basic_pentest"]["difficulty"] == "medium"
    assert by_id["basic_pentest"]["name"]  # display name present


def test_registry_requires_auth():
    import api

    assert TestClient(api.app).get("/scenarios").status_code == 401


def test_registry_module_matches_template_files():
    from config import TEMPLATES_DIR

    assert scenarios.scenario_ids() == {p.stem for p in TEMPLATES_DIR.glob("*.yaml")}


# --- deploy validation ------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "Lab-Team-1",        # uppercase
        "lab team",          # space
        "-leading-hyphen",
        "a" * 41,            # too long
        "../escape",
        "lab_underscore",    # underscores reserved for scenario ids only
        "",
    ],
)
def test_deploy_rejects_bad_instance_names(client, bad_name):
    resp = client.post(
        "/deploy", json={"scenario": "basic_pentest", "instance_id": bad_name}
    )
    assert resp.status_code == 422, bad_name


@pytest.mark.parametrize(
    "bad_scenario",
    [
        "no-such-scenario",       # well-formed but unregistered
        "../../../etc/passwd",    # traversal
        "basic_pentest.yaml",     # dots rejected
        "BASIC_PENTEST",
        "",
    ],
)
def test_deploy_rejects_bad_scenarios(client, bad_scenario):
    resp = client.post(
        "/deploy", json={"scenario": bad_scenario, "instance_id": "lab-ok"}
    )
    assert resp.status_code == 422, bad_scenario


def test_deploy_accepts_valid_request(client):
    resp = client.post(
        "/deploy", json={"scenario": "basic_pentest", "instance_id": "lab-ok-1"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


def test_unknown_scenario_error_points_to_registry(client):
    resp = client.post(
        "/deploy", json={"scenario": "no-such-scenario", "instance_id": "lab-ok"}
    )
    assert "GET /scenarios" in resp.text


# --- orchestrator defense in depth ------------------------------------------


@pytest.mark.parametrize("evil", ["../../../etc/passwd", "x/../../y", "a.b"])
def test_load_scenario_rejects_traversal(evil):
    from orchestrator import Orchestrator

    assert Orchestrator()._load_scenario(evil) is None
