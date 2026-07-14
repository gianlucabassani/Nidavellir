"""
Reference-harness tests (ROADMAP M3, ADR-0010).

Pure, offline coverage of the engagement loop, budgets, the scripted + Anthropic
brains, the single/suite runner, and deterministic replay — all with injected
fakes (no MCP, no orchestrator, no model).
"""
import asyncio
import json

import harness
from harness import Budget, ScriptedBrain, run_engagement
from harness.brains import AnthropicBrain
from harness.loop import EngagementState
from harness import claude_code
from harness.runner import (
    SingleRunConfig,
    run_single,
    run_single_claude_code,
    run_suite,
    summarize,
)
from harness.replay import plan_from_transcript, replay_run

TOOLS = [
    {"name": "get_topology", "description": "", "input_schema": {"type": "object",
     "properties": {"arena_id": {"type": "string"}}}},
    {"name": "run_command", "description": "", "input_schema": {"type": "object",
     "properties": {"arena_id": {"type": "string"}, "command": {"type": "string"}}}},
    {"name": "report_finding", "description": "", "input_schema": {"type": "object",
     "properties": {"arena_id": {"type": "string"}, "cwe": {"type": "string"}}}},
]


class FakeTools:
    def __init__(self, defs=TOOLS, fail=None):
        self._defs = defs
        self._fail = fail or set()
        self.calls = []

    async def list_tools(self):
        return self._defs

    async def call(self, name, args):
        self.calls.append((name, args))
        if name in self._fail:
            raise RuntimeError(f"{name} boom")
        return {"ok": True, "tool": name, "args": args}


def _run(coro):
    return asyncio.run(coro)


# --- loop --------------------------------------------------------------------

def test_scripted_plan_runs_then_stops():
    tools = FakeTools()
    brain = ScriptedBrain([("get_topology", {}), ("report_finding", {"cwe": "CWE-79"})])
    res = _run(run_engagement(arena_id="a1", tools=tools, brain=brain))
    assert [c[0] for c in tools.calls] == ["get_topology", "report_finding"]
    assert res.findings_reported == 1
    assert res.stop_reason.startswith("agent_stop")
    assert res.steps_used == 2


def test_step_budget_caps_the_run():
    tools = FakeTools()
    # A plan longer than the budget; loop must stop at max_steps.
    brain = ScriptedBrain([("run_command", {"command": f"c{i}"}) for i in range(10)],
                          stop_after=False)
    res = _run(run_engagement(arena_id="a1", tools=tools, brain=brain,
                              budget=Budget(max_steps=3)))
    assert res.steps_used == 3
    assert res.stop_reason == "budget_exhausted"


def test_max_findings_stops_early():
    tools = FakeTools()
    brain = ScriptedBrain([("report_finding", {}), ("report_finding", {}),
                           ("report_finding", {})], stop_after=False)
    res = _run(run_engagement(arena_id="a1", tools=tools, brain=brain,
                              budget=Budget(max_steps=10, max_findings=2)))
    assert res.findings_reported == 2
    assert res.stop_reason == "findings_target_reached"


def test_tool_error_is_recorded_not_fatal():
    tools = FakeTools(fail={"run_command"})
    brain = ScriptedBrain([("run_command", {}), ("report_finding", {})])
    res = _run(run_engagement(arena_id="a1", tools=tools, brain=brain))
    assert res.transcript[0].ok is False and "boom" in res.transcript[0].error
    assert res.transcript[1].ok is True  # kept going after the failed call


def test_brain_error_ends_run_cleanly():
    class Boom:
        async def decide(self, state):
            raise ValueError("bad brain")
    res = _run(run_engagement(arena_id="a1", tools=FakeTools(), brain=Boom()))
    assert res.stop_reason == "brain_error:ValueError"
    assert res.steps_used == 0


def test_deadline_stops_with_injected_clock():
    ticks = iter([0.0, 0.0, 5.0, 10.0, 100.0, 100.0])
    brain = ScriptedBrain([("run_command", {}) for _ in range(9)], stop_after=False)
    res = _run(run_engagement(arena_id="a1", tools=FakeTools(), brain=brain,
                              budget=Budget(max_steps=99, deadline_seconds=3.0),
                              clock=lambda: next(ticks)))
    assert res.stop_reason == "deadline"


# --- AnthropicBrain (fake client) --------------------------------------------

class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeAnthropic:
    """Returns a tool_use on the first create, an end-turn text on the second."""
    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.last_kwargs = kw
        self.calls += 1
        if self.calls == 1:
            return _Block(content=[_Block(type="tool_use", id="tu1",
                                          name="report_finding", input={"cwe": "CWE-89"})])
        return _Block(content=[_Block(type="text", text="done")])


def test_anthropic_brain_bridges_tool_use_and_stops():
    client = _FakeAnthropic()
    brain = AnthropicBrain(model="claude-fable-5", client=client)
    state = EngagementState(arena_id="a1", tools=TOOLS, history=[], steps_used=0,
                            findings_reported=0)
    a1 = _run(brain.decide(state))
    assert a1.kind == "tool" and a1.name == "report_finding" and a1.args == {"cwe": "CWE-89"}
    # tools were converted to the anthropic schema shape.
    assert {t["name"] for t in client.last_kwargs["tools"]} == {"get_topology", "run_command", "report_finding"}
    a2 = _run(brain.decide(state))
    assert a2.kind == "stop"


# --- runner + suite ----------------------------------------------------------

class FakeControl:
    def __init__(self, row=None, active=True, fail_deploy=False):
        self._row = row or {"run_id": "x", "score": {"value": 1.0}, "metadata": {"pass@1": 1}}
        self._active = active
        self._fail = fail_deploy
        self.destroyed = []

    def deploy(self, scenario):
        if self._fail:
            raise RuntimeError("deploy failed")
        return f"arena-{scenario}"

    def wait_active(self, arena_id, timeout=120.0):
        return self._active

    def bind_agent(self, arena_id, agent_name, stance):
        pass

    def eval_export(self, arena_id):
        return dict(self._row, run_id=arena_id)

    def destroy(self, arena_id):
        self.destroyed.append(arena_id)


def _factory():
    class _Ctx:
        async def __aenter__(self):
            return FakeTools()
        async def __aexit__(self, *e):
            return False
    return lambda arena_id: _Ctx()


def test_run_single_produces_eval_row_with_transcript():
    control = FakeControl()
    row = _run(run_single(
        scenario="s1", control=control, tools_factory=_factory(),
        brain_factory=lambda: ScriptedBrain([("report_finding", {"cwe": "CWE-79"})]),
        config=SingleRunConfig(),
    ))
    assert row["run_id"] == "arena-s1"
    assert row["run"]["findings_reported"] == 1
    assert control.destroyed == ["arena-s1"]  # torn down after


def test_run_single_inactive_arena_is_error_row():
    row = _run(run_single(
        scenario="s1", control=FakeControl(active=False), tools_factory=_factory(),
        brain_factory=lambda: ScriptedBrain([]),
    ))
    assert "did not become active" in row["error"]


def test_run_single_deploy_failure_is_error_row_not_raise():
    row = _run(run_single(
        scenario="s1", control=FakeControl(fail_deploy=True), tools_factory=_factory(),
        brain_factory=lambda: ScriptedBrain([]),
    ))
    assert "deploy failed" in row["error"]


def test_suite_runs_all_and_summarizes():
    control = FakeControl(row={"score": {"value": 1.0}, "metadata": {"pass@1": 1,
                          "nv.progress_rate": 1.0, "nv.mode": "benchmark", "attributed": True}})
    out = _run(run_suite(
        scenarios=["s1", "s2", "s3"], control=control, tools_factory=_factory(),
        brain_factory=lambda: ScriptedBrain([("report_finding", {})]),
        concurrency=2,
    ))
    assert out["summary"]["runs"] == 3
    assert out["summary"]["completed"] == 3
    assert out["summary"]["solved"] == 3
    assert out["summary"]["solve_rate"] == 1.0
    assert out["summary"]["modes"] == {"benchmark": 3}


def test_summarize_handles_errors_and_empties():
    rows = [{"error": "x", "metadata": {"error": "x"}},
            {"score": {"value": 0}, "metadata": {"pass@1": 0, "nv.progress_rate": 0.4}}]
    s = summarize(rows)
    assert s["runs"] == 2 and s["errored"] == 1 and s["completed"] == 1
    assert s["solved"] == 0
    assert summarize([])["runs"] == 0


# --- replay ------------------------------------------------------------------

def test_plan_from_transcript_extracts_tool_calls():
    transcript = [{"tool": "get_topology", "args": {}},
                  {"tool": "report_finding", "args": {"cwe": "CWE-79"}}]
    assert plan_from_transcript(transcript) == [("get_topology", {}),
                                                ("report_finding", {"cwe": "CWE-79"})]


def test_replay_reproduces_matching_score():
    recorded = {
        "scenario": "s1",
        "score": {"value": 1.0, "evidence": {"found": ["x"], "confirmed": ["x"],
                  "confirmed_findings": 1, "fault_sites": 1}},
        "run": {"transcript": [{"tool": "report_finding", "args": {"cwe": "CWE-79"}}]},
    }
    control = FakeControl(row=recorded)  # eval_export returns the same score
    out = _run(replay_run(recorded_row=recorded, control=control, tools_factory=_factory()))
    assert out["reproduced"] is True
    assert out["replay_score"] == 1.0


def test_replay_flags_divergence():
    recorded = {"scenario": "s1",
                "score": {"value": 1.0, "evidence": {"found": ["x"], "confirmed": ["x"]}},
                "run": {"transcript": [{"tool": "report_finding", "args": {}}]}}
    # control returns a DIFFERENT score on replay.
    control = FakeControl(row={"score": {"value": 0.0, "evidence": {"found": [], "confirmed": []}}})
    out = _run(replay_run(recorded_row=recorded, control=control, tools_factory=_factory()))
    assert out["reproduced"] is False


# --- RestControlPlane (fake http) --------------------------------------------

class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b"x"

    def json(self):
        return self._payload


class _RecordingHttp:
    def __init__(self, script):
        self._script = script  # (method, path_suffix) -> _Resp
        self.requests = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.requests.append((method, url, json))
        for (m, suffix), resp in self._script.items():
            if method == m and url.endswith(suffix):
                return resp
        return _Resp(200, {})


def test_rest_control_plane_lifecycle():
    from harness.rest_control import RestControlPlane

    http = _RecordingHttp({
        ("POST", "/deploy"): _Resp(200, {"queued": True}),
        ("POST", "/bindings"): _Resp(200, {"bound": True}),
        ("GET", "/eval-export"): _Resp(200, {"run_id": "x", "score": {"value": 1.0}}),
    })
    cp = RestControlPlane(api_url="http://orch:8000", operator_key="cg_op", http=http)
    arena = cp.deploy("container_web_pentest")
    assert arena.startswith("rh-")
    cp.bind_agent(arena, "reference-harness", "attacker")
    row = cp.eval_export(arena)
    assert row["score"]["value"] == 1.0
    # deploy sent the generated instance_id + scenario.
    deploy_body = next(j for (m, _u, j) in http.requests if m == "POST" and j and "instance_id" in j)
    assert deploy_body["scenario"] == "container_web_pentest"
    assert deploy_body["instance_id"] == arena


def test_rest_control_plane_wait_active_transitions():
    from harness.rest_control import RestControlPlane

    states = iter([{"status": "deploying"}, {"status": "active"}])
    http = _RecordingHttp({})
    http.request = lambda *a, **k: _Resp(200, next(states))
    cp = RestControlPlane(api_url="http://o", operator_key="k", http=http, poll_interval=0)
    assert cp.wait_active("rh-1", timeout=5) is True


def test_rest_control_plane_wait_active_gives_up_on_failure():
    from harness.rest_control import RestControlPlane

    http = _RecordingHttp({})
    http.request = lambda *a, **k: _Resp(200, {"status": "failed"})
    cp = RestControlPlane(api_url="http://o", operator_key="k", http=http, poll_interval=0)
    assert cp.wait_active("rh-1", timeout=5) is False


# --- Claude Code (subscription) path -----------------------------------------


def test_gateway_mcp_server_is_minimal_and_scoped():
    s = claude_code.gateway_mcp_server(
        agent_key="cg_agent", stance="attacker", api_url="http://127.0.0.1:8099",
        gateway_pythonpath="/gw", python="python3")
    assert s["type"] == "stdio" and s["command"] == "python3"
    assert s["args"] == ["-m", "gateway.server"]
    # only the gateway's own overrides — no unrelated environment leaks in.
    assert set(s["env"]) == {"PYTHONPATH", "NIDAVELLIR_AGENT_KEY", "NIDAVELLIR_STANCE",
                             "NIDAVELLIR_API_URL", "NIDAVELLIR_GATEWAY_TRANSPORT"}
    assert s["env"]["NIDAVELLIR_AGENT_KEY"] == "cg_agent"


def test_build_mcp_config_and_command():
    server = claude_code.gateway_mcp_server(
        agent_key="k", stance="attacker", api_url="http://x", gateway_pythonpath="/gw")
    cfg = claude_code.build_mcp_config(server)
    assert cfg == {"mcpServers": {"nidavellir-arena": server}}

    argv = claude_code.build_claude_command(prompt="play arena a1", mcp_config="/tmp/c.json",
                                            model="opus")
    assert argv[0] == "claude" and "-p" in argv and "play arena a1" in argv
    assert "--mcp-config" in argv and "/tmp/c.json" in argv
    i = argv.index("--allowedTools")
    assert argv[i + 1] == "mcp__nidavellir-arena__*"
    assert "--output-format" in argv and "json" in argv
    assert "--strict-mcp-config" in argv  # hermetic: only our gateway server
    assert argv[argv.index("--model") + 1] == "opus"


class _Proc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _claude_runner(returncode=0, stdout=""):
    def run(argv, capture_output=True, text=True, timeout=None, env=None):
        run.argv = argv
        return _Proc(returncode, stdout)
    return run


def test_run_claude_code_parses_json_output():
    out = json.dumps({"result": "found SQLi", "total_cost_usd": 0.021,
                      "usage": {"input_tokens": 1200, "output_tokens": 300},
                      "session_id": "sess-1"})
    res = claude_code.run_claude_code(["claude"], runner=_claude_runner(0, out))
    assert res.ok and res.result_text == "found SQLi"
    assert res.cost_usd == 0.021 and res.session_id == "sess-1"


def test_run_claude_code_handles_nonjson_and_failure():
    plain = claude_code.run_claude_code(["claude"], runner=_claude_runner(0, "just text"))
    assert plain.result_text == "just text" and plain.cost_usd is None
    failed = claude_code.run_claude_code(["claude"], runner=_claude_runner(2, ""))
    assert failed.ok is False and failed.returncode == 2


def test_run_single_claude_code_produces_enriched_row():
    control = FakeControl(row={"run_id": "x", "score": {"value": 1.0}, "metadata": {"pass@1": 1}})
    out = json.dumps({"result": "reported CWE-89", "total_cost_usd": 0.05,
                      "usage": {"input_tokens": 900, "output_tokens": 200}})
    cfg = claude_code.build_mcp_config(claude_code.gateway_mcp_server(
        agent_key="k", stance="attacker", api_url="http://x", gateway_pythonpath="/gw"))
    row = _run(run_single_claude_code(
        scenario="container_web_pentest", control=control, mcp_config=cfg,
        prompt_template="play {arena_id}", claude_runner=_claude_runner(0, out),
    ))
    assert row["run"]["agent"] == "claude-code"
    assert row["run"]["result_text"] == "reported CWE-89"
    # cost/usage folded into the eval row's metadata.
    assert row["metadata"]["cost_usd"] == 0.05
    assert row["metadata"]["tokens"] == 1100
    assert control.destroyed  # arena torn down


def test_package_exports():
    for name in ("run_engagement", "run_single", "run_single_claude_code", "run_suite",
                 "replay_run", "ScriptedBrain", "AnthropicBrain", "Budget", "claude_code"):
        assert hasattr(harness, name)
