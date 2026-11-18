"""
R3 (work order 2026-11-18 phase 2): causality gate on confirmation.

In a research-mode arena a finding is confirmed only when its record carries a
trace, a fixed-build (or guard) control and the single toggle, each citing an
immutable evidence digest that resolves. Validation refuses ``confirmed``
without them, naming what is missing, and downgrades an automatic confirmation
to ``unverified``. With research mode off nothing changes.
"""
import uuid

import pytest

import api
import validation_evidence
from tests.research_support import active_arena, bind, client, research_mode
from tests.test_r2_fingerprint_dedup import BASE


@pytest.fixture()
def operator():
    return client("operator")


@pytest.fixture()
def agent():
    return client("agent")


def _evidence(arena):
    return validation_evidence.record(arena, {
        "schema": "nidavellir/validation-observation/v1", "kind": "test",
        "data": {"nonce": uuid.uuid4().hex}})


def _causality(arena, fixed_arena=None, *, omit=()):
    full = {
        "trace": {"summary": "probe on ItemController.deleteItem reaches removeById",
                  "evidence_digest": _evidence(arena)},
        "fixed_build_control": {
            "summary": "same DELETE returns 403 on the fix", "kind": "fixed_build",
            "build": "commit 1a2b3c4",
            "evidence_digest": _evidence(fixed_arena or arena),
            **({"arena_id": fixed_arena} if fixed_arena else {})},
        "toggle": {"summary": "owner check on → 403", "control": "ownerCheck",
                   "evidence_digest": _evidence(arena)},
    }
    return {k: v for k, v in full.items() if k not in omit}


def _report(c, arena, causality=None):
    # A distinct root cause per report, so R2's duplicate rule stays out of the way.
    body = {"title": "Owner check missing",
            "root_cause": {**BASE, "sink": f"ItemStore.remove{uuid.uuid4().hex[:8]}"}}
    if causality is not None:
        body["causality"] = causality
    r = c.post(f"/arenas/{arena}/findings", json=body)
    assert r.status_code == 200, r.text
    return r.json()["finding_id"]


def _confirm(operator, arena, finding_id, **extra):
    return operator.post(f"/arenas/{arena}/findings/{finding_id}/verify",
                         json={"verdict": "confirmed", "evidence_digest": _evidence(arena),
                               **extra})


def _payload(arena, finding_id):
    from database import Database
    for e in Database().list_events(arena, limit=None, types=("finding",)):
        if e["payload"]["finding_id"] == finding_id:
            return e["payload"]
    raise AssertionError(finding_id)


def _research(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    research_mode(operator, arena)
    return arena


def test_confirm_refused_naming_every_missing_part(operator, agent):
    arena = _research(operator, agent)
    bare = _report(agent, arena)
    r = _confirm(operator, arena, bare)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "causality_incomplete" and detail["status"] == "unverified"
    assert detail["missing"] == ["trace", "fixed_build_control", "toggle"]

    partial = _report(agent, arena, _causality(arena, omit=("toggle",)))
    r = _confirm(operator, arena, partial)
    assert r.status_code == 422 and r.json()["detail"]["missing"] == ["toggle"]


def test_complete_causality_confirms(operator, agent):
    arena = _research(operator, agent)
    fid = _report(agent, arena, _causality(arena))
    r = _confirm(operator, arena, fid)
    assert r.status_code == 200 and r.json()["verdict"] == "confirmed"


def test_verifier_may_complete_causality_at_confirmation(operator, agent):
    arena = _research(operator, agent)
    fid = _report(agent, arena, _causality(arena, omit=("fixed_build_control",)))
    late = _causality(arena)["fixed_build_control"]
    r = _confirm(operator, arena, fid, causality={"fixed_build_control": late})
    assert r.status_code == 200, r.text


def test_fixed_build_evidence_from_another_bound_arena(operator, agent):
    arena = _research(operator, agent)
    fixed = active_arena()
    # An agent may cite another arena's evidence only when bound to it.
    with_fixed = _causality(arena, fixed_arena=fixed)
    r = agent.post(f"/arenas/{arena}/findings",
                   json={"title": "t", "root_cause": BASE, "causality": with_fixed})
    assert r.status_code == 422 and r.json()["detail"]["part"] == "fixed_build_control"
    bind(operator, fixed, agent)
    fid = _report(agent, arena, with_fixed)
    assert _confirm(operator, arena, fid).status_code == 200


def test_unresolvable_or_malformed_evidence_is_refused(operator, agent):
    arena = _research(operator, agent)
    ghost = _causality(arena)
    ghost["trace"]["evidence_digest"] = "sha256:" + "f" * 64
    r = agent.post(f"/arenas/{arena}/findings",
                   json={"title": "t", "root_cause": BASE, "causality": ghost})
    assert r.status_code == 422
    assert r.json()["detail"] == {"code": "causality_evidence_unresolved", "part": "trace",
                                  "message": r.json()["detail"]["message"]}
    words = _causality(arena)
    words["toggle"]["evidence_digest"] = "the container showed it"
    r = agent.post(f"/arenas/{arena}/findings",
                   json={"title": "t", "root_cause": BASE, "causality": words})
    assert r.status_code == 422


def test_automatic_confirmation_without_causality_is_downgraded(operator, agent, monkeypatch):
    monkeypatch.setattr(api, "_validate_finding",
                        lambda record, req, vuln: {"confirmed": True, "method": "test"})
    arena = _research(operator, agent)
    bare = _payload(arena, _report(agent, arena))["validation"]
    assert bare["confirmed"] is False and bare["verdict"] == "unverified"
    assert bare["reason_code"] == "causality_incomplete"
    assert bare["missing_causality"] == ["trace", "fixed_build_control", "toggle"]
    complete = _payload(arena, _report(agent, arena, _causality(arena)))
    assert complete["validation"]["confirmed"] is True


def test_complete_causality_keeps_automatic_confirmation(operator, agent, monkeypatch):
    monkeypatch.setattr(api, "_validate_finding",
                        lambda record, req, vuln: {"confirmed": True, "method": "test"})
    arena = _research(operator, agent)
    payload = _payload(arena, _report(agent, arena, _causality(arena)))
    assert payload["validation"]["confirmed"] is True
    assert set(payload["causality"]) == {"trace", "fixed_build_control", "toggle"}


def test_research_mode_off_is_unchanged(operator, agent, monkeypatch):
    monkeypatch.setattr(api, "_validate_finding",
                        lambda record, req, vuln: {"confirmed": True, "method": "test"})
    arena = active_arena()
    bind(operator, arena, agent)
    r = agent.post(f"/arenas/{arena}/findings", json={"title": "plain"})
    fid = r.json()["finding_id"]
    assert _payload(arena, fid)["validation"]["confirmed"] is True
    assert _confirm(operator, arena, fid).status_code == 200
