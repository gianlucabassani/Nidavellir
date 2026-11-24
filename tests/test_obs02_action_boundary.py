"""OBS-02 (FR-11): one declared action boundary instead of path matching.

The budgeted route set now comes from ``@action`` declarations. It must equal
the set the old ``_budgeted_path`` middleware charged (frozen below, derived from
that function on 2026-11-24). Every call by an authenticated principal yields
exactly one span, refusals included; budget contracts are unchanged.
"""
import uuid
from datetime import datetime, timedelta

import actions
import api
from database import Database
from tests.research_support import active_arena, bind, client

FROZEN_BUDGETED_ROUTES = {
    "/arenas/{instance_id}/browser/visit",
    "/arenas/{instance_id}/exec",
    "/arenas/{instance_id}/files/download",
    "/arenas/{instance_id}/files/upload",
    "/arenas/{instance_id}/findings",
    "/arenas/{instance_id}/findings/manual",
    "/arenas/{instance_id}/findings/{finding_id}/verify",
    "/arenas/{instance_id}/http/request",
    "/arenas/{instance_id}/http/transactions/{digest}/replay",
    "/arenas/{instance_id}/mitm/observe",
    "/arenas/{instance_id}/setup/generate-proposals",
    "/arenas/{instance_id}/setup/proposals/{step_id}/approve",
    "/arenas/{instance_id}/setup/propose",
    "/arenas/{instance_id}/setup/run",
    "/arenas/{instance_id}/setup/step",
    "/arenas/{instance_id}/setup/upload",
    "/arenas/{instance_id}/workspaces/{workspace_node}/patch-artifacts",
}


def test_declared_budgeted_routes_equal_the_frozen_list():
    declared = actions.declared(api.app)
    assert {path for method, path, spec in declared if spec.budgeted} == FROZEN_BUDGETED_ROUTES
    assert {method for method, _, _ in declared} == {"POST"}
    assert not hasattr(api, "_budgeted_path")


def _spans(arena):
    return Database().list_spans(arena_id=arena)


def _limit(arena, cap):
    Database().revise_budget_policy(arena, action_cap=cap,
                                    deadline=datetime.now() + timedelta(minutes=30),
                                    actor="operator", reason="obs02")


def test_one_span_per_call_including_budget_refusals():
    operator = client("operator")
    arena = active_arena()
    _limit(arena, 1)
    command = {"node": "victim", "command": "id"}
    ok = operator.post(f"/arenas/{arena}/exec", json=command)
    refused = operator.post(f"/arenas/{arena}/exec", json=command)
    assert (ok.status_code, refused.status_code) == (200, 429)
    assert ok.headers.get("X-Action-ID")
    rows = _spans(arena)
    assert [(r["name"], r["status"]) for r in rows] == [("exec", "ok"), ("exec", "budget_refused")]
    assert rows[0]["attrs"]["nv.budget_action_id"] == ok.headers["X-Action-ID"]
    assert rows[0]["actor"] == operator.name and rows[0]["actor_kind"] == "human"
    assert rows[0]["input_digest"] and rows[0]["output_digest"]
    assert '"command":"id"' in rows[0]["input_preview"]


def test_policy_refusals_and_route_errors_are_spans_too():
    operator, agent, stranger = client("operator"), client("agent"), client("agent")
    arena = active_arena()
    bind(operator, arena, agent, "attacker")
    assert stranger.post(f"/arenas/{arena}/exec",
                         json={"node": "victim", "command": "id"}).status_code == 403
    assert agent.post(f"/arenas/{arena}/findings/manual",
                      json={"title": "x"}).status_code == 403
    assert operator.post(f"/arenas/{arena}/exec", json={}).status_code == 422
    rows = _spans(arena)
    assert [(r["name"], r["status"], r["actor"]) for r in rows] == [
        ("exec", "denied", stranger.name),
        ("findings/manual", "denied", agent.name),
        ("exec", "error", operator.name),
    ]
    # None of these consumed budget.
    assert operator.get(f"/arenas/{arena}/budget").json()["policy"]["spent"] == 0


def test_agent_span_carries_its_stance_and_the_route_keeps_its_audit_event():
    operator, agent = client("operator"), client("agent")
    arena = active_arena()
    bind(operator, arena, agent, "attacker")
    r = agent.post(f"/arenas/{arena}/findings", json={"title": "IDOR", "node": "victim"})
    assert r.status_code == 200, r.text
    row = _spans(arena)[-1]
    assert (row["name"], row["actor_kind"], row["stance"]) == ("findings", "agent", "attacker")
    events = operator.get(f"/deployments/{arena}/events?type=finding").json()["events"]
    assert len(events) == 1


def test_unauthenticated_calls_and_undeclared_routes_write_no_span():
    from fastapi.testclient import TestClient
    operator = client("operator")
    arena = active_arena()
    assert TestClient(api.app).post(f"/arenas/{arena}/exec", json={}).status_code == 401
    assert operator.post(f"/arenas/{arena}/research-mode",
                         json={"enabled": True}).status_code in (200, 422)
    assert _spans(arena) == []


def test_idempotent_action_key_and_invalid_key_contracts_hold():
    operator = client("operator")
    arena = active_arena()
    command = {"node": "victim", "command": "id"}
    key = f"obs02-{uuid.uuid4().hex}"
    first = operator.post(f"/arenas/{arena}/exec", json=command, headers={"X-Action-Key": key})
    assert first.status_code == 200
    bad = operator.post(f"/arenas/{arena}/exec", json=command, headers={"X-Action-Key": "x"})
    assert bad.status_code == 422 and bad.json()["detail"] == "invalid X-Action-Key"
    capped = operator.post(f"/arenas/{arena}/exec", json=command,
                           headers={"X-Token-Budget": "100"})
    assert capped.status_code == 422
    assert operator.get(f"/arenas/{arena}/budget").json()["policy"]["spent"] == 1
