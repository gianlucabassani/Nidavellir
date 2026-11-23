"""
R4 (work order 2026-11-18 phase 2): saturation ledger.

Per arena: planned-vs-reviewed coverage, hypotheses by status and sweeps with
source and yield. The yield is derived from the arena's findings that no earlier
sweep counted, excluding R2 duplicates; a yield the sweeper reports is kept as
`reported_yield` and flagged when it disagrees. Two consecutive zero-yield sweeps
with >= 80% planned coverage
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
from tests.test_r2_fingerprint_dedup import BASE

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


def _sweep(c, arena, yield_=None, reviewed=(), planned=(), source="fix-diff"):
    """``yield_`` is the sweeper's reported count; the recorded yield is derived."""
    body = {"source": source, "surfaces_planned": list(planned),
            "surfaces_reviewed": list(reviewed)}
    if yield_ is not None:
        body["yield"] = yield_
    return c.post(f"/arenas/{arena}/sweeps", json=body)


def _find(c, arena, sink="ItemStore.removeById", root_cause=True):
    """Report one finding; distinct ``sink`` values are independent under R2."""
    body = {"title": f"finding at {sink}"}
    if root_cause:
        body["root_cause"] = {**BASE, "sink": sink}
    r = c.post(f"/arenas/{arena}/findings", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["finding_id"]


def test_ledger_records_sweeps_coverage_and_hypotheses(operator, agent):
    arena = _arena(operator, agent)
    hid = agent.post(f"/arenas/{arena}/hypotheses", json=contract()).json()["id"]
    agent.post(f"/arenas/{arena}/hypotheses/{hid}/tested",
               json={"contract_id": hid, "outcome": "refuted"})
    agent.post(f"/arenas/{arena}/hypotheses", json=contract())
    _find(agent, arena, "A.sink")
    _find(agent, arena, "B.sink")
    r = _sweep(agent, arena, 2, reviewed=SURFACES[:3], planned=SURFACES)
    assert r.status_code == 201 and r.json()["shelved_by_this_sweep"] is False
    assert r.json()["sweep"] == {"yield": 2, "yield_source": "derived",
                                 "reported_yield": 2, "yield_disagrees": False}
    ledger = agent.get(f"/arenas/{arena}/research").json()
    assert ledger["status"] == "active" and ledger["research_mode"] is True
    assert ledger["coverage"] == {"planned": 10, "reviewed": 3, "ratio": 0.3}
    assert ledger["hypotheses"] == {"open": 1, "tested": 1, "outcomes": {"refuted": 1}}
    assert ledger["sweeps"][0]["source"] == "fix-diff" and ledger["sweeps"][0]["yield"] == 2


def test_two_zero_yield_sweeps_at_coverage_shelve_and_block(operator, agent):
    arena = _arena(operator, agent)
    hid = agent.post(f"/arenas/{arena}/hypotheses", json=contract(probe_budget=50)).json()["id"]
    _find(agent, arena)
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
    _find(agent, arena)
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
    # The first sweep yields the campaign's findings; two zero-yield sweeps follow.
    assert _sweep(agent, arena, reviewed=SURFACES, planned=SURFACES).json()["sweep"]["yield"] > 0
    _sweep(agent, arena, 0)
    _sweep(agent, arena, 0)
    for c in (agent, operator):
        body = c.get(f"/arenas/{arena}/digest").content
        assert len(body) <= research_digest.MAX_BYTES
        assert json.loads(body)["research"]["status"] == "shelved"


# --- Derived yield (issue #13) ------------------------------------------------------

def test_reported_yield_without_findings_is_flagged_and_cannot_hold_off_shelving(
        operator, agent):
    arena = _arena(operator, agent)
    first = _sweep(agent, arena, 3, reviewed=SURFACES, planned=SURFACES).json()
    assert first["sweep"] == {"yield": 0, "yield_source": "derived",
                              "reported_yield": 3, "yield_disagrees": True}
    assert first["sweeps"][-1]["yield"] == 0 and first["sweeps"][-1]["reported_yield"] == 3
    # A self-reported yield no longer breaks the zero-yield streak.
    assert _sweep(agent, arena, 5).json()["shelved_by_this_sweep"] is True


def test_duplicates_do_not_count_and_nothing_is_counted_twice(operator, agent):
    arena = _arena(operator, agent)
    _find(agent, arena)
    _find(agent, arena)                       # same root cause: R2 duplicate
    _find(agent, arena, "Other.sink")         # independent
    assert _sweep(agent, arena).json()["sweep"]["yield"] == 2
    assert _sweep(agent, arena).json()["sweep"]["yield"] == 0
    _find(agent, arena, "Third.sink")
    assert _sweep(agent, arena).json()["sweep"]["yield"] == 1


def test_findings_without_a_relation_count(operator, agent):
    arena = _arena(operator, agent, mode=False)
    _find(agent, arena, root_cause=False)
    r = _sweep(agent, arena).json()
    assert r["sweep"] == {"yield": 1, "yield_source": "derived"}


def test_findings_in_other_arenas_do_not_count(operator, agent):
    arena, other = _arena(operator, agent), _arena(operator, agent)
    _find(agent, other)
    assert _sweep(agent, arena).json()["sweep"]["yield"] == 0


def _event(id_, type_, **payload):
    return {"id": id_, "type": type_, "payload": payload}


def test_derive_yield_counts_a_late_committed_finding_in_the_next_sweep():
    # Finding f-late got event id 5 before sweep 6 was recorded, but committed
    # after it: sweep 6 did not count it, so the next sweep must.
    events = [_event(6, ri.SWEEP_EVENT, counted_findings=["f-1"]),
              _event(5, ri.FINDING_EVENT, finding_id="f-late"),
              _event(4, ri.FINDING_EVENT, finding_id="f-1")]
    assert ri.derive_yield(events) == ["f-late"]


def test_derive_yield_treats_findings_before_a_legacy_sweep_as_counted():
    events = [_event(9, ri.FINDING_EVENT, finding_id="f-new"),
              _event(7, ri.SWEEP_EVENT, **{"yield": 1}),
              _event(3, ri.FINDING_EVENT, finding_id="f-old")]
    assert ri.derive_yield(events) == ["f-new"]


def test_sweep_payload_keeps_the_reported_count_apart():
    events = [_event(2, ri.FINDING_EVENT, finding_id="f-1",
                     dedup={"relation": ri.DUPLICATE})]
    payload = ri.sweep_payload({"source": "fuzz", "yield": 1, "surfaces_planned": [],
                                "surfaces_reviewed": []}, events)
    assert payload["yield"] == 0 and payload["counted_findings"] == []
    assert payload["reported_yield"] == 1 and payload["yield_disagrees"] is True
