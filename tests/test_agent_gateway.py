"""
Tests for the MCP agent gateway skeleton (ROADMAP Phase 2, P2-1).

Pins: stance allow-lists gate tool access (and the per-stance execution tools
are intentionally absent in this skeleton); the lifecycle tools proxy the REST
API correctly and trace every call; the REST client forwards the agent key and
surfaces upstream errors; the agent key is never written to a trace; and the
FastMCP server registers exactly the lifecycle tools.
"""
import json

import pytest

from gateway.config import GatewayConfig
from gateway.rest_client import GatewayRestError, RestClient
from gateway.session import GatewayAuthError, Session, session_from_config
from gateway.stances import Stance, allowed_tools, parse_stance
from gateway.tools import GatewayContext, ToolNotAllowed
from gateway import tools


# --- fakes -------------------------------------------------------------------


class _FakeRestClient:
    """Records calls and returns canned responses."""

    def __init__(self):
        self.calls = []

    def list_scenarios(self, api_key):
        self.calls.append(("list_scenarios", api_key))
        return {"scenarios": [{"id": "basic_pentest", "name": "Web App Pentest (VM)",
                               "provider_class": "vm", "nodes": 3}]}

    def deploy(self, api_key, scenario, instance_id, provider=None):
        self.calls.append(("deploy", api_key, scenario, instance_id, provider))
        return {"status": "accepted", "instance_id": "sys-uuid-123"}

    def status(self, api_key, instance_id):
        self.calls.append(("status", api_key, instance_id))
        return {"status": "active", "scenario": "basic_pentest",
                "outputs": {"node_jump_private_ip": "10.0.0.5"}}

    def destroy(self, api_key, instance_id):
        self.calls.append(("destroy", api_key, instance_id))
        return {"status": "accepted"}


def _ctx(stance=Stance.attacker, trace_dir=None, client=None):
    return GatewayContext(
        client=client or _FakeRestClient(),
        session=Session(api_key="cg_secret_key", stance=stance),
        trace_dir=trace_dir,
    )


# --- stances -----------------------------------------------------------------


def test_parse_stance():
    assert parse_stance("attacker") is Stance.attacker
    assert parse_stance(None) is None
    with pytest.raises(ValueError, match="unknown stance"):
        parse_stance("wizard")


def test_lifecycle_tools_allowed_for_every_session():
    for stance in (None, Stance.attacker, Stance.defender, Stance.mitm):
        tools_allowed = allowed_tools(stance)
        assert {"list_scenarios", "deploy_arena", "destroy_arena"} <= tools_allowed


def test_execution_tools_absent_in_skeleton():
    # No stance exposes run_command/observe/etc. yet — that increment is gated.
    assert not Session("k", Stance.attacker).can_use("run_command")
    assert not Session("k", Stance.defender).can_use("query_events")


# --- session auth ------------------------------------------------------------


def test_session_from_config_requires_key():
    with pytest.raises(GatewayAuthError):
        session_from_config(GatewayConfig(env={}))
    s = session_from_config(GatewayConfig(env={"CYBERGUARD_AGENT_KEY": "cg_x",
                                               "CYBERGUARD_STANCE": "defender"}))
    assert s.stance is Stance.defender


def test_agent_id_is_derived_not_the_raw_key():
    s = Session(api_key="cg_supersecret")
    assert s.agent_id.startswith("agent-")
    assert "supersecret" not in s.agent_id


# --- lifecycle tools ---------------------------------------------------------


def test_list_scenarios_proxies_rest():
    ctx = _ctx()
    out = tools.list_scenarios(ctx)
    assert out["scenarios"][0]["id"] == "basic_pentest"
    assert ("list_scenarios", "cg_secret_key") in ctx.client.calls


def test_deploy_arena_returns_canonical_system_id():
    ctx = _ctx()
    out = tools.deploy_arena(ctx, scenario="basic_pentest", provider="docker-local")
    # the orchestrator's response instance_id is the canonical arena id
    assert out["arena_id"] == "sys-uuid-123"
    assert out["name"].startswith("arena-")
    deploy_call = next(c for c in ctx.client.calls if c[0] == "deploy")
    assert deploy_call[2] == "basic_pentest"
    assert deploy_call[4] == "docker-local"


def test_get_briefing_composes_status_scenario_and_roe():
    ctx = _ctx(stance=Stance.attacker)
    brief = tools.get_briefing(ctx, arena_id="sys-uuid-123")
    assert brief["stance"] == "attacker"
    assert brief["status"] == "active"
    assert brief["scenario"]["id"] == "basic_pentest"
    assert any("egress" in r for r in brief["rules_of_engagement"])


def test_tool_call_blocked_when_stance_disallows(monkeypatch):
    # Simulate a future exec tool not in any allow-list.
    ctx = _ctx()
    with pytest.raises(ToolNotAllowed):
        tools._guard(ctx, "run_command")


# --- tracing -----------------------------------------------------------------


def test_calls_are_traced_without_leaking_the_key(tmp_path):
    ctx = _ctx(trace_dir=str(tmp_path))
    tools.deploy_arena(ctx, scenario="basic_pentest")
    trace_file = tmp_path / "sys-uuid-123.jsonl"
    assert trace_file.exists()
    line = trace_file.read_text().strip()
    entry = json.loads(line)
    assert entry["tool"] == "deploy_arena"
    assert entry["agent_id"].startswith("agent-")
    assert "cg_secret_key" not in line  # the raw API key must never be traced


# --- REST client -------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = b"x" if payload is not None or text else b""

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, resp):
        self.resp = resp
        self.last = None

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.last = {"method": method, "url": url, "headers": headers, "json": json}
        return self.resp


def test_rest_client_forwards_key_and_builds_url():
    http = _FakeHttp(_FakeResp(200, {"scenarios": []}))
    client = RestClient("http://orch:8000/", http=http)
    client.list_scenarios("cg_abc")
    assert http.last["url"] == "http://orch:8000/scenarios"
    assert http.last["headers"]["X-API-Key"] == "cg_abc"


def test_rest_client_raises_on_error_status():
    http = _FakeHttp(_FakeResp(404, text="Instance not found"))
    client = RestClient("http://orch:8000", http=http)
    with pytest.raises(GatewayRestError, match="404"):
        client.status("cg_abc", "missing")


# --- server wiring -----------------------------------------------------------


def test_server_registers_exactly_the_lifecycle_tools():
    import asyncio

    from gateway.server import build_server
    from gateway.stances import LIFECYCLE_TOOLS

    mcp = build_server(GatewayConfig(env={"CYBERGUARD_GATEWAY_HOST": "127.0.0.1"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == set(LIFECYCLE_TOOLS)
