"""
FR-04 (review item): an agent key can no longer read or create outside its arena.

- ``GET /deployments``, ``GET /events``, ``POST /deploy`` and ``POST /arenas/custom``
  are operator-only.
- ``GET /status/{id}``, ``GET /deployments/{id}/events`` and the agent-session
  announcement require the caller's binding to that arena.
- An agent reading its own arena's events sees only the allowlisted event types
  (``event_visibility``), never operator judgment or validator truth.

Review item U5 is exercised by
``test_unbound_agent_cannot_read_decrypted_outputs``: before FR-04 the same request
returned 200 with the decrypted secret output.
"""
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import crypto

AGENT_NAME = "fr04-agent"
OTHER_AGENT = "fr04-other-agent"
SECRET_OUTPUT = "fr04-s3cret-soc-password"


def _client(role, name):
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name, role=role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    client.db = Database()
    client.key = key
    return client


@pytest.fixture()
def operator():
    return _client("operator", "fr04-operator")


@pytest.fixture()
def agent():
    return _client("agent", AGENT_NAME)


def _arena(db, iid, outputs=None):
    db.create_deployment(iid, iid, "container_web_pentest", provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    db.update_deployment(
        iid, status="active",
        outputs=outputs or {"node_victim_name": f"nv-{iid}-victim"}, actor="test",
    )
    return iid


def _bind(operator, iid, stance=None, name=AGENT_NAME):
    body = {"agent_name": name}
    if stance:
        body["stance"] = stance
    response = operator.post(f"/arenas/{iid}/bindings", json=body)
    assert response.status_code == 200, response.text


@pytest.fixture()
def encryption_on(monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_default_cipher()
    yield
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "")
    crypto.reset_default_cipher()


# --- U5: decrypted outputs never reach an unbound agent ---------------------


def test_unbound_agent_cannot_read_decrypted_outputs(operator, agent, encryption_on):
    from sqlalchemy import text

    iid = _arena(operator.db, "fr04-u5", outputs={
        "node_victim_name": "nv-fr04-u5-victim",
        "soc_credentials": {"username": "admin", "password": SECRET_OUTPUT},
    })
    with operator.db._engine.connect() as conn:
        stored = conn.execute(text("SELECT outputs FROM deployments WHERE id = :id"),
                              {"id": iid}).scalar_one()
    assert stored.startswith("enc:v1:") and SECRET_OUTPUT not in stored

    response = agent.get(f"/status/{iid}")
    assert response.status_code == 403, response.text
    assert SECRET_OUTPUT not in response.text

    # The owner of the arena (the operator) still reads the decrypted outputs.
    owner = operator.get(f"/status/{iid}")
    assert owner.status_code == 200
    assert owner.json()["outputs"]["soc_credentials"]["password"] == SECRET_OUTPUT


# --- operator-only routes ----------------------------------------------------


OPERATOR_ONLY = (
    ("get", "/deployments", None),
    ("get", "/events", None),
    ("post", "/deploy", {"scenario": "container_web_pentest", "instance_id": "fr04-deploy"}),
    ("post", "/arenas/custom", {"instance_id": "fr04-custom", "attackers": ["kali-cli"],
                                "victims": ["dvwa"]}),
)


@pytest.mark.parametrize("bound", [False, True], ids=["unbound", "bound"])
@pytest.mark.parametrize(("method", "path", "body"), OPERATOR_ONLY,
                         ids=[f"{m.upper()} {p}" for m, p, _ in OPERATOR_ONLY])
def test_operator_only_routes_refuse_agent_keys(operator, agent, monkeypatch,
                                                method, path, body, bound):
    import api

    queued = []
    monkeypatch.setattr(api.deploy_lab, "delay", lambda **kw: queued.append(kw))
    iid = _arena(operator.db, f"fr04-oponly-{method}-{path.strip('/').replace('/', '-')}-{bound}")
    if bound:  # even a binding (any stance) does not open these routes
        _bind(operator, iid)
    before = {d["id"] for d in operator.db.list_deployments()}
    kwargs = {"json": body} if body is not None else {}
    response = getattr(agent, method)(path, **kwargs)
    assert response.status_code == 403, response.text
    assert queued == []
    assert {d["id"] for d in operator.db.list_deployments()} == before
    assert SECRET_OUTPUT not in response.text


@pytest.mark.parametrize("path", ["/deployments", "/events"])
def test_operator_keeps_global_reads(operator, path):
    _arena(operator.db, f"fr04-op-read-{path.strip('/')}")
    assert operator.get(path).status_code == 200


def test_operator_can_still_deploy(operator, monkeypatch):
    import api

    queued = []
    monkeypatch.setattr(api.deploy_lab, "delay", lambda **kw: queued.append(kw))
    response = operator.post("/deploy", json={"scenario": "container_web_pentest",
                                              "instance_id": "fr04-op-deploy"})
    assert response.status_code == 200, response.text
    assert len(queued) == 1
    # Operators are never bound: no binding event is created by a deploy.
    import bindings
    events = operator.db.list_events(response.json()["instance_id"],
                                     types=bindings.BINDING_EVENT_TYPES)
    assert events == []


# --- per-arena reads require a binding ---------------------------------------


@pytest.mark.parametrize("path", ["/status/{iid}", "/deployments/{iid}/events"])
def test_per_arena_reads_require_binding_to_that_arena(operator, agent, path):
    own = _arena(operator.db, f"fr04-member-own-{path.split('/')[1]}")
    other = _arena(operator.db, f"fr04-member-other-{path.split('/')[1]}")
    assert agent.get(path.format(iid=own)).status_code == 403
    _bind(operator, own, stance="attacker")
    assert agent.get(path.format(iid=own)).status_code == 200
    # A binding to one arena never opens another.
    assert agent.get(path.format(iid=other)).status_code == 403
    # Revoking the binding closes the read again.
    assert operator.delete(f"/arenas/{own}/bindings/{AGENT_NAME}").status_code == 200
    assert agent.get(path.format(iid=own)).status_code == 403


def test_unknown_arena_stays_404(operator, agent):
    # Arena routes keep their existing 404-before-403 order (destroy, capabilities
    # and budget already do this); arena ids are random UUIDs.
    assert operator.get("/status/fr04-ghost").status_code == 404
    assert agent.get("/status/fr04-ghost").status_code == 404
    assert agent.get("/deployments/fr04-ghost/events").status_code == 404


def test_paused_binding_may_still_read(operator, agent):
    # Reads are not capability-gated (bindings.py): pause halts actions, not reads.
    iid = _arena(operator.db, "fr04-paused-read")
    _bind(operator, iid, stance="attacker")
    assert operator.post(f"/arenas/{iid}/bindings/{AGENT_NAME}/pause").status_code == 200
    assert agent.get(f"/status/{iid}").status_code == 200
    assert agent.get(f"/deployments/{iid}/events").status_code == 200


def test_bound_agent_reads_its_own_status(operator, agent):
    iid = _arena(operator.db, "fr04-own-status", outputs={
        "node_victim_name": "nv-v", "node_victim_private_ip": "172.30.0.2"})
    _bind(operator, iid, stance="attacker")
    body = agent.get(f"/status/{iid}").json()
    assert body["status"] == "active"
    assert body["outputs"]["node_victim_private_ip"] == "172.30.0.2"


# --- agent-session announcement requires a binding ---------------------------


def test_announce_requires_binding(operator, agent):
    iid = _arena(operator.db, "fr04-announce")
    body = {"model": "m", "provider": "p", "stance": "attacker"}
    assert agent.post(f"/arenas/{iid}/agent-session", json=body).status_code == 403
    assert operator.db.list_events(iid, types=("agent_session",)) == []
    _bind(operator, iid, stance="attacker")
    assert agent.post(f"/arenas/{iid}/agent-session", json=body).status_code == 200
    assert len(operator.db.list_events(iid, types=("agent_session",))) == 1


# --- event allowlist ---------------------------------------------------------


# Every event type the orchestrator emits today that must stay operator-only.
HIDDEN_TYPES = (
    "finding_verification", "http_request_group",
    "source_review_session", "source_review_capture", "source_site_review",
    "source_review_capture_start",
    "research_campaign", "campaign_finding", "campaign_disclosure", "campaign_bundle",
    "lifecycle_recipe", "lifecycle_observation", "engagement_intent", "session_preflight",
    "setup_session", "setup_step", "setup_finished", "setup_proposal",
    "setup_proposal_decision", "setup_prearm", "session_prearm", "source_bundle_intake",
    "agent_binding", "agent_binding_revoked", "agent_binding_paused",
    "agent_binding_resumed", "budget_reserved", "budget_settled", "budget_denied",
    "budget_policy_revised", "arena_stop", "system_stop", "stop_verified", "stop_cleared",
    "reset_requested", "reset_replacement_created", "reset_replacement_of",
    "reset_replaced_by", "reset_mismatch", "deploy_failed", "reaped", "record_deleted",
    "research_code_lookup", "helper_job_submitted", "poc_job_finished",
    "poc_job_cancelled", "monitor_signal",
)
# Participant activity and lifecycle status an agent may read in its own arena.
VISIBLE_TYPES = (
    "created", "status", "agent_session", "agent_exec", "http_request", "browser_visit",
    "file_upload", "file_download", "mitm_observe", "workspace_diff", "evidence_artifact",
    "poc_job_submitted", "poc_job_cancel_requested", "forward_opened",
    "forward_connected", "forward_closed", "forward_revoked", "finding",
)


def _seed_every_type(db, iid):
    for kind in HIDDEN_TYPES + VISIBLE_TYPES + ("fr04_brand_new_type",):
        if kind in ("created", "status"):
            continue  # written by the lifecycle already
        payload = {"marker": f"{kind}-payload"}
        if kind == "finding":
            payload = {"finding_id": "f-agent", "title": "claimed sqli", "manual": False,
                       "matched_vuln_id": "sqli-login",
                       "validation": {"verdict": "confirmed", "confirmed": True}}
        db.record_event(iid, kind, payload, actor="seed")
    db.record_event(iid, "finding", {
        "finding_id": "f-operator", "title": "operator-entered truth", "manual": True,
        "matched_vuln_id": "sqli-login", "validation": None}, actor="operator")


def test_allowlist_matches_the_reviewed_sets():
    import event_visibility

    assert set(VISIBLE_TYPES) == set(event_visibility.AGENT_VISIBLE_EVENT_TYPES)
    assert not set(HIDDEN_TYPES) & event_visibility.AGENT_VISIBLE_EVENT_TYPES
    assert event_visibility.visible_event_types("defender") == (
        event_visibility.AGENT_VISIBLE_EVENT_TYPES | {"monitor_signal"})
    for stance in (None, "attacker", "mitm", "configurator", "unknown"):
        assert event_visibility.visible_event_types(stance) == (
            event_visibility.AGENT_VISIBLE_EVENT_TYPES)


def test_unknown_event_types_are_hidden_by_default():
    import event_visibility

    events = [{"type": "fr04_brand_new_type", "payload": {"x": 1}},
              {"type": "agent_exec", "payload": {"node": "jump"}}]
    assert [e["type"] for e in event_visibility.redact_for_agent(events, None)] == [
        "agent_exec"]


@pytest.mark.parametrize("stance", ["attacker", None, "defender"])
def test_bound_agent_sees_only_allowlisted_types(operator, agent, stance):
    import event_visibility

    iid = _arena(operator.db, f"fr04-allow-{stance}")
    _bind(operator, iid, stance=stance)
    _seed_every_type(operator.db, iid)

    events = agent.get(f"/deployments/{iid}/events?limit=500").json()["events"]
    seen = {e["type"] for e in events}
    assert seen <= event_visibility.visible_event_types(stance)
    assert not seen & (set(HIDDEN_TYPES) - event_visibility.visible_event_types(stance))
    assert "fr04_brand_new_type" not in seen
    assert {"created", "status", "agent_exec", "finding"} <= seen
    assert ("monitor_signal" in seen) is (stance == "defender")
    findings = [e for e in events if e["type"] == "finding"]
    assert [f["payload"]["finding_id"] for f in findings] == ["f-agent"]
    assert "matched_vuln_id" not in findings[0]["payload"]
    assert "validation" not in findings[0]["payload"]
    assert "operator-entered truth" not in json.dumps(events)
    assert "sqli-login" not in json.dumps(events)

    # The operator still reads everything, unredacted.
    op_types = {e["type"] for e in operator.get(
        f"/deployments/{iid}/events?limit=500").json()["events"]}
    assert set(HIDDEN_TYPES) <= op_types


def test_agent_type_filter_cannot_select_a_hidden_type(operator, agent):
    iid = _arena(operator.db, "fr04-type-filter")
    _bind(operator, iid, stance="attacker")
    _seed_every_type(operator.db, iid)
    for hidden in ("finding_verification", "lifecycle_recipe", "monitor_signal",
                   "fr04_brand_new_type"):
        response = agent.get(f"/deployments/{iid}/events", params={"type": hidden})
        assert response.status_code == 200
        assert response.json()["events"] == []
    shown = agent.get(f"/deployments/{iid}/events", params={"type": "agent_exec"})
    assert [e["type"] for e in shown.json()["events"]] == ["agent_exec"]


def test_agent_limit_counts_visible_events_only(operator, agent):
    # Hidden noise must not starve the agent's window: the filter runs in SQL.
    iid = _arena(operator.db, "fr04-window")
    _bind(operator, iid, stance="attacker")
    operator.db.record_event(iid, "agent_exec", {"node": "jump"}, actor="seed")
    for _ in range(30):
        operator.db.record_event(iid, "budget_settled", {"outcome": "spent"}, actor="seed")
    events = agent.get(f"/deployments/{iid}/events?limit=3").json()["events"]
    assert [e["type"] for e in events][0] == "agent_exec"


# --- the gateway keeps working through bound routes --------------------------


def _gateway(client, stance):
    from gateway.rest_client import RestClient
    from gateway.session import Session
    from gateway.stances import Stance
    from gateway.tools import GatewayContext

    return GatewayContext(
        client=RestClient("http://testserver", http=client),
        session=Session(api_key=client.key, stance=Stance(stance) if stance else None),
    )


def test_gateway_tools_work_for_a_bound_agent_against_the_real_api(operator, agent):
    from gateway import tools

    outputs = {
        "node_jump_name": "nv-jump", "node_jump_ssh_command": "docker exec nv-jump sh",
        "node_jump_private_ip": "172.30.0.3",
        "node_victim_name": "nv-victim", "node_victim_private_ip": "172.30.0.2",
    }
    iid = _arena(operator.db, "fr04-gateway", outputs=outputs)
    _bind(operator, iid, stance="attacker")
    attacker = _gateway(agent, "attacker")

    assert tools.announce_agent(attacker, iid, "m", "p")["recorded"] is True
    assert tools.arena_status(attacker, iid)["status"] == "active"
    topology = tools.get_topology(attacker, iid)
    assert {n["node"] for n in topology["nodes"]} == {"jump", "victim"}
    assert [t["node"] for t in tools.list_targets(attacker, iid)["targets"]] == ["victim"]
    assert tools.get_briefing(attacker, iid)["status"] == "active"


def test_gateway_defender_feed_is_allowlisted(operator):
    from gateway import tools

    defender_key = _client("agent", "fr04-defender")
    iid = _arena(operator.db, "fr04-gateway-defender")
    _bind(operator, iid, stance="defender", name="fr04-defender")
    _seed_every_type(operator.db, iid)
    feed = tools.query_events(_gateway(defender_key, "defender"), iid, limit=500)
    assert {e["type"] for e in feed["events"]} >= {"agent_exec", "monitor_signal"}
    assert not {e["type"] for e in feed["events"]} & {"finding_verification",
                                                      "lifecycle_recipe"}


def test_gateway_cannot_reopen_the_holes(operator, agent):
    from gateway import tools
    from gateway.rest_client import GatewayRestError

    bound = _arena(operator.db, "fr04-gateway-bound")
    foreign = _arena(operator.db, "fr04-gateway-foreign")
    _bind(operator, bound, stance="attacker")
    attacker = _gateway(agent, "attacker")
    with pytest.raises(GatewayRestError, match="403"):
        tools.deploy_arena(attacker, scenario="container_web_pentest")
    with pytest.raises(GatewayRestError, match="403"):
        tools.arena_status(attacker, foreign)
    with pytest.raises(GatewayRestError, match="403"):
        tools.announce_agent(attacker, foreign, "m", "p")
    defender = _gateway(agent, "defender")
    with pytest.raises(GatewayRestError, match="403"):
        tools.query_events(defender, foreign)
