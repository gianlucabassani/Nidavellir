"""
R2 (work order 2026-11-18 phase 2): root-cause fingerprint store and dedup.

A finding's root cause (invariant, owner/lifetime, source, sink, missing check)
is normalised then hashed; the behaviour oracle is kept alongside. In a
research-mode arena a report colliding with an earlier one of the same lineage
is stored as ``duplicate`` (same oracle) or ``variant`` (different oracle) with
the related finding id, and a duplicate can never be confirmed.
"""
import pytest

import api
import research_integrity as ri
from tests.research_support import active_arena, bind, client

BASE = {
    "invariant": "Only the owner may delete a resource",
    "owner_lifetime": "resource owned by creating user for its whole lifetime",
    "source": "DELETE /api/item/{id} handled by ItemController.deleteItem",
    "sink": "ItemStore.removeById at ItemStore.java:212",
    "missing_check": "no owner comparison before removeById",
    "oracle": "victim item returns 404 after attacker DELETE",
}


def _fp(parts):
    return ri.fingerprint(parts)["fingerprint"]


# --- normalisation (pure) ------------------------------------------------------

def test_identical_parts_collide():
    assert _fp(BASE) == _fp(dict(BASE))


def test_renamed_and_backported_variant_collides():
    """Same root cause written for a backport: different casing and naming
    style, other line numbers, a version string and an address."""
    backport = {
        "invariant": "only the OWNER may delete a resource.",
        "owner_lifetime": "Resource owned by creating-user for its whole lifetime (v11.0.2)",
        "source": "delete /api/item/{id} handled by item_controller.delete_item",
        "sink": "item_store.remove_by_id at itemstore.java line 198",
        "missing_check": "No owner comparison before remove_by_id @ 0x7f3a2c",
        "oracle": BASE["oracle"],
    }
    assert _fp(backport) == _fp(BASE)


def test_genuinely_different_parts_do_not_collide():
    for name, value in (("sink", "AuditLog.append"),
                        ("missing_check", "no CSRF token check before removeById"),
                        ("invariant", "only admins may delete a resource")):
        assert _fp({**BASE, name: value}) != _fp(BASE), name


def test_oracle_is_outside_the_fingerprint():
    other = ri.fingerprint({**BASE, "oracle": "500 error leaks stack trace"})
    assert other["fingerprint"] == _fp(BASE)
    assert other["oracle_digest"] != ri.fingerprint(BASE)["oracle_digest"]


# --- API ---------------------------------------------------------------------------

@pytest.fixture()
def operator():
    return client("operator")


@pytest.fixture()
def agent():
    return client("agent")


def _research_arena(operator, agent, lineage=None):
    arena = active_arena()
    bind(operator, arena, agent)
    r = operator.post(f"/arenas/{arena}/research-mode",
                      json={"enabled": True, "reason": "t", "lineage": lineage})
    assert r.status_code == 200
    return arena


def _report(c, arena, root_cause=BASE, title="Owner check missing"):
    body = {"title": title}
    if root_cause is not None:
        body["root_cause"] = root_cause
    return c.post(f"/arenas/{arena}/findings", json=body)


def _finding(arena, finding_id):
    from database import Database
    for event in Database().list_events(arena, limit=None, types=("finding",)):
        if event["payload"]["finding_id"] == finding_id:
            return event["payload"]
    raise AssertionError(finding_id)


def test_research_mode_requires_root_cause(operator, agent):
    arena = _research_arena(operator, agent)
    r = _report(agent, arena, root_cause=None)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "root_cause_required"


def test_duplicate_variant_independent_are_recorded_with_related_id(operator, agent):
    arena = _research_arena(operator, agent)
    first = _report(agent, arena).json()["finding_id"]
    assert _finding(arena, first)["dedup"]["relation"] == "independent"

    dup = _report(agent, arena, title="IDOR on delete (renamed)").json()["finding_id"]
    dup_payload = _finding(arena, dup)
    assert dup_payload["dedup"]["relation"] == "duplicate"
    assert dup_payload["dedup"]["related_finding_id"] == first
    assert dup_payload["research_key"] == first

    var = _report(agent, arena, {**BASE, "oracle": "audit log shows foreign delete"}).json()
    assert _finding(arena, var["finding_id"])["dedup"] == {
        "relation": "variant", "related_finding_id": first,
        "lineage": f"arena:{arena}"}

    other = _report(agent, arena, {**BASE, "sink": "AuditLog.append"}).json()
    assert _finding(arena, other["finding_id"])["dedup"]["relation"] == "independent"


def test_backport_in_another_arena_of_the_same_lineage_collides(operator, agent):
    lineage = f"prog-{api.uuid.uuid4().hex[:6]}"
    vulnerable = _research_arena(operator, agent, lineage)
    backport = _research_arena(operator, agent, lineage)
    unrelated = _research_arena(operator, agent)
    first = _report(agent, vulnerable).json()["finding_id"]
    renamed = {**BASE, "source": "delete /api/item/{id} handled by item_controller.delete_item",
               "sink": "item_store.remove_by_id at ItemStore.java:198"}
    again = _report(agent, backport, renamed).json()["finding_id"]
    assert _finding(backport, again)["dedup"]["related_finding_id"] == first
    alone = _report(agent, unrelated).json()["finding_id"]
    assert _finding(unrelated, alone)["dedup"]["relation"] == "independent"


def test_duplicate_cannot_be_confirmed(operator, agent):
    arena = _research_arena(operator, agent)
    _report(agent, arena)
    dup = _report(agent, arena).json()["finding_id"]
    r = operator.post(f"/arenas/{arena}/findings/{dup}/verify",
                      json={"verdict": "confirmed", "evidence_digest": "sha256:" + "0" * 64})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "duplicate_finding"


def test_duplicate_auto_confirmation_is_downgraded(operator, agent, monkeypatch):
    monkeypatch.setattr(api, "_validate_finding",
                        lambda record, req, vuln: {"confirmed": True, "method": "test"})
    from tests.test_r3_causality_gate import _causality
    arena = _research_arena(operator, agent)
    # Complete R3 causality, so only the duplicate rule can withhold confirmation.
    complete = {"title": "t", "root_cause": BASE, "causality": _causality(arena)}
    first = agent.post(f"/arenas/{arena}/findings", json=complete).json()["finding_id"]
    assert _finding(arena, first)["validation"]["confirmed"] is True
    dup = agent.post(f"/arenas/{arena}/findings",
                     json={**complete, "causality": _causality(arena)}).json()["finding_id"]
    validation = _finding(arena, dup)["validation"]
    assert validation["confirmed"] is False
    assert validation["verdict"] == "unverified"
    assert validation["reason_code"] == "duplicate_finding"
    assert validation["duplicate_of"] == first


def test_dedup_lookup_before_probing(operator, agent):
    arena = _research_arena(operator, agent)
    empty = agent.post(f"/arenas/{arena}/dedup/lookup", json=BASE).json()
    assert empty["relation"] == "independent" and empty["matches"] == []
    first = _report(agent, arena, title="SECRET TITLE").json()["finding_id"]
    hit = agent.post(f"/arenas/{arena}/dedup/lookup", json=BASE)
    assert hit.status_code == 200
    body = hit.json()
    assert body["relation"] == "duplicate" and body["related_finding_id"] == first
    assert body["matches"] == [{"finding_id": first, "arena_id": arena,
                                "reported_at": body["matches"][0]["reported_at"],
                                "relation": "duplicate"}]
    assert "SECRET TITLE" not in hit.text
    variant = agent.post(f"/arenas/{arena}/dedup/lookup",
                         json={**BASE, "oracle": "different behaviour"}).json()
    assert variant["relation"] == "variant"


def test_dedup_lookup_needs_research_mode_for_agents(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    r = agent.post(f"/arenas/{arena}/dedup/lookup", json=BASE)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "research_mode_off"
    assert operator.post(f"/arenas/{arena}/dedup/lookup", json=BASE).status_code == 200
    outsider = client("agent")
    assert outsider.post(f"/arenas/{arena}/dedup/lookup", json=BASE).status_code == 403


def test_mode_off_stores_fingerprint_but_no_relation(operator, agent):
    arena = active_arena()
    bind(operator, arena, agent)
    assert _report(agent, arena, root_cause=None).status_code == 200
    fid = _report(agent, arena).json()["finding_id"]
    payload = _finding(arena, fid)
    assert payload["root_cause"]["fingerprint"] == _fp(BASE)
    assert "dedup" not in payload
