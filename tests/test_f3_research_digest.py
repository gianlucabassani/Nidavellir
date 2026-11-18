"""
F3 (work order 2026-11-18): the bounded research digest.

``GET /arenas/{id}/digest`` and the MCP ``digest`` tool return ≤ 2048 bytes of
deterministic JSON built from sources of truth, so an agent stops re-reading its
own multi-megabyte run log every cycle. An agent sees only FR-04-visible events and
never an operator verdict or a validator match.
"""
import asyncio
import json
import random
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api
import research_digest
from auth import generate_api_key, hash_api_key
from database import Database
from timeutil import db_now

TOP_KEYS = {"schema", "arena", "seconds_left", "budget", "cycles", "hypotheses",
            "findings", "recent", "next_actions"}
_CREATED: list[str] = []


def _client(role):
    name = f"f3-{role}-{uuid.uuid4().hex[:8]}"
    key = generate_api_key()
    Database().create_api_key(hash_api_key(key), name, role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    client.name = name
    client.key = key
    return client


@pytest.fixture(autouse=True)
def _retire_arenas():
    yield
    db = Database()
    while _CREATED:
        arena = _CREATED.pop()
        if db.get_deployment(arena)["status"] == "active":
            db.update_deployment(arena, status="destroying")
            db.update_deployment(arena, status="destroyed")


def _arena(expires_in=3600):
    arena = str(uuid.uuid4())
    _CREATED.append(arena)
    db = Database()
    db.create_deployment(arena, arena[:8], "opencms-22-whitebox", provider="mock",
                         expires_at=db_now() + timedelta(seconds=expires_in))
    db.update_deployment(arena, status="deploying")
    db.update_deployment(arena, status="active", outputs={"node_victim_name": "mock-victim"})
    return arena


def _bind(operator, arena, agent, stance):
    assert operator.post(f"/arenas/{arena}/bindings", json={
        "agent_name": agent.name, "stance": stance}).status_code == 200


def _heavy_campaign(arena, findings=400, execs=300):
    """Worst case well beyond the OpenCMS campaign: long multi-byte titles,
    huge commands, evidence on half the claims, operator verdicts and an
    operator-entered finding that agents must never see."""
    db = Database()
    for i in range(12):
        db.record_event(arena, "agent_session", {"model": "m", "provider": "p"}, actor="a")
    for i in range(findings):
        payload = {"finding_id": uuid.uuid4().hex[:12], "title": f"Ünïcødé ✓ OpenCms finding {i} " + "x" * 220,
                   "cwe": "CWE-79", "matched_vuln_id": "SECRET-VULN",
                   "validation": {"confirmed": True}}
        if i % 2:
            payload["transaction_digests"] = ["sha256:" + "a" * 64]
        db.record_event(arena, "finding", payload, actor="agent")
        if i % 3 == 0:
            db.record_event(arena, "finding_verification",
                            {"finding_id": payload["finding_id"], "verdict": "confirmed"},
                            actor="op")
    db.record_event(arena, "finding", {"finding_id": uuid.uuid4().hex[:12], "title": "OPERATOR-ONLY",
                                       "manual": True}, actor="op")
    for i in range(execs):
        db.record_event(arena, "agent_exec", {"node": "attacker", "exit_code": 0,
                                              "command": "curl -s " + "A" * 4000}, actor="a")


def test_digest_is_bounded_and_schema_complete_for_a_heavy_campaign():
    operator, attacker = _client("operator"), _client("agent")
    arena = _arena()
    _bind(operator, arena, attacker, "attacker")
    _heavy_campaign(arena)

    for caller in (attacker, operator):
        response = caller.get(f"/arenas/{arena}/digest")
        assert response.status_code == 200, response.text
        assert len(response.content) <= 2048, len(response.content)
        doc = response.json()
        assert set(doc) == TOP_KEYS
        assert doc["schema"] == "nidavellir.research-digest.v1"
        assert doc["arena"]["status"] == "active"
        assert 3500 <= doc["seconds_left"] <= 3600
        assert doc["cycles"] == 12
        assert len(doc["recent"]) <= 3 and len(doc["next_actions"]) <= 3
        assert len(doc["findings"]["titles"]) <= 10
        assert doc["budget"]["remaining"] == doc["budget"]["cap"]

    agent_doc = attacker.get(f"/arenas/{arena}/digest").json()
    assert agent_doc["findings"]["count"] == 400  # manual finding hidden
    assert agent_doc["hypotheses"] == {"evidenced": 200, "asserted": 200}
    assert agent_doc["findings"]["titles_truncated"] is True
    assert agent_doc["findings"]["titles"][0].startswith("Ünïcødé ✓ OpenCms finding 399")
    assert "SECRET-VULN" not in json.dumps(agent_doc)
    assert "OPERATOR-ONLY" not in json.dumps(agent_doc)

    op_doc = operator.get(f"/arenas/{arena}/digest").json()
    assert op_doc["findings"]["count"] == 401
    assert op_doc["hypotheses"]["verdicts"]["confirmed"] == 134


def test_digest_requires_a_binding_but_allows_reads_while_paused():
    operator, agent, other = _client("operator"), _client("agent"), _client("agent")
    arena = _arena()
    assert agent.get(f"/arenas/{arena}/digest").status_code == 403
    _bind(operator, arena, agent, "attacker")
    operator.post(f"/arenas/{arena}/bindings/{agent.name}/pause")
    assert agent.get(f"/arenas/{arena}/digest").status_code == 200
    assert other.get(f"/arenas/{arena}/digest").status_code == 403
    assert operator.get(f"/arenas/{uuid.uuid4()}/digest").status_code == 404


def test_next_actions_follow_stance_time_and_evidence():
    operator, attacker, configurator = _client("operator"), _client("agent"), _client("agent")
    arena = _arena(expires_in=300)
    _bind(operator, arena, attacker, "attacker")
    _bind(operator, arena, configurator, "configurator")

    attacker_actions = attacker.get(f"/arenas/{arena}/digest").json()["next_actions"]
    assert attacker_actions[0] == "time box nearly over: ask the operator to extend"
    assert "no findings yet: get_topology, then probe the targets" in attacker_actions
    configurator_actions = configurator.get(f"/arenas/{arena}/digest").json()["next_actions"]
    assert configurator_actions[0] == "time box nearly over: extend_arena(seconds=3600)"

    Database().record_event(arena, "finding", {"finding_id": uuid.uuid4().hex[:12], "title": "XSS"})
    actions = attacker.get(f"/arenas/{arena}/digest").json()["next_actions"]
    assert "attach transaction_digests to 1 asserted finding(s)" in actions


def test_recent_lines_skip_noise_and_are_newest_first():
    operator = _client("operator")
    arena = _arena()
    db = Database()
    for i in range(5):
        db.record_event(arena, "agent_exec", {"node": "attacker", "command": f"step-{i}"})
    db.record_event(arena, "status", {"status": "active"})
    db.record_event(arena, "agent_session", {"model": "m"})
    recent = operator.get(f"/arenas/{arena}/digest").json()["recent"]
    assert [line.split("command=")[1].split()[0] for line in recent] == [
        "step-4", "step-3", "step-2"]


def test_render_is_deterministic_and_never_exceeds_the_cap():
    now = datetime(2026, 11, 18, 12, 0, 0)
    rng = random.Random(7)
    for _ in range(50):
        n = rng.randint(0, 600)
        findings = [{"payload": {"title": "".join(rng.choice("aé✓ <>\"\\") for _ in
                                                     range(rng.randint(0, 256)))}}
                    for _ in range(n)]
        activity = [{"type": "agent_exec", "ts": "2026-11-18 11:59:00",
                     "payload": {"command": "ü" * rng.randint(0, 5000)}}
                    for _ in range(rng.randint(0, 10))]
        doc = research_digest.build(
            arena={"id": str(uuid.uuid4()), "status": "active", "scenario": "s" * 64,
                   "expires_at": "2026-11-18 12:05:00"},
            budget={"policy": {"remaining": 3, "action_cap": 1000,
                               "deadline": "2026-11-18 12:05:00"},
                    "arena": {"state": "open"}, "system": {"state": "open"}},
            finding_events=findings, activity_events=activity, session_count=n,
            now=now, verdicts={}, can_extend=True)
        body = research_digest.render(doc)
        assert len(body) <= research_digest.MAX_BYTES
        assert body == research_digest.render(doc)
        parsed = json.loads(body)
        assert parsed["findings"]["count"] == n and parsed["seconds_left"] == 300


# --- gateway ------------------------------------------------------------------


def test_digest_is_a_lifecycle_tool_registered_for_every_stance():
    from gateway.config import GatewayConfig
    from gateway.server import build_server
    from gateway.stances import LIFECYCLE_TOOLS

    assert "digest" in LIFECYCLE_TOOLS
    for stance in ("attacker", "defender", "mitm", "configurator"):
        mcp = build_server(GatewayConfig(env={"NIDAVELLIR_STANCE": stance}))
        assert "digest" in {t.name for t in asyncio.run(mcp.list_tools())}


def test_gateway_digest_works_end_to_end_with_an_attacker_binding():
    from gateway import tools
    from gateway.session import Session
    from gateway.stances import Stance
    from gateway.tools import GatewayContext

    operator, attacker = _client("operator"), _client("agent")
    arena = _arena()
    _bind(operator, arena, attacker, "attacker")
    _heavy_campaign(arena, findings=30, execs=10)
    http = TestClient(api.app)

    class Orchestrator:  # the gateway REST client, served in-process
        def digest(self, api_key, arena_id):
            response = http.get(f"/arenas/{arena_id}/digest", headers={"X-API-Key": api_key})
            assert response.status_code == 200, response.text
            assert len(response.content) <= 2048
            return response.json()

    ctx = GatewayContext(client=Orchestrator(),
                         session=Session(api_key=attacker.key, stance=Stance.attacker))
    doc = tools.digest(ctx, arena)
    assert doc["findings"]["count"] == 30 and doc["arena"]["id"] == arena
