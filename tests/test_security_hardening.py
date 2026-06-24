"""
Security-hardening pass: SSRF guard (netguard), the SUT repo validator, the
events ground-truth redaction (agent role), the configurator budget/cross-session
gates, the Requires egress/mirror passthrough, and the AWS node-name output.
"""
import pytest
from fastapi.testclient import TestClient


def _client(role, name=None):
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name or f"{role}-sec", role=role)
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


def _active_arena(iid, scenario="container_web_pentest", bind_configurator=None):
    from database import Database

    db = Database()
    db.create_deployment(iid, iid, scenario, provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    db.update_deployment(
        iid, status="active",
        outputs={
            "node_victim_name": "nv-victim",
            "node_kali_name": "nv-kali",
            "node_kali_ssh_command": "docker exec -it nv-kali bash",
        },
        actor="test",
    )
    # D1: agent keys that drive the configurator setup phase must be bound.
    if bind_configurator:
        db.record_event(
            iid, "agent_binding",
            {"agent_name": bind_configurator, "stance": "configurator"}, actor="test",
        )
    return iid


# --- netguard (SSRF) ---------------------------------------------------------


def test_netguard_blocks_internal_and_metadata_literals():
    import netguard

    for bad in [
        "https://169.254.169.254/latest/meta-data/",   # cloud metadata
        "https://127.0.0.1/x", "https://10.0.0.5/x",
        "https://192.168.1.1/x", "https://[::1]/x",
        "https://0.0.0.0/x", "https://100.64.0.1/x",    # CGNAT
    ]:
        with pytest.raises(netguard.UnsafeHostError):
            netguard.assert_public_host(bad, resolve=False)


def test_netguard_allows_public_literal_and_defers_hostnames_without_dns():
    import netguard

    assert netguard.assert_public_host("https://8.8.8.8/x", resolve=False)
    # literal-only mode does no DNS, so a hostname passes (provider re-checks it)
    assert netguard.assert_public_host("https://github.com/org/proj", resolve=False)


def test_sut_request_rejects_internal_repo_host():
    import pydantic

    import api

    with pytest.raises(pydantic.ValidationError):
        api.SutArenaRequest(instance_id="x", repo="https://169.254.169.254/meta")


# --- events ground-truth redaction (authz #5) --------------------------------


def test_events_redact_matched_vuln_id_for_agent_not_operator():
    from database import Database

    db = Database()
    iid = _active_arena("sec-events")
    db.record_event(
        iid, "finding",
        {"finding_id": "f1", "title": "sqli", "cwe": "CWE-89",
         "matched_vuln_id": "vuln-sqli", "actor": "att"},
        actor="att",
    )
    op = _client("operator", "ev-op")
    ag = _client("agent", "ev-ag")

    op_ev = next(e for e in op.get(f"/deployments/{iid}/events").json()["events"]
                 if e["type"] == "finding")
    ag_ev = next(e for e in ag.get(f"/deployments/{iid}/events").json()["events"]
                 if e["type"] == "finding")
    assert op_ev["payload"]["matched_vuln_id"] == "vuln-sqli"   # operator: ground truth
    assert "matched_vuln_id" not in ag_ev["payload"]            # agent: stripped
    # the global feed redacts too
    ag_global = ag.get("/events").json()["events"]
    assert all("matched_vuln_id" not in (e.get("payload") or {})
               for e in ag_global if e["type"] == "finding")


# --- configurator budget + cross-session gates -------------------------------


def test_propose_rejected_when_budget_exhausted():
    op = _client("operator", "cfg-op-b")
    ag = _client("agent", "cfg-ag-b")
    iid = _active_arena("sec-budget", bind_configurator="cfg-ag-b")
    assert op.post(f"/arenas/{iid}/setup/start",
                   json={"mode": "hitl", "command_budget": 1}).status_code == 200
    # propose + approve consumes the only budget slot
    sid = ag.post(f"/arenas/{iid}/setup/propose",
                  json={"node": "victim", "command": "echo 1"}).json()["step_id"]
    assert op.post(f"/arenas/{iid}/setup/proposals/{sid}/approve").status_code == 200
    # the next propose is refused — budget is now enforced at propose time too
    r = ag.post(f"/arenas/{iid}/setup/propose", json={"node": "victim", "command": "echo 2"})
    assert r.status_code == 429


def test_approve_rejects_cross_session_proposal():
    op = _client("operator", "cfg-op-x")
    ag = _client("agent", "cfg-ag-x")
    iid = _active_arena("sec-xsession", bind_configurator="cfg-ag-x")
    op.post(f"/arenas/{iid}/setup/start", json={"mode": "hitl", "command_budget": 10})
    sid = ag.post(f"/arenas/{iid}/setup/propose",
                  json={"node": "victim", "command": "echo old"}).json()["step_id"]
    op.post(f"/arenas/{iid}/setup/finish")                       # close session A
    op.post(f"/arenas/{iid}/setup/start", json={"mode": "hitl", "command_budget": 10})  # session B
    # approving session A's proposal under session B must be refused
    r = op.post(f"/arenas/{iid}/setup/proposals/{sid}/approve")
    assert r.status_code == 409
    assert "different setup session" in r.text


# --- Requires egress/mirror passthrough (providers #8) -----------------------


def test_requires_egress_mirror_survive_validation():
    from scenario_spec import ScenarioSpec

    spec = ScenarioSpec.from_raw({
        "schema": "nidavellir/v3", "name": "x",
        "requires": {"provider_class": "container", "egress": "open", "mirror": "off"},
        "nodes": [{"name": "n", "image": "alpine", "segments": []}],
    })
    assert spec.requires.egress == "open"
    assert spec.requires.mirror == "off"


# --- AWS node-name output (providers #1) -------------------------------------


def test_aws_emits_node_name_key():
    from providers.aws import AWSProvider

    flat = AWSProvider()._post_process_outputs({
        "node_private_ips": {"web": "10.0.0.5"},
        "node_instance_ids": {"web": "i-0abc"},
        "node_roles": {"web": "victim"},
    })
    # the WebUI discovers nodes via node_<name>_name — must be present for AWS
    assert flat["node_web_name"] == "i-0abc"
    assert flat["node_web_private_ip"] == "10.0.0.5"
