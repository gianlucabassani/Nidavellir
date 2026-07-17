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
                "node_jump_name": "nv-x-jump",
                "node_jump_private_ip": "10.0.0.3",
                "node_jump_ssh_command": "docker exec -it nv-x-jump /bin/bash",
                "node_web_name": "nv-x-web",
                "node_web_private_ip": "10.0.0.2",
                "node_web_url": "http://127.0.0.1:32768",
                "node_web_state": "running",
                "lab_networks": ["nidavellir-x-lab"],
            },
        }

    def destroy(self, api_key, instance_id):
        self.calls.append(("destroy", api_key, instance_id))
        return {"status": "accepted"}

    def exec_command(self, api_key, arena_id, node, command, timeout=30):
        self.calls.append(("exec", api_key, arena_id, node, command, timeout))
        return {"node": node, "exit_code": 0, "stdout": f"ran: {command}\n", "stderr": ""}

    def report_finding(self, api_key, arena_id, title, cwe=None, node=None, evidence=None,
                       path=None, param=None, payload=None, oast_token=None, poc=None):
        self.calls.append(("report_finding", api_key, arena_id, title, cwe, node))
        self.last_finding = {"title": title, "cwe": cwe, "node": node, "evidence": evidence,
                             "path": path, "param": param, "payload": payload,
                             "oast_token": oast_token, "poc": poc}
        return {"recorded": True, "finding_id": "abc123"}

    def announce_agent(self, api_key, arena_id, model, provider, stance=None):
        self.calls.append(("announce_agent", api_key, arena_id, model, provider, stance))
        return {"recorded": True}

    def list_events(self, api_key, arena_id, limit=100):
        self.calls.append(("list_events", api_key, arena_id, limit))
        return {"events": [
            {"id": 2, "type": "agent_exec", "actor": "agent",
             "payload": {"node": "jump", "command": "whoami", "exit_code": 0}},
            {"id": 1, "type": "status", "actor": "worker",
             "payload": {"from": "pending", "to": "active"}},
        ]}

    # configurator stance
    def setup_brief(self, api_key, arena_id):
        self.calls.append(("setup_brief", api_key, arena_id))
        return {"arena_id": arena_id, "mode": "hitl", "victim_nodes": ["web"], "whitebox_source": {}}

    def setup_propose(self, api_key, arena_id, node, command, rationale=""):
        self.calls.append(("setup_propose", api_key, arena_id, node, command, rationale))
        return {"proposed": True, "step_id": "step-1", "status": "pending"}

    def setup_proposal_status(self, api_key, arena_id, step_id):
        self.calls.append(("setup_proposal_status", api_key, arena_id, step_id))
        return {"step_id": step_id, "status": "approved", "exit_code": 0}

    def setup_run(self, api_key, arena_id, node, command, timeout=60):
        self.calls.append(("setup_run", api_key, arena_id, node, command, timeout))
        return {"ran": True, "node": node, "exit_code": 0}

    def setup_upload(self, api_key, arena_id, node, path, content_b64):
        self.calls.append(("setup_upload", api_key, arena_id, node, path, content_b64))
        return {"uploaded": True, "node": node, "path": path, "bytes": 5}

    def setup_finish(self, api_key, arena_id):
        self.calls.append(("setup_finish", api_key, arena_id))
        return {"finished": True}

    # operator stance (authoring)
    def generate_scenario(self, api_key, prompt, provider_class=None):
        self.calls.append(("generate_scenario", api_key, prompt, provider_class))
        return {"valid": True, "spec": {"schema": "nidavellir/v3", "name": "Gen"},
                "topology": {"nodes": []}, "suggested_id": "gen", "warnings": []}

    def import_scenario(self, api_key, spec, scenario_id=None, overwrite=False):
        self.calls.append(("import_scenario", api_key, scenario_id, overwrite))
        return {"status": "imported", "id": scenario_id or "gen"}

    # mitm stance
    def mitm_observe(self, api_key, arena_id, seconds=6, max_packets=200):
        self.calls.append(("mitm_observe", api_key, arena_id, seconds, max_packets))
        return {"success": True, "packets": 1,
                "flows": [{"src": "10.0.0.3", "dst": "10.0.0.2", "proto": "tcp",
                           "sport": 5000, "dport": 80}]}


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


def test_report_finding_forwards_verification_inputs():
    # A3: path/param/payload/oast_token reach the orchestrator so the finding can
    # be ACTIVELY validated, not just passively correlated.
    ctx = _ctx(stance=Stance.attacker)
    tools.report_finding(ctx, arena_id="a1", title="reflected XSS", cwe="CWE-79",
                         node="web", path="/search", param="q",
                         payload="<svg/onload=alert(1)>", oast_token="tok9")
    f = ctx.client.last_finding
    assert f["path"] == "/search" and f["param"] == "q"
    assert f["payload"] == "<svg/onload=alert(1)>" and f["oast_token"] == "tok9"


def test_get_topology_returns_named_nodes():
    # A4 lock: nodes are keyed "node" (not "name") with real names populated —
    # the earlier "null names" was a diagnostic script reading the wrong key.
    ctx = _ctx(stance=Stance.attacker)
    topo = tools.get_topology(ctx, arena_id="a1")
    names = {n["node"] for n in topo["nodes"]}
    assert names == {"jump", "web"}
    assert all(n["node"] for n in topo["nodes"])  # no null names
    web = next(n for n in topo["nodes"] if n["node"] == "web")
    assert web["foothold"] is False and web["url"] == "http://127.0.0.1:32768"


# --- session auth ------------------------------------------------------------


def test_session_from_config_requires_key():
    with pytest.raises(GatewayAuthError):
        session_from_config(GatewayConfig(env={}))
    s = session_from_config(GatewayConfig(env={"NIDAVELLIR_AGENT_KEY": "cg_x",
                                               "NIDAVELLIR_STANCE": "defender"}))
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


def test_announce_agent_proxies_with_the_bound_stance():
    # The harness declares its model/provider; the gateway adds the session stance.
    ctx = _ctx(stance=Stance.attacker)
    out = tools.announce_agent(ctx, arena_id="a1", model="deepseek-chat", provider="deepseek")
    assert out["recorded"] is True
    assert ("announce_agent", "cg_secret_key", "a1", "deepseek-chat", "deepseek", "attacker") \
        in ctx.client.calls


def test_announce_agent_is_lifecycle_grade_for_every_stance():
    for stance in (None, Stance.attacker, Stance.defender, Stance.mitm):
        assert "announce_agent" in allowed_tools(stance)


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
    # OpenInference / OTel-GenAI alignment (ADR-0010): a tool call is a TOOL span.
    assert entry["span_kind"] == "execute_tool"
    assert entry["attributes"]["openinference.span.kind"] == "TOOL"
    assert entry["attributes"]["tool.name"] == "deploy_arena"


def test_trace_span_kind_distinguishes_agent_scope_tools():
    from gateway import trace

    def kind(tool):
        e = _capture_entry(trace, tool)
        return e["span_kind"], e["attributes"]["openinference.span.kind"]

    assert kind("run_command") == ("execute_tool", "TOOL")
    assert kind("report_finding") == ("invoke_agent", "AGENT")
    assert kind("announce_agent") == ("invoke_agent", "AGENT")


def _capture_entry(trace, tool):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = trace.record(d, agent_id="agent-x", stance="attacker", tool=tool,
                            args={}, ok=True, arena_id="arena-1", now=1.0)
        return json.loads(path.read_text().strip())


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

    mcp = build_server(GatewayConfig(env={"NIDAVELLIR_GATEWAY_HOST": "127.0.0.1"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == set(LIFECYCLE_TOOLS)


def test_attacker_session_also_registers_the_attacker_tools():
    import asyncio

    from gateway.server import build_server

    mcp = build_server(GatewayConfig(env={"NIDAVELLIR_STANCE": "attacker"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"run_command", "list_targets", "get_topology", "report_finding"} <= names


def test_mitm_session_registers_observe_tools_only():
    import asyncio

    from gateway.server import build_server

    mcp = build_server(GatewayConfig(env={"NIDAVELLIR_STANCE": "mitm"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"get_topology", "observe_traffic"} <= names
    # no attacker/defender/configurator tools leak onto the mitm surface
    assert not ({"run_command", "report_finding", "query_events",
                 "run_setup_step"} & names)


def test_observe_traffic_proxies_and_is_mitm_only():
    ctx = _ctx(stance=Stance.mitm)
    out = tools.observe_traffic(ctx, arena_id="a1", seconds=4)
    assert out["packets"] == 1 and out["flows"][0]["dport"] == 80
    call = next(c for c in ctx.client.calls if c[0] == "mitm_observe")
    assert call[2] == "a1" and call[3] == 4
    # an attacker session may NOT observe traffic
    with pytest.raises(tools.ToolNotAllowed):
        tools.observe_traffic(_ctx(stance=Stance.attacker), arena_id="a1")


def test_operator_session_registers_authoring_tools_only():
    import asyncio

    from gateway.server import build_server

    mcp = build_server(GatewayConfig(env={"NIDAVELLIR_STANCE": "operator"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    # authoring tools present...
    assert {"scaffold_scenario", "import_scenario"} <= names
    # ...and NONE of the in-arena agent tools leak onto the operator surface
    assert not ({"run_command", "report_finding", "query_events",
                 "run_setup_step"} & names)


def test_authoring_tools_absent_from_agent_stances():
    """scaffold/import must never appear on an attacker/defender/configurator
    session — authoring is an operator privilege."""
    assert not Session("k", Stance.attacker).can_use("scaffold_scenario")
    assert not Session("k", Stance.defender).can_use("import_scenario")
    assert not Session("k", Stance.configurator).can_use("scaffold_scenario")
    assert Session("k", Stance.operator).can_use("scaffold_scenario")
    assert Session("k", Stance.operator).can_use("import_scenario")


def test_scaffold_scenario_proxies_generate_and_traces():
    ctx = _ctx(stance=Stance.operator)
    out = tools.scaffold_scenario(ctx, prompt="a dvwa lab", provider_class="container")
    assert out["valid"] is True and out["spec"]["schema"] == "nidavellir/v3"
    call = next(c for c in ctx.client.calls if c[0] == "generate_scenario")
    assert call[2] == "a dvwa lab" and call[3] == "container"


def test_import_scenario_proxies_and_is_operator_only():
    ctx = _ctx(stance=Stance.operator)
    out = tools.import_scenario(ctx, spec={"schema": "nidavellir/v3"}, scenario_id="my-id")
    assert out["status"] == "imported" and out["id"] == "my-id"
    # an attacker session is blocked at the guard
    with pytest.raises(tools.ToolNotAllowed):
        tools.scaffold_scenario(_ctx(stance=Stance.attacker), prompt="x")


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
    assert topo["networks"] == ["nidavellir-x-lab"]


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
    mcp = build_server(GatewayConfig(env={"NIDAVELLIR_STANCE": "defender",
                                          "NIDAVELLIR_GATEWAY_HOST": "127.0.0.1"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"query_events", "get_topology"} <= names
    assert "run_command" not in names


# --- configurator stance (SUT setup phase) -----------------------------------


def test_configurator_stance_owns_only_setup_tools():
    cfg = Session("k", Stance.configurator)
    for t in ("get_setup_brief", "propose_setup_step", "await_setup_step",
              "run_setup_step", "upload_file", "finish_setup"):
        assert cfg.can_use(t)
    # NO attacker tools — the configurator is victim-scoped, not offensive
    assert not cfg.can_use("run_command")
    assert not cfg.can_use("report_finding")
    # ...and other stances don't get the configurator toolset
    assert not Session("k", Stance.attacker).can_use("run_setup_step")
    assert not Session("k", Stance.defender).can_use("propose_setup_step")


def test_configurator_session_registers_its_tools():
    import asyncio

    from gateway.server import build_server

    mcp = build_server(GatewayConfig(env={"NIDAVELLIR_STANCE": "configurator",
                                          "NIDAVELLIR_GATEWAY_HOST": "127.0.0.1"}))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"get_setup_brief", "propose_setup_step", "await_setup_step",
            "run_setup_step", "upload_file", "finish_setup"} <= names
    # no attacker tools leak into the configurator stance
    assert "run_command" not in names and "report_finding" not in names


def test_configurator_tools_proxy_rest_and_are_gated():
    ctx = _ctx(stance=Stance.configurator)
    assert tools.get_setup_brief(ctx, "a1")["mode"] == "hitl"
    assert tools.propose_setup_step(ctx, "a1", "web", "make", "build")["step_id"] == "step-1"
    assert tools.await_setup_step(ctx, "a1", "step-1")["status"] == "approved"
    assert tools.run_setup_step(ctx, "a1", "web", "make")["ran"] is True
    assert tools.upload_file(ctx, "a1", "web", "/app/x", "aGk=")["uploaded"] is True
    assert tools.finish_setup(ctx, "a1")["finished"] is True
    kinds = {c[0] for c in ctx.client.calls}
    assert {"setup_brief", "setup_propose", "setup_proposal_status",
            "setup_run", "setup_upload", "setup_finish"} <= kinds
    # an attacker session cannot reach a configurator tool
    with pytest.raises(ToolNotAllowed):
        tools.run_setup_step(_ctx(stance=Stance.attacker), "a1", "web", "make")
