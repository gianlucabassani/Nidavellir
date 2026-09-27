"""Model-driven durable evaluation uses mocked provider decisions only."""
from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

import api
import auth
import eval_model_driver as driver
import experiments
from database import Database


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.isError = False
        self.structuredContent = payload


class Session:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return Response({"recorded": True, "finding_id": "neutral"})


def test_model_trial_injects_scope_and_keeps_neutral_ack():
    session = Session()
    connection = {"provider": "anthropic", "model": "mock", "api_key": "not-used"}
    build = {"config": {"goal": "Test the synthetic target", "max_model_calls": 2,
                        "max_output_tokens": 128, "deadline_seconds": 600}}
    prompts = []

    def decide(_connection, prompt, _tokens, _timeout):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"tool": "report_finding", "args": {"title": "claim", "node": "target"}}, {
                "input_tokens": 100, "output_tokens": 20, "cost_usd": None}
        return None, {"input_tokens": 40, "output_tokens": 2, "cost_usd": None}

    result = asyncio.run(driver.run(session, "arena", build, connection,
        lambda response: response.structuredContent, decide=decide))
    assert session.calls == [("report_finding", {"title": "claim", "node": "target",
                              "arena_id": "arena"})]
    assert result["termination"] == "model_end_turn"
    assert result["model_usage"] == [
        {"input_tokens": 100, "output_tokens": 20, "cost_usd": None},
        {"input_tokens": 40, "output_tokens": 2, "cost_usd": None}]
    assert "neutral" in prompts[1] and "confirmed" not in prompts[1]


def test_invalid_model_tool_never_reaches_mcp():
    session = Session()
    build = {"config": {"goal": "Test", "max_model_calls": 1,
                        "max_output_tokens": 128, "deadline_seconds": 600}}
    result = asyncio.run(driver.run(session, "arena", build, {},
        lambda response: response.structuredContent,
        decide=lambda *_: ({"tool": "run_command", "args": {"command": "id"}},
                           {"input_tokens": 1, "output_tokens": 1, "cost_usd": None})))
    assert result["termination"] == "model_protocol_error"
    assert session.calls == []


def test_anthropic_response_usage_and_one_tool():
    seen = {}

    def transport(url, *, headers, json, timeout, allow_redirects):
        seen.update(url=url, headers=headers, body=json, timeout=timeout,
                    allow_redirects=allow_redirects)
        class HTTP:
            status_code = 200

            def json(self):
                return {"content": [{"type": "tool_use", "name": "get_briefing", "input": {}}],
                        "usage": {"input_tokens": 30, "output_tokens": 5}}
        return HTTP()

    action, usage = driver._post({"provider": "anthropic", "model": "mock-haiku",
        "api_key": "fake-key"}, "synthetic task", 128, 5, transport)
    assert action == {"tool": "get_briefing", "args": {}}
    assert usage == {"input_tokens": 30, "output_tokens": 5, "cost_usd": None}
    assert seen["url"].endswith("/v1/messages")
    assert seen["body"]["max_tokens"] == 128
    assert seen["allow_redirects"] is False
    assert "run_command" not in [tool["name"] for tool in seen["body"]["tools"]]


def test_gemini_compatibility_uses_low_consumption_and_usage():
    seen = {}

    def transport(url, *, headers, json, timeout, allow_redirects):
        seen.update(url=url, headers=headers, body=json, timeout=timeout,
                    allow_redirects=allow_redirects)
        class HTTP:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"tool_calls": [{"function": {
                    "name": "get_briefing", "arguments": "{}"}}]}}],
                    "usage": {"prompt_tokens": 70, "completion_tokens": 10}}
        return HTTP()

    action, usage = driver._post({"provider": "gemini", "model": "gemini-2.5-flash",
        "api_key": "fake-key"}, "synthetic task", 128, 5, transport)
    assert action == {"tool": "get_briefing", "args": {}}
    assert usage == {"input_tokens": 70, "output_tokens": 10, "cost_usd": None}
    assert seen["body"]["reasoning_effort"] == "none"
    assert seen["url"].endswith("/chat/completions")


def test_model_build_pins_connection_without_credential(monkeypatch):
    db = Database()
    key = auth.generate_api_key()
    owner = f"model-operator-{uuid.uuid4().hex}"
    db.create_api_key(auth.hash_api_key(key), name=owner, role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    monkeypatch.setattr("database.Database.get_model_connection", lambda self, owner: {
        "provider": "anthropic", "model": "mock-haiku", "key_last4": "alue",
        "base_url": None})
    response = client.post("/agent-builds", json={
        "name": f"model-build-{uuid.uuid4().hex}", "version": "v1",
        "driver": "model-mcp/v1", "goal": "Test synthetic ownership"})
    assert response.status_code == 201, response.text
    build = response.json()
    assert build["config"]["connection_owner"] == owner
    assert build["config"]["max_model_calls"] == 8
    assert "key_last4" not in str(build)
    assert client.post("/agent-builds", json={"name": "bad", "version": "v1",
        "driver": "model-mcp/v1", "goal": "test", "max_model_calls": 9}).status_code == 422


def test_single_trial_smoke_is_durable_and_unpaired(monkeypatch):
    db = Database()
    key = auth.generate_api_key()
    owner = f"smoke-operator-{uuid.uuid4().hex}"
    db.create_api_key(auth.hash_api_key(key), name=owner, role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    build = db.create_agent_build(name="mock-model", version="v1",
        digest=f"sha256:{uuid.uuid4().hex}", driver="model-mcp/v1",
        config={"connection_owner": owner, "provider": "anthropic", "model": "mock"})
    challenge = db.create_eval_challenge(name="synthetic", version="v1",
        scenario="fixture", source_arena_id="source", recipe_digest="sha256:fixture",
        validator_version="authorization_effect/v1", label="calibration")
    queued = []
    monkeypatch.setattr(api, "enqueue_evaluation", lambda evaluation_id: queued.append(evaluation_id))
    response = client.post("/evaluation-smokes", json={
        "build_id": build["id"], "challenge_id": challenge["id"],
        "action_cap": 8, "deadline_seconds": 600})
    assert response.status_code == 202, response.text
    assert response.json()["kind"] == "single_trial_smoke"
    record = client.get("/evaluations/" + response.json()["id"]).json()
    assert record["kind"] == "single_trial_smoke"
    assert len(record["runs"]) == len(record["trials"]) == 1
    assert record["comparison"]["matched_pairs"] == 0
    assert queued == [record["id"]]
    assert client.post("/evaluation-smokes", json={"build_id": build["id"],
        "challenge_id": challenge["id"], "action_cap": 9}).status_code == 422
    assert experiments.compare(record)["evidence_scope"] == "calibration_or_unknown"
