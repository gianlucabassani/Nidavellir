"""
R4 (work order 2026-11-18 phase 2): saturation ledger.

Per arena: planned-vs-reviewed coverage, hypotheses by status and sweeps with
source and yield. Two consecutive zero-yield sweeps with >= 80% planned coverage
shelve the arena's research with the reason and the reopen triggers; shelving
stops new sweeps, hypotheses and research-mode probes until an operator reopens
it on a named new input. The F3 digest carries the ledger within its 2 KB cap.
"""
import json

import pytest

import research_digest
import research_integrity as ri
from tests.research_support import active_arena, bind, client, contract, research_mode
from tests.test_f3_research_digest import TOP_KEYS, _heavy_campaign

SURFACES = [f"/api/s{i}" for i in range(10)]


@pytest.fixture()
def operator():
    return client("operator")


@pytest.fixture()
def agent():
    return client("agent")


def _arena(operator, agent, mode=True):
    arena = active_arena()
    bind(operator, arena, agent)
    if mode:
        research_mode(operator, arena)
    return arena


def _sweep(c, arena, yield_, reviewed=(), planned=(), source="fix-diff"):
    return c.post(f"/arenas/{arena}/sweeps", json={
        "source": source, "yield": yield_, "surfaces_planned": list(planned),
        "surfaces_reviewed": list(reviewed)})


def test_ledger_records_sweeps_coverage_and_hypotheses(operator, agent):
    arena = _arena(operator, agent)
    hid = agent.post(f"/arenas/{arena}/hypotheses", json=contract()).json()["id"]
    agent.post(f"/arenas/{arena}/hypotheses/{hid}/tested",
               json={"contract_id": hid, "outcome": "refuted"})
    agent.post(f"/arenas/{arena}/hypotheses", json=contract())
    r = _sweep(agent, arena, 2, reviewed=SURFACES[:3], planned=SURFACES)
    assert r.status_code == 201 and r.json()["shelved_by_this_sweep"] is False
    ledger = agent.get(f"/arenas/{arena}/research").json()
    assert ledger["status"] == "active" and ledger["research_mode"] is True
    assert ledger["coverage"] == {"planned": 10, "reviewed": 3, "ratio": 0.3}
    assert ledger["hypotheses"] == {"open": 1, "tested": 1, "outcomes": {"refuted": 1}}
    assert ledger["sweeps"][0]["source"] == "fix-diff" and ledger["sweeps"][0]["yield"] == 2


def test_two_zero_yield_sweeps_at_coverage_shelve_and_block(operator, agent):
    arena = _arena(operator, agent)
    hid = agent.post(f"/arenas/{arena}/hypotheses", json=contract(probe_budget=50)).json()["id"]
    _sweep(agent, arena, 1, reviewed=SURFACES[:8], planned=SURFACES)
    assert _sweep(agent, arena, 0).json()["shelved_by_this_sweep"] is False
    second = _sweep(agent, arena, 0, source="fuzz").json()
    assert second["shelved_by_this_sweep"] is True and second["status"] == "shelved"
    assert "2 consecutive zero-yield sweeps at 80% planned coverage" \
        == second["shelved"]["reason"]
    assert second["shelved"]["reopen_on"] == list(ri.REOPEN_TRIGGERS)

    for blocked in (_sweep(agent, arena, 0),
                    agent.post(f"/arenas/{arena}/hypotheses", json=contract()),
                    agent.post(f"/arenas/{arena}/exec",
                               json={"node": "victim", "command": "id",
                                     "hypothesis_id": hid})):
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "research_shelved"


def test_zero_yield_below_coverage_does_not_shelve(operator, agent):
    arena = _arena(operator, agent)
    _sweep(agent, arena, 0, reviewed=SURFACES[:7], planned=SURFACES)
    for _ in range(3):
        assert _sweep(agent, arena, 0).json()["shelved_by_this_sweep"] is False


def test_a_yielding_sweep_breaks_the_streak(operator, agent):
    arena = _arena(operator, agent)
    _sweep(agent, arena, 0, reviewed=SURFACES, planned=SURFACES)
    _sweep(agent, arena, 1)
    assert _sweep(agent, arena, 0).json()["shelved_by_this_sweep"] is False
    assert _sweep(agent, arena, 0).json()["shelved_by_this_sweep"] is True


def test_reopen_needs_operator_and_a_named_trigger(operator, agent):
    arena = _arena(operator, agent)
    url = f"/arenas/{arena}/research/reopen"
    assert operator.post(url, json={"trigger": "new_commit", "detail": "abc"}).status_code == 409
    _sweep(agent, arena, 0, reviewed=SURFACES, planned=SURFACES)
    _sweep(agent, arena, 0)
    assert agent.post(url, json={"trigger": "new_commit", "detail": "abc"}).status_code == 403
    assert operator.post(url, json={"trigger": "boredom", "detail": "x"}).status_code == 422
    r = operator.post(url, json={"trigger": "new_cve", "detail": "CVE-2026-0001"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert r.json()["last_reopened"]["trigger"] == "new_cve"
    # The streak restarts: one zero-yield sweep is not enough to re-shelve.
    assert _sweep(agent, arena, 0).json()["shelved_by_this_sweep"] is False
    assert _sweep(agent, arena, 0).json()["shelved_by_this_sweep"] is True


def test_sweeps_need_an_exec_binding(operator, agent):
    arena = active_arena()
    assert _sweep(agent, arena, 0).status_code == 403
    bind(operator, arena, agent, stance="defender")
    assert _sweep(agent, arena, 0).status_code == 403
    assert agent.get(f"/arenas/{arena}/research").status_code == 200


def test_digest_carries_research_only_when_used(operator, agent):
    plain = _arena(operator, agent, mode=False)
    doc = json.loads(agent.get(f"/arenas/{plain}/digest").content)
    assert set(doc) == TOP_KEYS

    arena = _arena(operator, agent)
    doc = json.loads(agent.get(f"/arenas/{arena}/digest").content)
    assert doc["research"] == {"mode": True, "status": "active", "coverage_pct": 0,
                               "hypotheses": {"open": 0, "tested": 0}, "sweeps": 0,
                               "zero_streak": 0}
    assert doc["next_actions"][0] == "research mode: register_hypothesis before probing"
    _sweep(agent, arena, 0, reviewed=SURFACES, planned=SURFACES)
    _sweep(agent, arena, 0)
    doc = json.loads(agent.get(f"/arenas/{arena}/digest").content)
    assert doc["research"]["status"] == "shelved"
    assert doc["research"]["reopen_on"] == list(ri.REOPEN_TRIGGERS)
    assert doc["next_actions"][0].startswith("research shelved as saturated")


def test_digest_with_research_stays_within_cap(operator, agent):
    arena = _arena(operator, agent)
    _heavy_campaign(arena)
    for i in range(30):
        agent.post(f"/arenas/{arena}/hypotheses", json=contract(id=f"H-{i:03d}"))
    _sweep(agent, arena, 0, reviewed=SURFACES, planned=SURFACES)
    _sweep(agent, arena, 0)
    for c in (agent, operator):
        body = c.get(f"/arenas/{arena}/digest").content
        assert len(body) <= research_digest.MAX_BYTES
        assert json.loads(body)["research"]["status"] == "shelved"
