"""REST ownership, publication and evidence-derived confidence."""
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import api
import auth
import crypto
from tests.test_configuration_capture import recipe


@pytest.fixture
def clients(monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_default_cipher()
    names = ["lineage-op-" + uuid4().hex[:8], "lineage-agent-" + uuid4().hex[:8]]
    clients = []
    for name, role in zip(names, ("operator", "agent")):
        key = auth.generate_api_key()
        api.db.create_api_key(auth.hash_api_key(key), name=name, role=role)
        client = TestClient(api.app)
        client.headers["X-API-Key"] = key
        clients.append(client)
    yield api.db, *clients, names
    crypto.reset_default_cipher()


def arena(db, name, value="false"):
    name = name + uuid4().hex[:8]
    db.create_deployment(name, "operator", "lineage-fixture", provider="docker-local")
    db.save_lifecycle_recipe(name, recipe(value))
    return name


def test_operator_capture_compare_and_raw_agent_denial(clients):
    db, operator, agent, _ = clients
    first, second = arena(db, "first"), arena(db, "second", "true")
    snapshots = []
    for name in (first, second):
        response = operator.post(f"/arenas/{name}/configuration-snapshots", json={"stage": "deployment"})
        assert response.status_code == 201, response.text
        snapshots.append(response.json()["snapshot"])
        assert agent.get(f"/arenas/{name}/configuration-snapshots").status_code == 403
        assert agent.post(f"/arenas/{name}/configuration-snapshots", json={"stage": "deployment"}).status_code == 403
    compare = operator.post("/configuration-lineage/compare", json={
        "before": snapshots[0]["snapshot_id"], "after": snapshots[1]["snapshot_id"]})
    assert compare.status_code == 200, compare.text
    assert compare.json()["candidate_keys"] == ["service.authorization.disabled"]
    assert operator.get(f"/arenas/{second}/configuration-snapshots/{snapshots[0]['snapshot_id']}").status_code == 404


def test_analysis_rejects_caller_verdicts_and_hides_private_events(clients):
    db, operator, agent, _ = clients
    first, second = arena(db, "analysis-a"), arena(db, "analysis-b", "true")
    ids = [operator.post(f"/arenas/{name}/configuration-snapshots", json={"stage": "deployment"}).json()["snapshot"]["snapshot_id"] for name in (first, second)]
    body = {"subject_arena_id": second, "snapshot_ids": ids, "research_key": "unverified"}
    forged = operator.post("/configuration-lineage/analyze", json={**body, "observations": [{"verdict": "confirmed"}]})
    assert forged.status_code == 422
    response = operator.post("/configuration-lineage/analyze", json=body)
    assert response.status_code == 201, response.text
    analysis = response.json()
    assert analysis["confidence"] == "inferred"
    assert analysis["earliest_known_vulnerable"] is None
    path = f"/arenas/{second}/configuration-lineage/{analysis['analysis_id']}"
    assert agent.get(path).status_code == 403
    events = agent.get(f"/deployments/{second}/events").json()["events"]
    assert not any(event["type"].startswith("configuration_") for event in events)


def test_agent_projection_requires_explicit_publication_binding_and_subject(clients):
    db, operator, agent, names = clients
    first, second = arena(db, "published-a"), arena(db, "published-b", "true")
    db.record_event(second, "engagement_intent", {"purpose": "research"}, actor=names[0])
    ids = [operator.post(f"/arenas/{name}/configuration-snapshots", json={"stage": "deployment"}).json()["snapshot"]["snapshot_id"] for name in (first, second)]
    analysis = operator.post("/configuration-lineage/analyze", json={
        "subject_arena_id": second, "snapshot_ids": ids, "research_key": "hypothesis",
        "publish_to": [names[1]]}).json()
    assert "analysis_id" in analysis, analysis
    path = f"/arenas/{second}/configuration-lineage/{analysis['analysis_id']}"
    assert agent.get(path).status_code == 403
    db.record_event(second, "agent_binding", {"agent_name": names[1], "stance": "attacker"}, actor=names[0])
    response = agent.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["candidate_keys"] == ["service.authorization.disabled"]
    delta = response.json()["delta"]
    assert delta["before_snapshot_id"] == ids[0]
    assert delta["after_snapshot_id"] == ids[1]
    assert delta["changes"][0]["before"]["value"] is False
    assert delta["changes"][0]["after"]["value"] is True
    assert delta["changes"][0]["after"]["source_class"] == "scenario"
    assert response.json()["completeness"]["status"] == "complete"
    assert "evidence_digests" not in response.json()
    assert agent.get(f"/arenas/{first}/configuration-lineage/{analysis['analysis_id']}").status_code in (403, 404)


def test_profile_deployment_without_encryption_fails_before_recipe_storage(clients, monkeypatch):
    from datetime import datetime, timedelta
    from fastapi import HTTPException

    db, _, _, _ = clients
    name = "unencrypted-profile-" + uuid4().hex[:8]
    db.create_deployment(name, "operator", "lineage-fixture")
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "")
    crypto.reset_default_cipher()
    with pytest.raises(HTTPException) as error:
        api._record_lifecycle_recipe(name, scenario_name="lineage-fixture", scenario_config=recipe()["scenario"],
            requested_provider="docker-local", expires_at=datetime.now() + timedelta(hours=1))
    assert error.value.status_code == 422
    assert db.get_lifecycle_recipe(name) is None
    assert db.get_deployment(name)["status"] == "failed"
