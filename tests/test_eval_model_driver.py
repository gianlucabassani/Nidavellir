"""Model-driven durable evaluation uses mocked provider decisions only."""
from __future__ import annotations

import asyncio
import uuid

import pytest
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


def test_single_invalid_tool_is_fed_back_and_continues():
    session = Session()
    build = {"config": {"goal": "Test", "max_model_calls": 3,
                        "max_output_tokens": 128, "deadline_seconds": 600}}
    prompts = []
    calls = [0]

    def decide(_connection, prompt, _tokens, _timeout):
        prompts.append(prompt)
        calls[0] += 1
        if calls[0] == 1:
            return ({"tool": "run_command", "args": {"command": "id"}},
                    {"input_tokens": 1, "output_tokens": 1, "cost_usd": None})
        if calls[0] == 2:
            return ({"tool": "report_finding", "args": {"title": "claim", "node": "target"}},
                    {"input_tokens": 1, "output_tokens": 1, "cost_usd": None})
        return None, {"input_tokens": 1, "output_tokens": 1, "cost_usd": None}

    result = asyncio.run(driver.run(session, "arena", build, {},
        lambda response: response.structuredContent, decide=decide))
    # one wobble does not void the trial: the model is told and continues
    assert result["termination"] == "model_end_turn"
    assert session.calls == [("report_finding", {"title": "claim", "node": "target",
                              "arena_id": "arena"})]
    rejected = result["transcript"][0]
    assert rejected["ok"] is False and "available tools" in rejected["error"]
    assert len(rejected["error"]) <= 200
    assert "available tools" in prompts[1]


def test_repeated_invalid_tool_terminates_protocol_error():
    session = Session()
    build = {"config": {"goal": "Test", "max_model_calls": 3,
                        "max_output_tokens": 128, "deadline_seconds": 600}}
    result = asyncio.run(driver.run(session, "arena", build, {},
        lambda response: response.structuredContent,
        decide=lambda *_: ({"tool": "run_command", "args": {"command": "id"}},
                           {"input_tokens": 1, "output_tokens": 1, "cost_usd": None})))
    # two in a row: the model is not learning, end the trial as agent failure
    assert result["termination"] == "model_protocol_error"
    assert session.calls == []
    assert len(result["transcript"]) == 2
    assert all(entry["ok"] is False for entry in result["transcript"])
    assert all("available tools" in entry["error"] for entry in result["transcript"])
    assert all(len(entry["error"]) <= 200 for entry in result["transcript"])


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
        "driver": "model-mcp/v1", "goal": "test", "max_model_calls": 13}).status_code == 422
    assert client.post("/agent-builds", json={"name": "bad", "version": "v1",
        "driver": "model-mcp/v1", "goal": "test", "cost_budget_usd": 1}).status_code == 422


# --- MODEL-R1: extra_headers passthrough ----------------------------------

def _openai_ok(payload):
    class HTTP:
        status_code = 200

        def json(self):
            return payload
    return HTTP()


def test_post_sends_extra_headers_openai_path():
    seen = {}

    def transport(url, *, headers, json, timeout, allow_redirects):
        seen.update(url=url, headers=headers)
        return _openai_ok({"choices": [{"message": {"tool_calls": [{"function": {
            "name": "get_briefing", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    action, _ = driver._post({
        "provider": "openai", "model": "gpt-4o", "api_key": "fake-key",
        "extra_headers": {"User-Agent": "opencode-test/1.0",
                          "x-opencode-session": "sess-123"}},
        "synthetic task", 128, 5, transport)
    assert action == {"tool": "get_briefing", "args": {}}
    assert seen["headers"]["User-Agent"] == "opencode-test/1.0"
    assert seen["headers"]["x-opencode-session"] == "sess-123"
    assert seen["headers"]["Authorization"] == "Bearer fake-key"


def test_post_sends_extra_headers_anthropic_path():
    seen = {}

    def transport(url, *, headers, json, timeout, allow_redirects):
        seen.update(url=url, headers=headers)

        class HTTP:
            status_code = 200

            def json(self):
                return {"content": [{"type": "tool_use", "name": "get_briefing",
                                     "input": {}}],
                        "usage": {"input_tokens": 1, "output_tokens": 1}}
        return HTTP()

    action, _ = driver._post({
        "provider": "anthropic", "model": "mock-haiku", "api_key": "fake-key",
        "extra_headers": {"User-Agent": "opencode-test/1.0",
                          "x-opencode-session": "sess-123"}},
        "synthetic task", 128, 5, transport)
    assert action == {"tool": "get_briefing", "args": {}}
    assert seen["headers"]["User-Agent"] == "opencode-test/1.0"
    assert seen["headers"]["x-opencode-session"] == "sess-123"
    assert seen["headers"]["x-api-key"] == "fake-key"


def test_post_authorization_cannot_be_overridden():
    seen = {}

    def transport(url, *, headers, json, timeout, allow_redirects):
        seen["headers"] = headers
        return _openai_ok({"choices": [{"message": {"tool_calls": [{"function": {
            "name": "get_briefing", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    # Even if extra_headers smuggled Authorization past validation, the
    # driver's own credential always wins.
    driver._post({
        "provider": "openai", "model": "gpt-4o", "api_key": "real-key",
        "extra_headers": {"Authorization": "Bearer evil"}},
        "synthetic task", 128, 5, transport)
    assert seen["headers"]["Authorization"] == "Bearer real-key"


def test_model_build_pins_headers_digest(monkeypatch):
    import hashlib
    import json as _json

    db = Database()
    key = auth.generate_api_key()
    owner = f"model-headers-{uuid.uuid4().hex}"
    db.create_api_key(auth.hash_api_key(key), name=owner, role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    headers = {"User-Agent": "opencode-test/1.0", "x-opencode-session": "s"}
    digest = "sha256:" + hashlib.sha256(_json.dumps(
        headers, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    monkeypatch.setattr("database.Database.get_model_connection", lambda self, owner: {
        "provider": "custom", "model": "m", "key_last4": None,
        "base_url": "http://vllm.internal:8000/v1",
        "header_names": sorted(headers), "headers_digest": digest})
    response = client.post("/agent-builds", json={
        "name": f"model-headers-build-{uuid.uuid4().hex}", "version": "v1",
        "driver": "model-mcp/v1", "goal": "Test synthetic ownership"})
    assert response.status_code == 201, response.text
    build = response.json()
    assert build["config"]["headers_digest"] == digest
    assert "opencode-test" not in str(build)


def test_model_trial_rejects_headers_digest_drift():
    connection = {"provider": "custom", "model": "m",
                  "base_url": "http://vllm.internal:8000/v1",
                  "extra_headers": {"User-Agent": "opencode-test/1.0"}}
    config = {"provider": "custom", "model": "m",
              "base_url": "http://vllm.internal:8000/v1",
              "headers_digest": "sha256:" + "0" * 64}
    with pytest.raises(RuntimeError, match="headers_digest"):
        experiments.check_model_connection(connection, config)
    # matching digest passes silently
    import model_headers
    config["headers_digest"] = model_headers.extra_headers_digest(
        connection["extra_headers"])
    experiments.check_model_connection(connection, config)
    # a model drift names the model field
    with pytest.raises(RuntimeError, match="model"):
        experiments.check_model_connection(connection, {**config, "model": "other"})


# --- topology orientation (class-C root cause) ------------------------------

def test_topology_offered_with_no_model_args():
    schemas = driver._schemas()
    assert "get_topology" in schemas
    assert schemas["get_topology"]["required"] == []
    assert schemas["get_topology"]["properties"] == {}
    # arena_id is driver-injected; the model must not supply it or anything else
    with pytest.raises(driver.ModelProtocolError):
        driver._valid_action({"tool": "get_topology",
                              "args": {"arena_id": "arena"}})
    with pytest.raises(driver.ModelProtocolError):
        driver._valid_action({"tool": "get_topology",
                              "args": {"node": "target"}})


def test_topology_call_routed_recorded_and_fed_back():
    session = Session()
    build = {"config": {"goal": "Test", "max_model_calls": 3,
                        "max_output_tokens": 128, "deadline_seconds": 600}}
    prompts = []
    calls = [0]
    topology = {"arena_id": "arena", "nodes": [
        {"node": "target", "url": "http://10.0.0.3:8080",
         "state": "active", "foothold": False}]}

    class TopoResponse:
        isError = False
        structuredContent = topology

    def decide(_connection, prompt, _tokens, _timeout):
        prompts.append(prompt)
        calls[0] += 1
        if calls[0] == 1:
            return {"tool": "get_topology", "args": {}}, {
                "input_tokens": 1, "output_tokens": 1, "cost_usd": None}
        return None, {"input_tokens": 1, "output_tokens": 1, "cost_usd": None}

    async def call_tool(name, arguments):
        session.calls.append((name, arguments))
        return TopoResponse()

    session.call_tool = call_tool
    result = asyncio.run(driver.run(session, "arena", build, {},
        lambda response: response.structuredContent, decide=decide))
    assert ("get_topology", {"arena_id": "arena"}) in session.calls
    # tool + ok only: no topology content (and no truth) lands in evidence
    assert result["transcript"][0] == {"tool": "get_topology", "ok": True}
    # the agent actually receives names/URLs in the next turn's history
    assert "target" in prompts[1] and "http://10.0.0.3:8080" in prompts[1]


def test_failed_call_retains_truncated_error_text():
    session = Session()
    build = {"config": {"goal": "Test", "max_model_calls": 1,
                        "max_output_tokens": 128, "deadline_seconds": 600}}

    class FailResponse:
        isError = True
        structuredContent = {"error": "unknown node(s) ['nope']; arena nodes: ['target']"}

    async def call_tool(name, arguments):
        session.calls.append((name, arguments))
        return FailResponse()

    session.call_tool = call_tool
    result = asyncio.run(driver.run(session, "arena", build, {},
        lambda response: response.structuredContent,
        decide=lambda *_: ({"tool": "http_request",
                            "args": {"node": "nope", "path": "/"}},
                           {"input_tokens": 1, "output_tokens": 1, "cost_usd": None})))
    entry = result["transcript"][-1]
    assert entry["ok"] is False
    assert "unknown node" in entry["error"]
    assert len(entry["error"]) <= 200


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
        "challenge_id": challenge["id"], "action_cap": 13}).status_code == 422
    assert client.post("/evaluation-smokes", json={"build_id": build["id"],
        "challenge_id": challenge["id"], "token_budget": 100}).status_code == 422
    assert experiments.compare(record)["evidence_scope"] == "calibration_or_unknown"
