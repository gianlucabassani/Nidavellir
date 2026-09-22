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

    def transfer_upload(self, api_key, arena_id, path, content_b64, node=None):
        self.calls.append(("transfer_upload", api_key, arena_id, path, node))
        return {"uploaded": True, "node": node or "jump", "path": path, "bytes": 5}

    def transfer_download(
        self, api_key, arena_id, path, node=None, offset=0, max_bytes=262144
    ):
        self.calls.append(
            ("transfer_download", api_key, arena_id, path, node, offset, max_bytes)
        )
        return {
            "node": node or "jump", "path": path, "content_b64": "cHJvb2Y=",
            "returned_bytes": 5, "file_bytes": 5, "next_offset": None,
            "digest": "sha256:" + "a" * 64,
        }

    def browser_visit(self, api_key, arena_id, node, path="/", params=None, wait_ms=1500):
        self.calls.append(("browser_visit", api_key, arena_id, node, path, params, wait_ms))
        return {
            "success": True, "node": node, "title": "Target",
            "rendered_dom": "<html>rendered</html>",
            "dom_sha256": "sha256:" + "b" * 64,
        }

    def http_request(self, api_key, arena_id, node, path="/", params=None,
                     method="GET", headers=None, body=None):
        self.calls.append(
            ("http_request", api_key, arena_id, node, path, params,
             method, headers, body)
        )
        return {
            "success": True, "node": node, "status": 200, "reason": "OK",
            "body": "<html>ok</html>", "body_bytes": 13,
            "body_sha256": "sha256:" + "c" * 64,
            "transaction_digest": "sha256:" + "d" * 64,
        }

    def http_transactions(self, api_key, arena_id, limit=None, offset=0):
        self.calls.append(("http_transactions", api_key, arena_id, limit, offset))
        return {"total": 1, "offset": offset, "limit": limit or 100,
                "transactions": [{"digest": "sha256:" + "d" * 64}]}

    def http_transaction(self, api_key, arena_id, digest):
        self.calls.append(("http_transaction", api_key, arena_id, digest))
        return {"manifest": {"digest": digest},
                "transaction": {"request": {"path": "/"}, "response": {}}}

    def http_replay(self, api_key, arena_id, digest, *, node=None, path=None,
                    params=None, headers=None, method=None, body=None):
        self.calls.append(
            ("http_replay", api_key, arena_id, digest, node, path, params,
             headers, method, body)
        )
        return {
            "success": True, "status": 302, "replay_of": digest,
            "transaction_digest": "sha256:" + "e" * 64,
        }

    def submit_poc(self, api_key, arena_id, source, **options):
        self.calls.append(("submit_poc", api_key, arena_id, source, options))
        return {"created": True, "job": {
            "id": "poc-1", "state": "queued", "input_digest": "sha256:" + "1" * 64,
        }}

    def poc_job(self, api_key, arena_id, job_id):
        self.calls.append(("poc_job", api_key, arena_id, job_id))
        return {"job": {
            "id": job_id, "state": "succeeded", "input_digest": "sha256:" + "1" * 64,
            "result": {"stdout": "proof", "stdout_sha256": "sha256:" + "2" * 64},
        }}

    def cancel_poc(self, api_key, arena_id, job_id):
        self.calls.append(("cancel_poc", api_key, arena_id, job_id))
        return {"job": {"id": job_id, "state": "cancelled"}}

    def report_finding(self, api_key, arena_id, title, cwe=None, node=None, evidence=None,
                       path=None, param=None, payload=None, oast_token=None, poc=None,
                       evidence_artifact_digests=None, transaction_digests=None):
        self.calls.append(("report_finding", api_key, arena_id, title, cwe, node))
        self.last_finding = {"title": title, "cwe": cwe, "node": node, "evidence": evidence,
                             "path": path, "param": param, "payload": payload,
                             "oast_token": oast_token, "poc": poc,
                             "evidence_artifact_digests": evidence_artifact_digests,
                             "transaction_digests": transaction_digests}
        return {"recorded": True, "finding_id": "abc123"}

    def announce_agent(self, api_key, arena_id, model, provider, stance=None):
        self.calls.append(("announce_agent", api_key, arena_id, model, provider, stance))
        return {"recorded": True}

    def list_workspaces(self, api_key, arena_id):
        self.calls.append(("list_workspaces", api_key, arena_id))
        return {"arena_id": arena_id, "workspaces": [
            {"node": "web", "whitebox": True, "writable": False}
        ]}

    def session_preflight(self, api_key, arena_id):
        self.calls.append(("session_preflight", api_key, arena_id))
        return {
            "arena_id": arena_id,
            "status": "passed",
            "ready": True,
            "failed_checks": [],
            "target": {"identity": {"digest": "a" * 40}},
        }

    def workspace_diff(self, api_key, arena_id, node, **options):
        self.calls.append(("workspace_diff", api_key, arena_id, node, options))
        return {
            "success": True, "node": node, "changed_file_count": 1,
            "returned_lines": 2, "diff": "-old\n+new", "next_start_line": None,
        }

    def workspace_patch_artifact(self, api_key, arena_id, node, **options):
        self.calls.append(("workspace_patch_artifact", api_key, arena_id, node, options))
        return {
            "artifact": {"digest": "sha256:" + "a" * 64, "bytes": 12},
            "patch": "-old\n+new\n",
        }

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


def test_attacker_file_transfer_proxies_and_is_stance_gated():
    ctx = _ctx(stance=Stance.attacker)
    uploaded = tools.upload_file(ctx, "a1", None, "payload.bin", "cHJvb2Y=")
    assert uploaded["uploaded"] is True
    downloaded = tools.download_file(ctx, "a1", "payload.bin", offset=0, max_bytes=32)
    assert downloaded["content_b64"] == "cHJvb2Y="
    assert any(call[0] == "transfer_upload" for call in ctx.client.calls)
    assert any(call[0] == "transfer_download" for call in ctx.client.calls)
    with pytest.raises(ToolNotAllowed):
        tools.download_file(_ctx(stance=Stance.defender), "a1", "payload.bin")


def test_headless_browser_proxies_is_budgeted_and_traces_metadata(tmp_path):
    ctx = _ctx(stance=Stance.attacker, trace_dir=str(tmp_path))
    ctx.step_budget = 1
    result = tools.browser_visit(
        ctx, "a1", "web", "/app", {"q": "<script>secret</script>"}, 900
    )
    assert result["title"] == "Target"
    call = next(c for c in ctx.client.calls if c[0] == "browser_visit")
    assert call[3:7] == ("web", "/app", {"q": "<script>secret</script>"}, 900)
    trace_body = (tmp_path / "a1.jsonl").read_text()
    assert '"param_names": ["q"]' in trace_body
    assert "<script>secret</script>" not in trace_body
    with pytest.raises(tools.BudgetExceeded):
        tools.browser_visit(ctx, "a1", "web")
    with pytest.raises(ToolNotAllowed):
        tools.browser_visit(_ctx(stance=Stance.defender), "a1", "web")


def test_http_tools_proxy_are_budgeted_and_trace_metadata_only(tmp_path):
    ctx = _ctx(stance=Stance.attacker, trace_dir=str(tmp_path))
    ctx.step_budget = 4

    sent = tools.http_request(
        ctx, "a1", "web", "/login", {"u": "admin"}, "post",
        {"X-Proof": "1"}, "secret-payload",
    )
    assert sent["transaction_digest"].startswith("sha256:")
    call = next(c for c in ctx.client.calls if c[0] == "http_request")
    assert call[3:9] == (
        "web", "/login", {"u": "admin"}, "post",
        {"X-Proof": "1"}, "secret-payload",
    )

    listed = tools.list_http_transactions(ctx, "a1", limit=5)
    assert listed["total"] == 1
    fetched = tools.get_http_transaction(ctx, "a1", "sha256:" + "d" * 64)
    assert fetched["manifest"]["digest"] == "sha256:" + "d" * 64
    replayed = tools.replay_http_transaction(
        ctx, "a1", "sha256:" + "d" * 64, params={"q": "' OR 1=1"},
    )
    assert replayed["replay_of"] == "sha256:" + "d" * 64
    replay_call = next(c for c in ctx.client.calls if c[0] == "http_replay")
    # only provided overrides cross the boundary
    assert replay_call[6:] == ({"q": "' OR 1=1"}, None, None, None)

    assert ctx.steps_used == 4
    with pytest.raises(tools.BudgetExceeded):
        tools.http_request(ctx, "a1", "web")

    trace_body = (tmp_path / "a1.jsonl").read_text()
    assert '"param_names": ["u", "q"]' in trace_body or '"param_names": ["u"]' in trace_body
    assert '"digest": "sha256:' in trace_body
    for secret in ("admin", "secret-payload", "<script>"):
        assert secret not in trace_body

    for tool_name, fn, args in (
        ("http_request", tools.http_request, ("a1", "web")),
        ("list_http_transactions", tools.list_http_transactions, ("a1",)),
        ("get_http_transaction", tools.get_http_transaction, ("a1", "sha256:" + "0" * 64)),
        ("replay_http_transaction", tools.replay_http_transaction,
         ("a1", "sha256:" + "0" * 64)),
    ):
        with pytest.raises(ToolNotAllowed):
            fn(_ctx(stance=Stance.defender), *args)


def test_report_finding_forwards_verification_inputs():
    # A3: path/param/payload/oast_token reach the orchestrator so the finding can
    # be ACTIVELY validated, not just passively correlated.
    ctx = _ctx(stance=Stance.attacker)
    tools.report_finding(ctx, arena_id="a1", title="reflected XSS", cwe="CWE-79",
                         node="web", path="/search", param="q",
                         payload="<svg/onload=alert(1)>", oast_token="tok9",
                         evidence_artifact_digests=["sha256:" + "a" * 64])
    f = ctx.client.last_finding
    assert f["path"] == "/search" and f["param"] == "q"
    assert f["payload"] == "<svg/onload=alert(1)>" and f["oast_token"] == "tok9"
    assert f["evidence_artifact_digests"] == ["sha256:" + "a" * 64]


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
    assert {"run_command", "list_targets", "get_topology", "report_finding",
            "workspace_status", "workspace_diff", "workspace_patch_artifact",
            "upload_file", "download_file", "browser_visit",
            "http_request", "list_http_transactions",
            "get_http_transaction", "replay_http_transaction", "submit_poc",
            "poc_status", "poc_result", "cancel_poc"} <= names


def test_poc_tools_are_budgeted_stance_gated_and_trace_no_source(tmp_path):
    ctx = _ctx(stance=Stance.attacker, trace_dir=str(tmp_path))
    ctx.step_budget = 1
    result = tools.submit_poc(
        ctx, "a1", "print('source-secret')", target_node="web",
        idempotency_key="mcp-poc-key",
    )
    assert result["job"]["id"] == "poc-1"
    assert tools.poc_status(ctx, "a1", "poc-1")["job"]["state"] == "succeeded"
    assert tools.poc_result(ctx, "a1", "poc-1")["job"]["result"]["stdout"] == "proof"
    assert tools.cancel_poc(ctx, "a1", "poc-1")["job"]["state"] == "cancelled"
    trace = (tmp_path / "a1.jsonl").read_text()
    assert "source-secret" not in trace
    with pytest.raises(tools.BudgetExceeded):
        tools.submit_poc(ctx, "a1", "print(2)")
    with pytest.raises(ToolNotAllowed):
        tools.submit_poc(_ctx(stance=Stance.defender), "a1", "print(2)")


def test_workspace_tools_proxy_and_are_stance_gated():
    ctx = _ctx(stance=Stance.attacker)
    assert tools.workspace_status(ctx, "a1")["workspaces"][0]["node"] == "web"
    result = tools.workspace_diff(
        ctx, "a1", "web", path="src/app.py", start_line=300, max_lines=100
    )
    assert result["changed_file_count"] == 1
    call = next(c for c in ctx.client.calls if c[0] == "workspace_diff")
    assert call[3] == "web"
    assert call[4]["path"] == "src/app.py" and call[4]["start_line"] == 300
    artifact = tools.workspace_patch_artifact(
        ctx, "a1", "web", path="src/app.py", include_untracked_paths=["notes.txt"]
    )
    assert artifact["artifact"]["digest"].startswith("sha256:")
    patch_call = next(c for c in ctx.client.calls if c[0] == "workspace_patch_artifact")
    assert patch_call[4]["include_untracked_paths"] == ["notes.txt"]
    with pytest.raises(ToolNotAllowed):
        tools.workspace_status(_ctx(stance=Stance.defender), "a1")


def test_session_preflight_is_shared_and_traced():
    for stance in (Stance.attacker, Stance.defender, Stance.mitm, Stance.configurator):
        ctx = _ctx(stance=stance)
        result = tools.session_preflight(ctx, "a1")
        assert result["ready"] is True
        assert ("session_preflight", "cg_secret_key", "a1") in ctx.client.calls


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
              "run_setup_step", "upload_file", "finish_setup",
              "workspace_status", "workspace_diff", "workspace_patch_artifact"):
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
            "run_setup_step", "upload_file", "finish_setup",
            "workspace_status", "workspace_diff", "workspace_patch_artifact"} <= names
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
