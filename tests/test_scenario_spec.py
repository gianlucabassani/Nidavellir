"""
Tests for scenario schema v3 (ROADMAP Phase 1, P1-1).

Pins: the canonical ScenarioSpec validates a v3 topology; legacy vms[]/single-
network configs normalize into nodes[]/segments[]; structural errors are hard
(ValidationError) while soft issues only warn; the provider-facing
normalized_nodes()/primary_cidr() accept either shape; and the shipped
templates all validate against the schema.
"""
import pytest
from pydantic import ValidationError

import scenarios
from scenario_spec import (
    ProviderClass,
    ScenarioSpec,
    Stance,
    normalized_nodes,
    primary_cidr,
)

# --- a minimal valid v3 scenario --------------------------------------------

V3 = {
    "schema": "cyberguard/v3",
    "name": "two-node",
    "difficulty": "easy",
    "requires": {"provider_class": "container"},
    "network": {"segments": [{"name": "lab", "cidr": "10.10.0.0/24"}]},
    "nodes": [
        {"name": "web", "role": "victim", "image": "dvwa", "segments": ["lab"], "ports": [80]},
        {"name": "jump", "role": "attacker", "image": "kali",
         "segments": ["lab"], "entrypoint": True},
    ],
    "agents": [{"stance": "attacker", "node": "jump"}],
    "objectives": [{"description": "pop the box"}],
}


def test_valid_v3_spec_parses():
    spec = ScenarioSpec.from_raw(V3)
    assert spec.schema_version == "cyberguard/v3"
    assert spec.requires.provider_class is ProviderClass.container
    assert [n.name for n in spec.nodes] == ["web", "jump"]
    assert spec.agents[0].stance is Stance.attacker
    assert spec.nodes[0].ports == [80]
    assert spec.warnings() == []


# --- legacy normalization ----------------------------------------------------

LEGACY = {
    "name": "legacy",
    "difficulty": "medium",
    "requires": {"provider_class": "vm"},
    "network": {"name": "corp", "cidr": "192.168.0.0/24"},
    "vms": [
        {"name": "victim1", "role": "victim", "image": "victim-web", "flavor": "m1.small"},
        {"name": "attack1", "role": "attacker", "image": "kali"},
    ],
    "metadata": {"objectives": ["exploit the web app"], "tags": ["legacy"]},
}


def test_legacy_vms_become_nodes_on_a_default_segment():
    spec = ScenarioSpec.from_raw(LEGACY, scenario_id="legacy")
    assert [n.name for n in spec.nodes] == ["victim1", "attack1"]
    # The single legacy network becomes one segment every node attaches to.
    assert [s.name for s in spec.network.segments] == ["corp"]
    assert all(n.segments == ["corp"] for n in spec.nodes)
    # The legacy attacker is promoted to the entrypoint/foothold.
    assert spec.nodes[1].entrypoint is True
    # metadata.objectives / tags are lifted to first-class fields.
    assert spec.objectives[0].description == "exploit the web app"
    assert spec.tags == ["legacy"]


def test_normalized_nodes_handles_both_shapes():
    assert [n["name"] for n in normalized_nodes(V3)] == ["web", "jump"]
    assert [n["name"] for n in normalized_nodes(LEGACY)] == ["victim1", "attack1"]
    # legacy flavor is carried through for the OpenStack mapping
    assert normalized_nodes(LEGACY)[0]["flavor"] == "m1.small"


def test_primary_cidr_from_either_shape():
    assert primary_cidr(V3) == "10.10.0.0/24"
    assert primary_cidr(LEGACY) == "192.168.0.0/24"
    assert primary_cidr({"network": {}}) is None


# --- hard structural errors --------------------------------------------------


def test_node_without_image_is_rejected():
    bad = {**V3, "nodes": [{"name": "x", "role": "victim", "segments": ["lab"]}]}
    with pytest.raises(ValidationError):
        ScenarioSpec.from_raw(bad)


def test_undefined_segment_reference_is_rejected():
    bad = {**V3, "nodes": [{"name": "x", "image": "i", "segments": ["nope"]}]}
    with pytest.raises(ValidationError, match="undefined segment"):
        ScenarioSpec.from_raw(bad)


def test_duplicate_node_names_rejected():
    bad = {
        **V3,
        "nodes": [
            {"name": "dup", "image": "a", "segments": ["lab"]},
            {"name": "dup", "image": "b", "segments": ["lab"]},
        ],
    }
    with pytest.raises(ValidationError, match="duplicate node name"):
        ScenarioSpec.from_raw(bad)


def test_agent_bound_to_unknown_node_rejected():
    bad = {**V3, "agents": [{"stance": "attacker", "node": "ghost"}]}
    with pytest.raises(ValidationError, match="unknown node"):
        ScenarioSpec.from_raw(bad)


def test_empty_topology_rejected():
    with pytest.raises(ValidationError):
        ScenarioSpec.from_raw({"name": "empty", "nodes": []})


def test_bad_slug_and_port_rejected():
    with pytest.raises(ValidationError):
        ScenarioSpec.from_raw({**V3, "nodes": [{"name": "Bad Name", "image": "i"}]})
    with pytest.raises(ValidationError):
        ScenarioSpec.from_raw(
            {**V3, "nodes": [{"name": "ok", "image": "i", "segments": ["lab"],
                              "ports": [99999]}]}
        )


# --- soft advisories (do not block) -----------------------------------------


def test_attacker_not_on_entrypoint_warns_but_loads():
    spec = ScenarioSpec.from_raw(
        {
            **V3,
            "nodes": [
                {"name": "web", "role": "victim", "image": "dvwa", "segments": ["lab"]},
                {"name": "jump", "role": "attacker", "image": "kali", "segments": ["lab"]},
            ],
            "agents": [{"stance": "attacker", "node": "jump"}],
        }
    )
    warnings = spec.warnings()
    assert any("entrypoint" in w for w in warnings)


def test_unused_segment_warns():
    spec = ScenarioSpec.from_raw(
        {
            **V3,
            "network": {"segments": [{"name": "lab"}, {"name": "dmz"}]},
        }
    )
    assert any("dmz" in w for w in spec.warnings())


# --- the shipped templates validate -----------------------------------------


@pytest.mark.parametrize(
    "scenario_id,provider_class,n_nodes",
    [
        ("basic_pentest", "vm", 3),
        ("container_web_pentest", "container", 2),
        ("random_vulnhub", "vm", 2),
    ],
)
def test_shipped_templates_validate(scenario_id, provider_class, n_nodes):
    spec = scenarios.load_scenario_spec(scenario_id)
    assert spec is not None, f"{scenario_id} must validate against schema v3"
    assert spec.requires.provider_class.value == provider_class
    assert len(spec.nodes) == n_nodes
    # every template wires at least an attacker stance onto a foothold
    assert any(b.stance is Stance.attacker for b in spec.agents)


def test_registry_marks_templates_valid_with_node_counts():
    by_id = {s["id"]: s for s in scenarios.list_scenarios()}
    assert by_id["basic_pentest"]["valid"] is True
    assert by_id["basic_pentest"]["nodes"] == 3
    assert by_id["container_web_pentest"]["provider_class"] == "container"


# --- published JSON Schema ---------------------------------------------------


def test_json_schema_uses_alias_and_marks_nodes_required():
    from scenario_spec import json_schema

    schema = json_schema()
    assert "schema" in schema["properties"]   # the `schema` alias, not schema_version
    assert "nodes" in schema["required"]
