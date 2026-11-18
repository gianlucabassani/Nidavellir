"""
R1 (work order 2026-11-18 phase 2): hypothesis contract, registry and probe gate.

A contract missing any required field is refused with the field named; a valid
one is registered and listed with its status; it is marked tested only through
its endpoint with the matching contract id. In a research-mode arena an agent's
probe must cite an open hypothesis with probe budget left; with research mode
off (the default) nothing changes.
"""
import pytest

import research_integrity
from tests.research_support import active_arena, bind, client, contract, research_mode


@pytest.fixture()
def operator():
    return client("operator")


@pytest.fixture()
def agent():
    return client("agent")


def _exec(c, arena, **extra):
    return c.post(f"/arenas/{arena}/exec", json={"node": "victim", "command": "id", **extra})


@pytest.mark.parametrize("field", research_integrity.REQUIRED_FIELDS)
def test_contract_missing_a_field_is_refused_with_the_field_named(operator, agent, field):
    arena = active_arena()
    bind(operator, arena, agent)
    body = contract()
    del body[field]
    r = agent.post(f"/arenas/{arena}/hypotheses", json=body)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_hypothesis"
    assert detail["missing"] == [field]
    assert field in detail["message"]


def test_malformed_and_unknown_fields_are_named(operator):
    arena = active_arena()
    r = operator.post(f"/arenas/{arena}/hypotheses",
                      json=contract(source="vibes", probe_budget=0, extra="x",
                                    source_sink={"source": "a"}))
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert {"source", "probe_budget", "extra", "source_sink.sink"} <= fields
    assert r.json()["detail"]["missing"] == []


def test_empty_preconditions_are_refused(operator):
    arena = active_arena()
    r = operator.post(f"/arenas/{arena}/hypotheses", json=contract(preconditions=[]))
    assert r.status_code == 422
    assert "preconditions" in {e["field"] for e in r.json()["detail"]["errors"]}


def test_valid_contract_is_registered_listed_and_unique(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    body = contract()
    r = agent.post(f"/arenas/{arena}/hypotheses", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "open"
    assert r.json()["contract_digest"].startswith("sha256:")
    listed = agent.get(f"/arenas/{arena}/hypotheses").json()
    assert listed["counts"] == {"open": 1, "tested": 0}
    (view,) = listed["hypotheses"]
    assert view["id"] == body["id"] and view["probes_used"] == 0
    assert view["contract"]["negative_control"] == body["negative_control"]
    again = agent.post(f"/arenas/{arena}/hypotheses", json=body)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "hypothesis_exists"


def test_unbound_or_wrong_stance_agent_cannot_register(operator, agent):
    arena = active_arena()
    assert agent.post(f"/arenas/{arena}/hypotheses", json=contract()).status_code == 403
    bind(operator, arena, agent, stance="defender")
    assert agent.post(f"/arenas/{arena}/hypotheses", json=contract()).status_code == 403


def test_tested_requires_matching_contract_id_and_closes_once(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    hid = agent.post(f"/arenas/{arena}/hypotheses", json=contract()).json()["id"]
    url = f"/arenas/{arena}/hypotheses/{hid}/tested"
    wrong = agent.post(url, json={"contract_id": "H-other", "outcome": "refuted"})
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "contract_id_mismatch"
    unknown = agent.post(f"/arenas/{arena}/hypotheses/H-none/tested",
                         json={"contract_id": "H-none", "outcome": "refuted"})
    assert unknown.status_code == 404
    ok = agent.post(url, json={"contract_id": hid, "outcome": "refuted", "note": "403 twice"})
    assert ok.status_code == 200 and ok.json()["status"] == "tested"
    again = agent.post(url, json={"contract_id": hid, "outcome": "supported"})
    assert again.status_code == 409
    (view,) = agent.get(f"/arenas/{arena}/hypotheses").json()["hypotheses"]
    assert view["status"] == "tested" and view["outcome"] == "refuted"


def test_probe_without_hypothesis_allowed_when_research_mode_off(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    assert _exec(agent, arena).status_code == 200


def test_probe_without_hypothesis_refused_when_research_mode_on(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    research_mode(operator, arena)
    for path, body in (("exec", {"node": "victim", "command": "id"}),
                       ("http/request", {"node": "victim", "path": "/"}),
                       ("browser/visit", {"node": "victim", "path": "/"})):
        r = agent.post(f"/arenas/{arena}/{path}", json=body)
        assert r.status_code == 422, (path, r.text)
        assert r.json()["detail"]["code"] == "hypothesis_required"
    # Operators are not gated; turning the mode off restores the default.
    assert _exec(operator, arena).status_code == 200
    research_mode(operator, arena, enabled=False)
    assert _exec(agent, arena).status_code == 200


def test_probe_citing_hypothesis_spends_budget_then_stops(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    research_mode(operator, arena)
    assert _exec(agent, arena, hypothesis_id="H-ghost").json()["detail"]["code"] \
        == "unknown_hypothesis"
    hid = agent.post(f"/arenas/{arena}/hypotheses",
                     json=contract(probe_budget=2)).json()["id"]
    assert _exec(agent, arena, hypothesis_id=hid).status_code == 200
    assert _exec(agent, arena, hypothesis_id=hid).status_code == 200
    spent = _exec(agent, arena, hypothesis_id=hid)
    assert spent.status_code == 429
    assert spent.json()["detail"]["code"] == "probe_budget_exhausted"
    (view,) = agent.get(f"/arenas/{arena}/hypotheses").json()["hypotheses"]
    assert view["probes_used"] == 2


def test_tested_hypothesis_can_no_longer_be_probed(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    research_mode(operator, arena)
    hid = agent.post(f"/arenas/{arena}/hypotheses", json=contract()).json()["id"]
    agent.post(f"/arenas/{arena}/hypotheses/{hid}/tested",
               json={"contract_id": hid, "outcome": "inconclusive"})
    r = _exec(agent, arena, hypothesis_id=hid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hypothesis_closed"


def test_only_operator_sets_research_mode(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    r = agent.post(f"/arenas/{arena}/research-mode", json={"enabled": False, "reason": "x"})
    assert r.status_code == 403


def test_schema_is_published(agent):
    schema = agent.get("/research/hypothesis-schema").json()
    assert schema["$id"] == research_integrity.HYPOTHESIS_SCHEMA
    assert set(schema["required"]) == set(research_integrity.REQUIRED_FIELDS)
    assert schema["additionalProperties"] is False
