"""Affected-versus-fixed finding groups (NV-11)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api
import auth
from database import Database


@pytest.fixture()
def clients():
    db = Database()
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name="variant-operator", role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    return db, client


def _arena(db, name):
    db.create_deployment(name, name, name, provider="docker-local", actor="test")
    db.update_deployment(name, status="deploying", actor="test")
    db.update_deployment(name, status="active", actor="test")
    return name


def _post_manual(operator, arena, title, variant_of=None):
    body = {"title": title, "cwe": "CWE-639", "node": "target"}
    if variant_of:
        body["variant_of"] = variant_of
    return operator.post(f"/arenas/{arena}/findings/manual", json=body)


def _finding_payloads(operator, arena):
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    return {e["payload"]["finding_id"]: e["payload"]
            for e in events if e["type"] == "finding"}


def test_manual_finding_links_variant_and_root(clients):
    db, operator = clients
    arena = _arena(db, "variant-root")
    root = _post_manual(operator, arena, "root claim").json()["finding_id"]
    variant = _post_manual(operator, arena, "variant claim", variant_of=root)
    assert variant.status_code == 200, variant.text
    payloads = _finding_payloads(operator, arena)
    assert payloads[root]["research_key"] == root
    assert payloads[root]["variant_of"] is None
    assert payloads[variant.json()["finding_id"]]["variant_of"] == root
    assert payloads[variant.json()["finding_id"]]["research_key"] == root


def test_unknown_variant_of_is_rejected(clients):
    db, operator = clients
    arena = _arena(db, "variant-unknown")
    assert _post_manual(operator, arena, "x", variant_of="0" * 12).status_code == 422
    assert _post_manual(operator, arena, "x", variant_of="not-a-finding").status_code == 422


def test_find_finding_event_prefers_newest(clients):
    db, _ = clients
    db.record_event("arena-old", "finding", {"finding_id": "abc123abc123", "title": "old"})
    db.record_event("arena-new", "finding", {"finding_id": "abc123abc123", "title": "new"})
    event = api._find_finding_event("abc123abc123")
    assert event["lab_id"] == "arena-new"
    assert event["payload"]["title"] == "new"


def test_variant_reference_succeeds_across_arenas_without_leaking(clients):
    db, operator = clients
    source = _arena(db, "variant-source")
    target = _arena(db, "variant-target")
    root = _post_manual(operator, source, "root claim").json()["finding_id"]
    response = _post_manual(operator, target, "variant claim", variant_of=root)
    assert response.status_code == 200
    assert set(response.json()) == {"recorded", "finding_id", "manual"}


SCENARIO = {
    "schema": "nidavellir/v3", "name": "variant-lab",
    "network": {"segments": [{"name": "lab"}]},
    "nodes": [{"name": "target", "role": "victim", "image": "sha256:" + "a" * 64,
               "segments": ["lab"], "ports": [80]}],
    "vulnerabilities": [{"id": "acl", "title": "x", "cwe": "CWE-639", "node": "target",
        "validator": "http_access_control",
        "validation_config": {"actor": "B", "owner": "A",
            "actor_headers": {"Authorization": "Bearer b"},
            "owner_headers": {"Authorization": "Bearer a"},
            "action": {"method": "GET", "path": "/x"},
            "control": {"method": "GET", "path": "/y"},
            "forbidden_marker": "m"}}],
    "lifecycle": {"readiness": {"type": "http", "node": "target", "port": 80,
                                "path": "/health", "expected_status": 200}},
}
FIXED_EXPIRY = datetime(2026, 10, 6, tzinfo=timezone.utc)


def _arena_with_recipe(db, name):
    arena = _arena(db, name)
    api._record_lifecycle_recipe(
        name, scenario_name=name, scenario_config=SCENARIO,
        requested_provider="docker-local", expires_at=FIXED_EXPIRY)
    return arena


def _record_verdict(db, arena, finding_id, *, verdict, reason,
                    variant_of=None, research_key=None, validator_version=1,
                    validator_id="http_access_control"):
    db.record_event(arena, "finding", {
        "finding_id": finding_id, "title": finding_id, "cwe": "CWE-639",
        "node": "target", "variant_of": variant_of, "research_key": research_key,
        "validation": {"verdict": verdict, "reason_code": reason,
                       "validator_id": validator_id,
                       "validator_version": validator_version,
                       "action_digest": "sha256:" + "a" * 64,
                       "observation_digest": "sha256:" + "b" * 64,
                       "control_digest": "sha256:" + "c" * 64},
    })


def test_group_outcome_disappeared_under_controls(clients):
    db, operator = clients
    vuln_arena = _arena_with_recipe(db, "group-vuln")
    fixed_arena = _arena_with_recipe(db, "group-fixed")
    _record_verdict(db, vuln_arena, "rootid000001", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000001")
    _record_verdict(db, fixed_arena, "varid0000001", verdict="refuted",
                    reason="access_denied", variant_of="rootid000001",
                    research_key="rootid000001")
    body = operator.get("/findings/rootid000001").json()
    assert body["schema"] == "nidavellir/finding-group/v1"
    assert body["research_key"] == "rootid000001"
    assert [m["arena_id"] for m in body["members"]] == [vuln_arena, fixed_arena]
    assert body["members"][0]["identity"]["known"] is True
    assert body["members"][0]["identity"]["images"]["target"]["image"] == \
        "sha256:" + "a" * 64
    assert "validation_config" not in body["members"][0]["identity"]
    assert body["comparison"] == {
        "outcome": "disappeared_under_controls", "validator_comparable": True,
        "identity_match": "different_recipe",
        "counts": {"confirmed": 1, "refuted": 1, "inconclusive": 0,
                   "infrastructure_failure": 0}}


def test_group_identity_match_same_recipe(clients):
    db, operator = clients
    first = _arena(db, "group-same-1")
    second = _arena(db, "group-same-2")
    for arena in (first, second):
        api._record_lifecycle_recipe(
            arena, scenario_name="variant-shared", scenario_config=SCENARIO,
            requested_provider="docker-local", expires_at=FIXED_EXPIRY)
    _record_verdict(db, first, "rootid000050", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000050")
    _record_verdict(db, second, "varid0000050", verdict="refuted",
                    reason="access_denied", variant_of="rootid000050",
                    research_key="rootid000050")
    assert operator.get("/findings/rootid000050").json()["comparison"][
        "identity_match"] == "same_recipe"


def test_group_outcome_still_observed(clients):
    db, operator = clients
    vuln_arena = _arena_with_recipe(db, "group-still")
    fixed_arena = _arena_with_recipe(db, "group-still2")
    _record_verdict(db, vuln_arena, "rootid000010", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000010")
    _record_verdict(db, fixed_arena, "varid0000010", verdict="confirmed",
                    reason="unauthorized_disclosure", variant_of="rootid000010",
                    research_key="rootid000010")
    assert operator.get("/findings/rootid000010").json()["comparison"]["outcome"] \
        == "still_observed"


def test_group_unknown_without_recipe_or_verdict(clients):
    db, operator = clients
    no_recipe = _arena(db, "group-norecipe")
    _record_verdict(db, no_recipe, "rootid000020", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000020")
    _record_verdict(db, no_recipe, "varid0000020", verdict="refuted",
                    reason="access_denied", variant_of="rootid000020",
                    research_key="rootid000020")
    assert operator.get("/findings/rootid000020").json()["comparison"]["outcome"] \
        == "unknown"
    recipe_arena = _arena_with_recipe(db, "group-noverdict")
    db.record_event(recipe_arena, "finding", {
        "finding_id": "rootid000021", "title": "unverified", "research_key": None})
    assert operator.get("/findings/rootid000021").json()["comparison"]["outcome"] \
        == "unknown"


def test_group_inconclusive_cases(clients):
    db, operator = clients
    arena_a = _arena_with_recipe(db, "group-inc-a")
    arena_b = _arena_with_recipe(db, "group-inc-b")
    _record_verdict(db, arena_a, "rootid000030", verdict="confirmed",
                    reason="unauthorized_disclosure", research_key="rootid000030")
    _record_verdict(db, arena_b, "varid0000030", verdict="refuted",
                    reason="access_denied", variant_of="rootid000030",
                    research_key="rootid000030", validator_version=2)
    assert operator.get("/findings/rootid000030").json()["comparison"]["outcome"] \
        == "inconclusive"
    _record_verdict(db, arena_b, "varid0000031", verdict="infrastructure_failure",
                    reason="probe_failed", variant_of="rootid000030",
                    research_key="rootid000030")
    assert operator.get("/findings/rootid000030").json()["comparison"]["outcome"] \
        == "inconclusive"


def test_group_legacy_root_and_access_control(clients):
    db, operator = clients
    arena = _arena_with_recipe(db, "group-legacy")
    db.record_event(arena, "finding", {"finding_id": "rootid000040",
                                       "title": "legacy root"})
    _record_verdict(db, arena, "varid0000040", verdict="refuted",
                    reason="access_denied", variant_of="rootid000040",
                    research_key="rootid000040")
    body = operator.get("/findings/rootid000040").json()
    assert [m["finding_id"] for m in body["members"]] == \
        ["rootid000040", "varid0000040"]
    assert body["members"][0]["verdict"]["verdict"] is None
    assert operator.get("/findings/doesnotexist").status_code == 404

    agent_key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(agent_key), name="variant-agent", role="agent")
    agent = TestClient(api.app)
    agent.headers["X-API-Key"] = agent_key
    assert agent.get("/findings/rootid000040").status_code == 403
