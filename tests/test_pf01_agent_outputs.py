"""
PF-01 U5 (review 2026-11-16): decrypted outputs reached agent keys.

``/status/{id}`` returned an arena's whole decrypted ``outputs`` to any bound agent.
Providers also store operator material there: the Terraform/OpenStack contract's
``soc_credentials`` (the defender SOC dashboard password, mirrored by the mock
provider) and docker-local's ``setup_shell`` (a host ``docker exec`` into the
victim). Agents now get a deny-by-default allowlist of topology keys; operators
see everything.
"""
import uuid

import pytest

from tests.research_support import bind, client

OUTPUTS = {
    "provider": "mock",
    "lab_networks": ["nidavellir-x-research"],
    "node_victim_name": "victim",
    "node_victim_private_ip": "10.10.0.3",
    "node_victim_url": "http://127.0.0.1:32834",
    "node_victim_state": "running",
    "node_victim_setup_shell": "docker exec -it nv-x-victim /bin/bash",
    "node_victim_sut_source": "/opt/victim",
    "node_kali_name": "kali",
    "node_kali_ssh_command": "docker exec -it nv-x-kali /bin/bash",
    "soc_dashboard_url": "https://192.168.1.50:5601",
    "soc_credentials": {"username": "cyberrange-admin", "password": "CyberRange2024!"},
    "setup_instructions": "VM LOG ... password ...",
    "future_provider_secret": "s3cr3t",
}
WITHHELD = {"node_victim_setup_shell", "node_victim_sut_source", "soc_credentials",
            "setup_instructions", "future_provider_secret"}


@pytest.fixture()
def arena():
    from database import Database

    db = Database()
    arena_id = uuid.uuid4().hex[:16]
    db.create_deployment(arena_id, arena_id, "custom", provider=None, actor="test")
    db.update_deployment(arena_id, status="deploying", actor="test")
    db.update_deployment(arena_id, status="active", outputs=OUTPUTS, actor="test")
    return arena_id


def test_agent_sees_topology_but_not_operator_material(arena):
    operator, agent = client("operator"), client("agent")
    bind(operator, arena, agent)
    outputs = agent.get(f"/status/{arena}").json()["outputs"]
    assert not WITHHELD & set(outputs)
    assert "CyberRange2024!" not in str(outputs)
    assert outputs["withheld_outputs"] == len(WITHHELD)
    for key in ("node_victim_private_ip", "node_victim_url", "node_kali_ssh_command",
                "lab_networks", "soc_dashboard_url"):
        assert outputs[key] == OUTPUTS[key]


def test_operator_still_sees_every_output(arena):
    outputs = client("operator").get(f"/status/{arena}").json()["outputs"]
    assert outputs == OUTPUTS


def test_unknown_keys_are_withheld_by_default():
    import api

    assert api._agent_visible_outputs({"node_a_password": "x", "node_a_name": "a"}) == {
        "node_a_name": "a"}
