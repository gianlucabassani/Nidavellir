"""OBS-03 (FR-12): gateway tool calls, orchestrator actions and model calls in
one trace.

A mocked model-driven trial calls a tool through the real gateway wrapper and
REST client into the orchestrator. The result is one arena trace holding the
model spans (with the usage the trial stores), the gateway's tool-call span and
the orchestrator's action span nested under it. Self-reported spans are
labelled, bounded and confined to the caller's arena.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

import api
import eval_model_driver as driver
import experiments
import spans
from database import Database
from gateway import spans as gateway_spans
from gateway.rest_client import RestClient
from tests.research_support import active_arena, bind, client


class _Http:
    """RestClient transport over the in-process orchestrator."""
    def __init__(self):
        self.client = TestClient(api.app)

    def request(self, method, url, headers=None, json=None, timeout=None):
        return self.client.request(method, url, headers=headers, json=json)


class _Response:
    def __init__(self, payload):
        self.isError = False
        self.structuredContent = payload


def test_model_trial_yields_one_trace_with_nested_tool_and_model_spans():
    operator, agent = client("operator"), client("agent")
    arena = active_arena()
    bind(operator, arena, agent, "attacker")
    rest = RestClient("", http=_Http())
    ctx = SimpleNamespace(client=rest, session=SimpleNamespace(
        api_key=agent.headers["X-API-Key"], stance=SimpleNamespace(value="attacker")))

    def report_finding(arena_id, title, node):
        return rest._request("POST", f"/arenas/{arena_id}/findings", ctx.session.api_key,
                             json={"title": title, "node": node})

    tool = gateway_spans.traced(report_finding, lambda: ctx)

    class Session:
        async def call_tool(self, name, arguments):
            return _Response(tool(**arguments))

    usage = [{"input_tokens": 120, "output_tokens": 30, "cost_usd": None},
             {"input_tokens": 50, "output_tokens": 4, "cost_usd": None}]
    calls = iter([({"tool": "report_finding", "args": {"title": "IDOR", "node": "victim"}},
                   usage[0]), (None, usage[1])])
    build = {"id": "build-a", "name": "build-a",
             "config": {"goal": "find it", "max_model_calls": 3, "max_output_tokens": 64,
                        "deadline_seconds": 600, "model": "mock-model",
                        "provider": "mock"}}
    trial_id = f"trial-{uuid.uuid4().hex[:8]}"
    result = asyncio.run(driver.run(
        Session(), arena, build, {}, lambda r: r.structuredContent,
        decide=lambda *_: next(calls),
        on_model_call=experiments._model_span_recorder(arena, build, trial_id, "eval-1")))
    assert result["termination"] == "model_end_turn"

    rows = Database().list_spans(arena_id=arena)
    assert {r["trace_id"] for r in rows} == {spans.trace_id_for(arena_id=arena)}
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    assert len(by_kind["model"]) == 2 and len(by_kind["agent"]) == 1
    gateway, = by_kind["agent"]
    action, = by_kind["tool"]
    assert gateway["name"] == "report_finding" and gateway["attrs"]["nv.source"] == "gateway"
    assert gateway["attrs"]["nv.self_reported"] is True
    assert action["name"] == "findings" and action["parent_span_id"] == gateway["span_id"]
    assert all(m["trial_id"] == trial_id for m in by_kind["model"])
    tokens = sum(m["attrs"]["gen_ai.usage.input_tokens"] + m["attrs"]["gen_ai.usage.output_tokens"]
                 for m in by_kind["model"])
    stored = sum(u["input_tokens"] + u["output_tokens"] for u in result["model_usage"])
    assert tokens == stored == 204


def _span(**overrides):
    now = datetime.now(timezone.utc)
    body = {"name": "think", "kind": "agent",
            "started_at": (now - timedelta(seconds=2)).isoformat(),
            "ended_at": now.isoformat(), "attrs": {"note": "plan"}}
    body.update(overrides)
    return body


def test_self_reported_spans_are_labelled_scoped_and_bounded():
    operator, agent, stranger = client("operator"), client("agent"), client("agent")
    arena, other = active_arena(), active_arena()
    bind(operator, arena, agent, "attacker")
    sid = uuid.uuid4().hex[:16]
    r = agent.post(f"/arenas/{arena}/spans",
                   json=_span(span_id=sid, attrs={"nv.self_reported": False,
                                                  "authorization": "Bearer secret-value-123"}))
    assert r.status_code == 201, r.text
    assert r.json()["trace_id"] == spans.trace_id_for(arena_id=arena)
    row = Database().list_spans(arena_id=arena)[-1]
    assert row["attrs"]["nv.self_reported"] is True and row["visibility"] == "agent"
    assert "secret-value-123" not in str(row)
    assert row["stance"] == "attacker" and row["actor"] == agent.name
    assert agent.post(f"/arenas/{arena}/spans", json=_span(span_id=sid)).status_code == 409
    assert stranger.post(f"/arenas/{arena}/spans", json=_span()).status_code == 403
    assert agent.post(f"/arenas/{other}/spans", json=_span()).status_code == 403
    now = datetime.now(timezone.utc)
    for bad in (_span(kind="validation"), _span(kind="tool"), _span(status="denied"),
                _span(trace_id="0" * 32), _span(input={"x": "y" * 20000}),
                _span(started_at=now.isoformat(),
                      ended_at=(now - timedelta(seconds=5)).isoformat()),
                _span(started_at=(now - timedelta(days=3)).isoformat(),
                      ended_at=(now - timedelta(days=3)).isoformat()),
                _span(span_id="not-hex")):
        assert agent.post(f"/arenas/{arena}/spans", json=bad).status_code == 422, bad
    # Self-reported spans never consume the action budget.
    assert operator.get(f"/arenas/{arena}/budget").json()["policy"]["spent"] == 0


def test_traceparent_gives_only_the_parent_never_the_trace():
    good = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    assert spans.parent_from_traceparent(good) == "b" * 16
    for bad in (None, "", "garbage", "00-" + "a" * 32 + "-" + "0" * 16 + "-01",
                "00-" + "a" * 31 + "-" + "b" * 16 + "-01"):
        assert spans.parent_from_traceparent(bad) is None
    operator = client("operator")
    arena = active_arena()
    operator.post(f"/arenas/{arena}/exec", json={"node": "victim", "command": "id"},
                  headers={"traceparent": good})
    row = Database().list_spans(arena_id=arena)[-1]
    assert row["parent_span_id"] == "b" * 16
    assert row["trace_id"] == spans.trace_id_for(arena_id=arena) != "a" * 32


def test_gateway_and_orchestrator_derive_the_same_arena_trace():
    assert gateway_spans.trace_id_for_arena("arena-x") == spans.trace_id_for(arena_id="arena-x")
