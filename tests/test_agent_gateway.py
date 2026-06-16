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
        return {
            "status": "active", "scenario": "basic_pentest",
            "outputs": {
                # foothold (has a shell command) + one web target
                "node_jump_name": "cg-x-jump",
                "node_jump_private_ip": "10.0.0.3",
                "node_jump_ssh_command": "docker exec -it cg-x-jump /bin/bash",
                "node_web_name": "cg-x-web",
                "node_web_private_ip": "10.0.0.2",
                "node_web_url": "http://127.0.0.1:32768",
                "node_web_state": "running",
                "lab_networks": ["cyberguard-x-lab"],
            },
        }

    def destroy(self, api_key, instance_id):
        self.calls.append(("destroy", api_key, instance_id))
        return {"status": "accepted"}

    def exec_command(self, api_key, arena_id, node, command, timeout=30):
        self.calls.append(("exec", api_key, arena_id, node, command, timeout))
        return {"node": node, "exit_code": 0, "stdout": f"ran: {command}\n", "stderr": ""}

    def report_finding(self, api_key, arena_id, title, cwe=None, node=None, evidence=None):
        self.calls.append(("report_finding", api_key, arena_id, title, cwe, node))
        return {"recorded": True, "finding_id": "abc123"}

    def list_events(self, api_key, arena_id, limit=100):
        self.calls.append(("list_events", api_key, arena_id, limit))
        return {"events": [
            {"id": 2, "type": "agent_exec", "actor": "agent",
             "payload": {"node": "jump", "command": "whoami", "exit_code": 0}},
            {"id": 1, "type": "status", "actor": "worker",
             "payload": {"from": "pending", "to": "active"}},
        ]}


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


def test_attacker_owns_exec_and_recon_tools():
    atk = Session("k", Stance.attacker)
    assert atk.can_use("run_command")
    assert atk.can_use("list_targets")
    assert atk.can_use("get_topology")
    assert atk.can_use("report_finding")
    # other stances do NOT get the attacker toolset
    assert not Session("k", Stance.defender).can_use("run_command")
    assert not Session("k", Stance.defender).can_use("report_finding")
    assert not Session("k", Stance.mitm).can_use("run_command")
    # the MITM toolset is still unbuilt
    assert not Session("k", Stance.mitm).can_use("query_events")


def test_report_finding_proxies_rest_and_is_gated():
    ctx = _ctx(stance=Stance.attacker)
    out = tools.report_finding(ctx, arena_id="a1", title="SQLi on login",
                               cwe="CWE-89", node="victim")
    assert out["recorded"] is True
    assert ("report_finding", "cg_secret_key", "a1", "SQLi on login", "CWE-89", "victim") \
        in ctx.client.calls
    # a defender session may not report findings
    with pytest.raises(ToolNotAllowed):
        tools.report_finding(_ctx(stance=Stance.defender), arena_id="a1", title="x")


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


def test_tool_call_blocked_when_stance_disallows():
    # A tool that is in no allow-list must be refused for any stance.
    ctx = _ctx(stance=Stance.attacker)
    with pytest.raises(ToolNotAllowed):
        tools._guard(ctx, "delete_everything")


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


def test_unbound_session_registers_exactly_the_lifecycle_tools():
    import asyncio

    from gateway.server import build_server
    from gateway.stances import LIFECYCLE_TOOLS

    mcp = build_server(GatewayConfig(env={"CYBERGUARD_GATEWAY_HOST": "127.0.0.1"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == set(LIFECYCLE_TOOLS)


def test_attacker_session_also_registers_the_attacker_tools():
    import asyncio

    from gateway.server import build_server

    mcp = build_server(GatewayConfig(env={"CYBERGUARD_STANCE": "attacker"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"run_command", "list_targets", "get_topology", "report_finding"} <= names


# --- attacker stance: run_command + recon ------------------------------------


def test_run_command_resolves_the_foothold_and_execs():
    ctx = _ctx(stance=Stance.attacker)
    out = tools.run_command(ctx, "arena-1", "id")
    assert out["exit_code"] == 0
    exec_call = next(c for c in ctx.client.calls if c[0] == "exec")
    # foothold auto-resolved from the arena outputs (the node with a shell cmd)
    assert exec_call[3] == "jump"
    assert exec_call[4] == "id"


def test_run_command_refuses_a_non_foothold_node():
    ctx = _ctx(stance=Stance.attacker)
    # 'web' is a target, not a foothold → attacker scope violation
    with pytest.raises(ToolNotAllowed):
        tools.run_command(ctx, "arena-1", "whoami", node="web")


def test_run_command_charges_the_budget():
    from gateway.tools import BudgetExceeded

    ctx = _ctx(stance=Stance.attacker)
    ctx.step_budget = 1
    tools.run_command(ctx, "arena-1", "echo 1")
    with pytest.raises(BudgetExceeded):
        tools.run_command(ctx, "arena-1", "echo 2")


def test_run_command_is_traced(tmp_path):
    ctx = _ctx(stance=Stance.attacker, trace_dir=str(tmp_path))
    tools.run_command(ctx, "arena-1", "nmap -sV 10.0.0.2")
    line = (tmp_path / "arena-1.jsonl").read_text().strip()
    entry = json.loads(line)
    assert entry["tool"] == "run_command"
    assert entry["args"]["node"] == "jump"
    assert "cg_secret_key" not in line


def test_list_targets_excludes_the_foothold():
    ctx = _ctx(stance=Stance.attacker)
    targets = tools.list_targets(ctx, "arena-1")["targets"]
    names = {t["node"] for t in targets}
    assert names == {"web"}  # 'jump' (foothold) excluded
    assert targets[0]["url"] == "http://127.0.0.1:32768"


def test_get_topology_marks_the_foothold():
    ctx = _ctx(stance=Stance.attacker)
    topo = tools.get_topology(ctx, "arena-1")
    by_node = {n["node"]: n for n in topo["nodes"]}
    assert by_node["jump"]["foothold"] is True
    assert by_node["web"]["foothold"] is False
    assert topo["networks"] == ["cyberguard-x-lab"]


def test_defender_cannot_run_command():
    ctx = _ctx(stance=Stance.defender)
    with pytest.raises(ToolNotAllowed):
        tools.run_command(ctx, "arena-1", "id")


# --- defender stance ---------------------------------------------------------


def test_defender_owns_query_events_and_topology():
    dfn = Session("k", Stance.defender)
    assert dfn.can_use("query_events")
    assert dfn.can_use("get_topology")
    assert not dfn.can_use("list_targets")  # recon-for-attack stays attacker-only


def test_query_events_proxies_and_filters_by_type():
    ctx = _ctx(stance=Stance.defender)
    out = tools.query_events(ctx, "arena-1")
    assert out["arena_id"] == "arena-1" and out["count"] == 2
    assert ("list_events", "cg_secret_key", "arena-1", 100) in ctx.client.calls
    only_exec = tools.query_events(ctx, "arena-1", type="agent_exec")
    assert only_exec["count"] == 1
    assert only_exec["events"][0]["type"] == "agent_exec"


def test_query_events_blocked_for_attacker():
    ctx = _ctx(stance=Stance.attacker)
    with pytest.raises(ToolNotAllowed):
        tools.query_events(ctx, "arena-1")


def test_defender_session_registers_query_events_not_run_command():
    import asyncio

    from gateway.server import build_server
    mcp = build_server(GatewayConfig(env={"CYBERGUARD_STANCE": "defender",
                                          "CYBERGUARD_GATEWAY_HOST": "127.0.0.1"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"query_events", "get_topology"} <= names
    assert "run_command" not in names
