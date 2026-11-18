"""
F1 (work order 2026-11-18): arena time-box extension.

``POST /arenas/{id}/extend`` moves the reaper TTL and the durable budget deadline
forward together, so research continues on the same arena instead of a redeploy and
a re-grant. Operators may extend; an agent only through a ``configurator`` binding,
and never while a stop holds. Refusals carry a stable ``code``.
"""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api
import database
from auth import generate_api_key, hash_api_key
from database import Database
from timeutil import db_now


def _client(role, name=None):
    name = name or f"f1-{role}-{uuid.uuid4().hex[:8]}"
    key = generate_api_key()
    Database().create_api_key(hash_api_key(key), name, role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    client.name = name
    return client


_CREATED: list[str] = []


@pytest.fixture(autouse=True)
def _retire_arenas():
    """Short or elapsed TTLs here must not leak into later reaper tests that sweep
    the shared test database: retire every arena this module created."""
    yield
    db = Database()
    while _CREATED:
        arena = _CREATED.pop()
        status = db.get_deployment(arena)["status"]
        if status in ("pending", "deploying", "active"):
            db.update_deployment(arena, status="destroying")
            status = "destroying"
        if status == "destroying":
            db.update_deployment(arena, status="destroyed")


def _arena(*, expires_in=60, age=timedelta(hours=2, minutes=59), status="active"):
    """An arena created `age` ago whose TTL and budget deadline end in `expires_in` s."""
    arena = str(uuid.uuid4())
    _CREATED.append(arena)
    db = Database()
    db.create_deployment(arena, arena[:8], "container_web_pentest", provider="mock",
                         expires_at=db_now() + timedelta(seconds=expires_in))
    db.update_deployment(arena, status="deploying")
    if status != "deploying":
        db.update_deployment(arena, status="active",
                             outputs={"node_victim_name": "mock-victim"})
    if status in ("destroying", "destroyed"):
        db.update_deployment(arena, status="destroying")
    if status == "destroyed":
        db.update_deployment(arena, status="destroyed")
    from models import Deployment
    with db._session() as session:
        session.get(Deployment, arena).created_at = db_now() - age
        session.commit()
    return arena


def _bind(operator, arena, agent, stance):
    response = operator.post(f"/arenas/{arena}/bindings",
                             json={"agent_name": agent.name, "stance": stance})
    assert response.status_code == 200, response.text


def _at(monkeypatch, offset):
    """Run the budget admission check `offset` in the future."""
    future = db_now() + offset
    monkeypatch.setattr(database, "db_now", lambda: future)


def test_extend_at_2h59m_lets_the_agents_next_call_succeed(monkeypatch):
    operator, attacker = _client("operator"), _client("agent")
    arena = _arena(expires_in=60)
    _bind(operator, arena, attacker, "attacker")
    before = Database().get_deployment(arena)["expires_at"]

    response = operator.post(f"/arenas/{arena}/extend", json={"seconds": 3600})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "extended" and body["replayed"] is False
    assert body["previous_expires_at"] == before
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires - datetime.fromisoformat(before) == timedelta(seconds=3600)
    assert body["deadline"] == body["expires_at"]

    capabilities = attacker.get(f"/arenas/{arena}/capabilities").json()
    assert capabilities["expires_at"] == body["expires_at"]
    assert capabilities["budget"]["deadline"] == body["deadline"]
    assert capabilities["operations"]["extend"]["reason"] == "stance_denied"

    # Five minutes later the old box has elapsed; the extended one has not.
    _at(monkeypatch, timedelta(minutes=5))
    finding = attacker.post(f"/arenas/{arena}/findings", json={"title": "after extension"})
    assert finding.status_code == 200, finding.text

    events = Database().list_events(arena, types=(database.ARENA_EXTENDED_EVENT,))
    assert len(events) == 1
    assert events[0]["payload"]["category"] == "lifecycle"
    assert events[0]["actor"] == operator.name


def test_without_extension_the_same_call_is_refused(monkeypatch):
    operator, attacker = _client("operator"), _client("agent")
    arena = _arena(expires_in=60)
    _bind(operator, arena, attacker, "attacker")
    _at(monkeypatch, timedelta(minutes=5))
    finding = attacker.post(f"/arenas/{arena}/findings", json={"title": "too late"})
    assert finding.status_code in (409, 423, 429), finding.text


def test_extension_starts_from_now_when_the_deadline_has_passed():
    operator = _client("operator")
    arena = _arena(expires_in=-120)  # elapsed, reaper has not run yet
    body = operator.post(f"/arenas/{arena}/extend", json={"seconds": 600}).json()
    expires = datetime.fromisoformat(body["expires_at"])
    assert abs((expires - db_now()) - timedelta(seconds=600)) < timedelta(seconds=5)


def test_tighter_budget_deadline_keeps_its_offset_and_stays_within_ttl():
    operator = _client("operator")
    arena = _arena(expires_in=3600, age=timedelta(minutes=1))
    tight = db_now() + timedelta(minutes=10)
    Database().revise_budget_policy(arena, action_cap=50, deadline=tight,
                                    actor="op", reason="tight window")
    body = operator.post(f"/arenas/{arena}/extend", json={"seconds": 1800}).json()
    deadline = datetime.fromisoformat(body["deadline"])
    assert abs(deadline - (tight + timedelta(seconds=1800))) < timedelta(seconds=1)
    assert deadline <= datetime.fromisoformat(body["expires_at"])


def test_same_idempotency_key_extends_once_and_rejects_different_input():
    operator = _client("operator")
    arena = _arena()
    request = {"seconds": 900, "idempotency_key": "extend-once-1"}
    first = operator.post(f"/arenas/{arena}/extend", json=request).json()
    again = operator.post(f"/arenas/{arena}/extend", json=request).json()
    assert again["replayed"] is True
    assert again["expires_at"] == first["expires_at"]
    assert Database().get_deployment(arena)["expires_at"] == first["expires_at"]
    assert len(Database().list_events(arena, types=(database.ARENA_EXTENDED_EVENT,))) == 1

    reused = operator.post(f"/arenas/{arena}/extend",
                           json={"seconds": 1200, "idempotency_key": "extend-once-1"})
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "idempotency_key_reused"


@pytest.mark.parametrize("status", ["destroying", "destroyed"])
def test_refuses_destroying_and_destroyed_with_a_clear_code(status):
    operator = _client("operator")
    arena = _arena(status=status)
    response = operator.post(f"/arenas/{arena}/extend", json={"seconds": 600})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "arena_not_extendable"


@pytest.mark.parametrize("seconds", [0, 299, 86401])
def test_seconds_are_bounded(seconds):
    operator = _client("operator")
    arena = _arena()
    assert operator.post(f"/arenas/{arena}/extend",
                         json={"seconds": seconds}).status_code == 422


def test_lifetime_ceiling_is_enforced(monkeypatch):
    import config

    monkeypatch.setattr(config, "ARENA_MAX_LIFETIME_SECONDS", 4 * 3600)
    operator = _client("operator")
    arena = _arena(expires_in=60, age=timedelta(hours=3))
    response = operator.post(f"/arenas/{arena}/extend", json={"seconds": 7200})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "max_lifetime_exceeded"
    assert operator.post(f"/arenas/{arena}/extend",
                         json={"seconds": 1800}).status_code == 200


def test_only_operator_or_configurator_binding_may_extend():
    operator = _client("operator")
    configurator, attacker, unbound = _client("agent"), _client("agent"), _client("agent")
    arena = _arena()
    _bind(operator, arena, configurator, "configurator")
    _bind(operator, arena, attacker, "attacker")

    assert unbound.post(f"/arenas/{arena}/extend", json={"seconds": 600}).status_code == 403
    assert attacker.post(f"/arenas/{arena}/extend", json={"seconds": 600}).status_code == 403
    response = configurator.post(f"/arenas/{arena}/extend", json={"seconds": 600})
    assert response.status_code == 200, response.text

    # A configurator binding is to *its* arena only.
    other = _arena()
    assert configurator.post(f"/arenas/{other}/extend",
                             json={"seconds": 600}).status_code == 403


def test_agent_cannot_extend_a_stopped_arena_but_operator_can():
    operator, configurator = _client("operator"), _client("agent")
    arena = _arena()
    _bind(operator, arena, configurator, "configurator")
    assert operator.post(f"/arenas/{arena}/stop", json={
        "reason": "hold", "idempotency_key": uuid.uuid4().hex}).status_code == 200
    refused = configurator.post(f"/arenas/{arena}/extend", json={"seconds": 600})
    assert refused.status_code == 423
    assert refused.json()["detail"]["code"] == "stop_active"
    assert operator.post(f"/arenas/{arena}/extend", json={"seconds": 600}).status_code == 200
    # Extension never lifts the stop.
    assert operator.get(f"/arenas/{arena}/budget").json()["arena"]["state"] != "open"


def test_extend_is_not_charged_against_the_action_budget():
    operator = _client("operator")
    arena = _arena()
    operator.post(f"/arenas/{arena}/extend", json={"seconds": 600})
    assert operator.get(f"/arenas/{arena}/budget").json()["policy"]["spent"] == 0


# --- gateway ------------------------------------------------------------------


def test_gateway_exposes_extend_to_configurator_and_operator_only():
    from gateway.config import GatewayConfig
    from gateway.server import build_server
    from gateway.session import Session
    from gateway.stances import Stance

    def names(stance):
        mcp = build_server(GatewayConfig(env={"NIDAVELLIR_STANCE": stance}))
        return {t.name for t in asyncio.run(mcp.list_tools())}

    assert "extend_arena" in names("configurator")
    assert "extend_arena" in names("operator")
    assert "extend_arena" not in names("attacker")
    assert not Session("k", Stance.attacker).can_use("extend_arena")


def test_gateway_extend_proxies_to_the_orchestrator():
    from gateway import tools
    from gateway.session import Session
    from gateway.stances import Stance
    from gateway.tools import GatewayContext, ToolNotAllowed

    class Client:
        calls = []

        def extend_arena(self, api_key, arena_id, seconds, idempotency_key=None):
            self.calls.append((api_key, arena_id, seconds, idempotency_key))
            return {"arena_id": arena_id, "expires_at": "later"}

    client = Client()
    ctx = GatewayContext(client=client, session=Session("cg_k", Stance.configurator))
    assert tools.extend_arena(ctx, "a1", 600, "key-12345")["expires_at"] == "later"
    assert client.calls == [("cg_k", "a1", 600, "key-12345")]
    attacker = GatewayContext(client=client, session=Session("cg_k", Stance.attacker))
    with pytest.raises(ToolNotAllowed):
        tools.extend_arena(attacker, "a1", 600)
