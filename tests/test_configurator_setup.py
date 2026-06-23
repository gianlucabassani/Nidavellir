"""
Configurator setup phase — increment 1 (ADR-0007 / P2-10), the operator-scripted
AI-optional path. The orchestrator is the enforcement point: consent (operator-only
start), victim-scope (no foothold/attacker nodes), time-box (auto-revoke on
expiry), step budget, and full audit via setup_session/setup_step/setup_finished
events. No gateway/AI here.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


def _client(role, name=None):
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name or f"{role}-cfg", role=role)
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


@pytest.fixture()
def operator():
    return _client("operator", name="op-cfg")


@pytest.fixture()
def agent():
    return _client("agent", name="agent-cfg")


def _arena(iid):
    """An active arena with a victim node + a kali foothold (the foothold gets a
    shell command, so victim scope = {victim})."""
    from database import Database

    db = Database()
    db.create_deployment(iid, iid, "container_web_pentest", provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    db.update_deployment(
        iid, status="active",
        outputs={
            "node_victim_name": "cg-victim",
            "node_kali_name": "cg-kali",
            "node_kali_ssh_command": "docker exec -it cg-kali bash",
        },
        actor="test",
    )
    # D1: the configurator agent (key="agent-cfg") must be bound to drive setup.
    # (The agent_name-at-setup/start grant path is covered in test_agent_binding.)
    db.record_event(
        iid, "agent_binding",
        {"agent_name": "agent-cfg", "stance": "configurator"}, actor="test",
    )
    return iid


def test_start_defaults_to_victim_scope(operator):
    _arena("cfg-scope")
    r = operator.post("/arenas/cfg-scope/setup/start", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["started"] is True
    assert body["nodes"] == ["victim"]          # kali (foothold) excluded
    assert body["egress_enforced"] is False


def test_start_rejects_foothold_in_scope(operator):
    _arena("cfg-foot")
    r = operator.post("/arenas/cfg-foot/setup/start", json={"nodes": ["kali"]})
    assert r.status_code == 422
    assert "victim-scoped" in r.text or "foothold" in r.text


def test_start_rejects_unknown_node(operator):
    _arena("cfg-unknown")
    r = operator.post("/arenas/cfg-unknown/setup/start", json={"nodes": ["ghost"]})
    assert r.status_code == 422


def test_start_requires_active_arena(operator):
    from database import Database

    Database().create_deployment("cfg-pending", "cfg-pending", "x", actor="test")
    r = operator.post("/arenas/cfg-pending/setup/start", json={})
    assert r.status_code == 409


def test_double_session_rejected(operator):
    _arena("cfg-double")
    assert operator.post("/arenas/cfg-double/setup/start", json={}).status_code == 200
    assert operator.post("/arenas/cfg-double/setup/start", json={}).status_code == 409


def test_step_runs_and_decrements_budget(operator):
    _arena("cfg-step")
    operator.post("/arenas/cfg-step/setup/start", json={"command_budget": 3})
    r = operator.post("/arenas/cfg-step/setup/step", json={"node": "victim", "command": "echo hi"})
    assert r.status_code == 200, r.text
    assert r.json()["ran"] is True
    assert r.json()["budget_remaining"] == 2
    status = operator.get("/arenas/cfg-step/setup").json()
    assert status["open"] is True and status["steps_run"] == 1


def test_step_rejects_node_out_of_scope(operator):
    _arena("cfg-oob")
    operator.post("/arenas/cfg-oob/setup/start", json={})
    r = operator.post("/arenas/cfg-oob/setup/step", json={"node": "kali", "command": "id"})
    assert r.status_code == 403
    assert "victim scope" in r.text


def test_step_without_session_rejected(operator):
    _arena("cfg-nosess")
    r = operator.post("/arenas/cfg-nosess/setup/step", json={"node": "victim", "command": "id"})
    assert r.status_code == 409


def test_budget_exhausted(operator):
    _arena("cfg-budget")
    operator.post("/arenas/cfg-budget/setup/start", json={"command_budget": 1})
    assert operator.post("/arenas/cfg-budget/setup/step", json={"node": "victim", "command": "a"}).status_code == 200
    r = operator.post("/arenas/cfg-budget/setup/step", json={"node": "victim", "command": "b"})
    assert r.status_code == 429


def test_expired_session_autocloses(operator):
    from database import Database

    _arena("cfg-exp")
    past = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    Database().record_event(
        "cfg-exp", "setup_session",
        {"session_id": "expired1", "started_at": past, "expires_at": past,
         "nodes": ["victim"], "command_budget": 50, "setup_egress": False, "actor": "op-cfg"},
        actor="op-cfg",
    )
    r = operator.post("/arenas/cfg-exp/setup/step", json={"node": "victim", "command": "id"})
    assert r.status_code == 409 and "expired" in r.text
    # auto-closed: a fresh status reports no open session
    assert operator.get("/arenas/cfg-exp/setup").json()["open"] is False


def test_finish_closes_and_blocks_further_steps(operator):
    _arena("cfg-finish")
    operator.post("/arenas/cfg-finish/setup/start", json={})
    fin = operator.post("/arenas/cfg-finish/setup/finish")
    assert fin.status_code == 200 and fin.json()["finished"] is True
    assert operator.get("/arenas/cfg-finish/setup").json()["open"] is False
    assert operator.post("/arenas/cfg-finish/setup/step", json={"node": "victim", "command": "id"}).status_code == 409
    # finishing again is a no-op, not an error
    assert operator.post("/arenas/cfg-finish/setup/finish").json()["finished"] is False


def test_steps_are_audited(operator):
    from database import Database

    _arena("cfg-audit")
    operator.post("/arenas/cfg-audit/setup/start", json={})
    operator.post("/arenas/cfg-audit/setup/step", json={"node": "victim", "command": "whoami"})
    operator.post("/arenas/cfg-audit/setup/finish")
    types = [e["type"] for e in Database().list_events("cfg-audit", limit=50)]
    assert "setup_session" in types and "setup_step" in types and "setup_finished" in types


def test_setup_egress_open_close_lifecycle(operator, monkeypatch):
    import providers.mock as mock_module

    calls = []

    def spy(self, instance_id, node, open):
        calls.append((node, open))
        return {"success": True, "egress": "open" if open else "closed"}

    monkeypatch.setattr(mock_module.MockProvider, "set_node_egress", spy)
    _arena("cfg-egress")
    r = operator.post("/arenas/cfg-egress/setup/start", json={"setup_egress": True})
    assert r.status_code == 200 and r.json()["egress_enforced"] is True
    assert ("victim", True) in calls                       # opened on start
    assert operator.get("/arenas/cfg-egress/setup").json()["egress_enforced"] is True
    operator.post("/arenas/cfg-egress/setup/finish")
    assert ("victim", False) in calls                      # closed on finish


def test_setup_egress_unsupported_provider_is_501_and_rolls_back(operator, monkeypatch):
    import providers.mock as mock_module

    def boom(self, *a, **k):
        raise NotImplementedError("vm provider can't toggle egress")

    monkeypatch.setattr(mock_module.MockProvider, "set_node_egress", boom)
    _arena("cfg-egress-bad")
    r = operator.post("/arenas/cfg-egress-bad/setup/start", json={"setup_egress": True})
    assert r.status_code == 501
    # rolled back — no dangling open session
    assert operator.get("/arenas/cfg-egress-bad/setup").json()["open"] is False


def test_reaper_revokes_lapsed_setup_egress(monkeypatch):
    import setup_phase
    import tasks
    from database import Database

    db = Database()
    iid = "cfg-reap-egress"
    db.create_deployment(iid, iid, "x", provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    db.update_deployment(iid, status="active", outputs={"node_victim_name": "v"}, actor="test")
    past = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
    db.record_event(
        iid, "setup_session",
        {"session_id": "reap1", "started_at": past, "expires_at": past,
         "nodes": ["victim"], "command_budget": 50, "setup_egress": True, "actor": "op"},
        actor="op",
    )

    calls = []
    import providers.mock as mock_module
    monkeypatch.setattr(
        mock_module.MockProvider, "set_node_egress",
        lambda self, i, n, o: (calls.append((n, o)), {"success": True})[1],
    )
    revoked = tasks._revoke_expired_setup_egress(db, datetime.now())
    assert revoked >= 1
    assert ("victim", False) in calls
    # the lapsed session is now closed
    assert setup_phase.current_session(db.list_events(iid, limit=100)) is None


def test_setup_controls_are_operator_only(agent):
    # The operator's controls reject an agent key; the configurator *tools*
    # (brief/propose/await/run/upload/finish) are agent-callable (gated by session).
    _arena("cfg-authz")
    assert agent.post("/arenas/cfg-authz/setup/start", json={}).status_code == 403
    assert agent.get("/arenas/cfg-authz/setup").status_code == 403
    assert agent.post("/arenas/cfg-authz/setup/step", json={"node": "victim", "command": "id"}).status_code == 403
    assert agent.get("/arenas/cfg-authz/setup/proposals").status_code == 403
    assert agent.post("/arenas/cfg-authz/setup/proposals/x/approve").status_code == 403
    assert agent.post("/arenas/cfg-authz/setup/proposals/x/reject").status_code == 403


# --- increment 2: HITL (propose / approve / await) --------------------------

def test_hitl_propose_approve_await_flow(operator, agent):
    _arena("cfg-hitl")
    operator.post("/arenas/cfg-hitl/setup/start", json={"mode": "hitl", "command_budget": 5})
    pr = agent.post(
        "/arenas/cfg-hitl/setup/propose",
        json={"node": "victim", "command": "echo build", "rationale": "build the app"},
    )
    assert pr.status_code == 200
    step_id = pr.json()["step_id"]
    # await → pending; nothing ran yet
    assert agent.get(f"/arenas/cfg-hitl/setup/proposals/{step_id}").json()["status"] == "pending"
    assert operator.get("/arenas/cfg-hitl/setup").json()["steps_run"] == 0
    # operator sees it in the pending list, then approves → it runs
    pend = operator.get("/arenas/cfg-hitl/setup/proposals").json()["pending"]
    assert any(p["step_id"] == step_id for p in pend)
    ap = operator.post(f"/arenas/cfg-hitl/setup/proposals/{step_id}/approve")
    assert ap.status_code == 200 and ap.json()["approved"] is True
    # await now reports approved with the captured result; budget consumed
    st = agent.get(f"/arenas/cfg-hitl/setup/proposals/{step_id}").json()
    assert st["status"] == "approved" and st["exit_code"] == 0
    assert operator.get("/arenas/cfg-hitl/setup").json()["steps_run"] == 1


def test_hitl_reject_never_runs(operator, agent):
    _arena("cfg-reject")
    operator.post("/arenas/cfg-reject/setup/start", json={"mode": "hitl"})
    step_id = agent.post(
        "/arenas/cfg-reject/setup/propose", json={"node": "victim", "command": "rm -rf /"}
    ).json()["step_id"]
    assert operator.post(f"/arenas/cfg-reject/setup/proposals/{step_id}/reject").status_code == 200
    assert agent.get(f"/arenas/cfg-reject/setup/proposals/{step_id}").json()["status"] == "rejected"
    assert operator.get("/arenas/cfg-reject/setup").json()["steps_run"] == 0
    # a decided proposal can't be approved
    assert operator.post(f"/arenas/cfg-reject/setup/proposals/{step_id}/approve").status_code == 409


def test_propose_requires_hitl_mode(operator, agent):
    _arena("cfg-pmode")
    operator.post("/arenas/cfg-pmode/setup/start", json={})  # operator mode
    assert agent.post(
        "/arenas/cfg-pmode/setup/propose", json={"node": "victim", "command": "id"}
    ).status_code == 409


def test_propose_out_of_scope_rejected(operator, agent):
    _arena("cfg-pscope")
    operator.post("/arenas/cfg-pscope/setup/start", json={"mode": "hitl"})
    assert agent.post(
        "/arenas/cfg-pscope/setup/propose", json={"node": "kali", "command": "id"}
    ).status_code == 403


def test_setup_brief_and_upload(operator, agent):
    import base64

    _arena("cfg-brief")
    operator.post("/arenas/cfg-brief/setup/start", json={"mode": "hitl"})
    brief = agent.get("/arenas/cfg-brief/setup/brief").json()
    assert brief["victim_nodes"] == ["victim"] and brief["mode"] == "hitl"
    content = base64.b64encode(b"hello config").decode()
    up = agent.post(
        "/arenas/cfg-brief/setup/upload",
        json={"node": "victim", "path": "/app/config.env", "content_b64": content},
    )
    assert up.status_code == 200 and up.json()["uploaded"] is True and up.json()["bytes"] == 12


def test_finish_is_callable_by_the_configurator_agent(operator, agent):
    _arena("cfg-finagent")
    operator.post("/arenas/cfg-finagent/setup/start", json={"mode": "hitl"})
    assert agent.post("/arenas/cfg-finagent/setup/finish").json()["finished"] is True


# --- increment 3: autonomous behind the double lock -------------------------

def test_autonomous_blocked_without_platform_flag(operator):
    _arena("cfg-auto-off")
    r = operator.post("/arenas/cfg-auto-off/setup/start", json={"mode": "autonomous"})
    assert r.status_code == 403 and "platform policy" in r.text


def test_autonomous_run_with_double_lock(operator, agent, monkeypatch):
    import config

    monkeypatch.setattr(config, "ALLOW_AUTONOMOUS_CONFIGURATOR", True)
    _arena("cfg-auto-on")
    s = operator.post("/arenas/cfg-auto-on/setup/start", json={"mode": "autonomous", "command_budget": 3})
    assert s.status_code == 200 and s.json()["mode"] == "autonomous"
    r = agent.post("/arenas/cfg-auto-on/setup/run", json={"node": "victim", "command": "make"})
    assert r.status_code == 200 and r.json()["ran"] is True
    assert operator.get("/arenas/cfg-auto-on/setup").json()["steps_run"] == 1


def test_run_requires_autonomous_mode(operator, agent, monkeypatch):
    import config

    monkeypatch.setattr(config, "ALLOW_AUTONOMOUS_CONFIGURATOR", True)
    _arena("cfg-run-mode")
    operator.post("/arenas/cfg-run-mode/setup/start", json={"mode": "hitl"})
    assert agent.post(
        "/arenas/cfg-run-mode/setup/run", json={"node": "victim", "command": "id"}
    ).status_code == 409


def test_run_rejects_out_of_scope_even_in_autonomous(operator, agent, monkeypatch):
    import config

    monkeypatch.setattr(config, "ALLOW_AUTONOMOUS_CONFIGURATOR", True)
    _arena("cfg-run-scope")
    operator.post("/arenas/cfg-run-scope/setup/start", json={"mode": "autonomous"})
    assert agent.post(
        "/arenas/cfg-run-scope/setup/run", json={"node": "kali", "command": "id"}
    ).status_code == 403
