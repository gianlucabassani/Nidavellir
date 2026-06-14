"""
Tests for the AWS provider's scenario→Terraform compilation (ROADMAP P1-2 /
P5-2). The real apply needs an AWS account, so these pin the pure parts: the
v3 topology → tfvars mapping, image-map resolution, instance sizing, the
container-scenario rejection, and the per-node output flattening.
"""
import json

import pytest

import providers
from providers.aws import AWSProvider

SCENARIO = {
    "requires": {"provider_class": "vm"},
    "network": {"segments": [{"name": "corp", "cidr": "10.0.0.0/24"}, {"name": "dmz"}]},
    "nodes": [
        {"name": "dc", "role": "victim", "image": "ubuntu", "size": "large",
         "segments": ["corp"]},
        {"name": "jump", "role": "attacker", "image": "kali", "size": "medium",
         "segments": ["dmz", "corp"], "entrypoint": True, "ports": [22]},
        {"name": "fixed", "role": "victim", "image": "ami-0123456789abcdef0",
         "segments": ["dmz"]},
    ],
}


# --- registry ---------------------------------------------------------------


def test_aws_registered_as_vm_backend():
    assert "aws" in providers.available_providers()
    assert providers.infra_class_of("aws") == "vm"


# --- variable compilation ---------------------------------------------------


def test_compile_vars_shape():
    v = AWSProvider.compile_vars(SCENARIO, "arena-x")
    assert v["arena_id"] == "arena-x"
    assert {n["name"] for n in v["nodes"]} == {"dc", "jump", "fixed"}


def test_segments_keep_declared_cidr_and_synthesize_missing():
    segs = {s["name"]: s["cidr"] for s in AWSProvider.compile_vars(SCENARIO, "x")["segments"]}
    assert segs["corp"] == "10.0.0.0/24"          # declared cidr kept
    assert segs["dmz"].startswith("10.20.")       # synthesized /24
    assert segs["dmz"].endswith("/24")


def test_instance_type_mapping_and_flags():
    nodes = {n["name"]: n for n in AWSProvider.compile_vars(SCENARIO, "x")["nodes"]}
    assert nodes["dc"]["instance_type"] == "t3.large"
    assert nodes["jump"]["instance_type"] == "t3.medium"
    assert nodes["fixed"]["instance_type"] == "t3.small"   # default size
    assert nodes["jump"]["entrypoint"] is True
    assert nodes["jump"]["ports"] == [22]
    assert nodes["jump"]["segments"] == ["dmz", "corp"]


def test_image_map_resolution_into_ami_fields():
    nodes = {n["name"]: n for n in AWSProvider.compile_vars(SCENARIO, "x")["nodes"]}
    # logical "ubuntu"/"kali" → AMI name-filter + owner, no fixed id
    assert nodes["dc"]["ami"] is None
    assert nodes["dc"]["ami_owner"] == "099720109477"
    assert nodes["jump"]["ami_name"].startswith("kali-linux")
    # a concrete ami- id → fixed ami, no name lookup
    assert nodes["fixed"]["ami"] == "ami-0123456789abcdef0"
    assert nodes["fixed"]["ami_name"] is None


def test_nodes_without_segment_get_a_default():
    scenario = {
        "requires": {"provider_class": "vm"},
        "nodes": [{"name": "solo", "role": "victim", "image": "ubuntu"}],
    }
    v = AWSProvider.compile_vars(scenario, "x")
    assert [s["name"] for s in v["segments"]] == ["default"]
    assert v["nodes"][0]["segments"] == ["default"]


def test_write_vars_emits_tfvars_file(tmp_path):
    extra = AWSProvider()._write_vars(tmp_path, SCENARIO, "arena-x", None)
    assert extra == []
    data = json.loads((tmp_path / "arena.auto.tfvars.json").read_text())
    assert data["arena_id"] == "arena-x"
    assert {n["name"] for n in data["nodes"]} == {"dc", "jump", "fixed"}


# --- guards / outputs -------------------------------------------------------


def test_rejects_container_only_scenarios():
    result = AWSProvider().deploy({"requires": {"provider_class": "container"}}, "x")
    assert result["success"] is False
    assert "vm" in result["error"]


def test_post_process_flattens_per_node_maps():
    raw = {
        "provider": "aws",
        "arena_vpc_id": "vpc-1",
        "node_private_ips": {"dc": "10.0.0.5", "jump": "10.20.1.6", "fixed": "10.20.1.7"},
        "node_instance_ids": {"dc": "i-1", "jump": "i-2", "fixed": "i-3"},
        "node_roles": {"dc": "victim", "jump": "attacker", "fixed": "victim"},
    }
    flat = AWSProvider()._post_process_outputs(raw)

    assert flat["provider"] == "aws"
    assert flat["arena_vpc_id"] == "vpc-1"
    assert flat["node_dc_private_ip"] == "10.0.0.5"
    assert flat["node_jump_instance_id"] == "i-2"
    assert flat["node_fixed_private_ip"] == "10.20.1.7"
    # legacy role keys resolve to the FIRST node of each canonical role
    assert flat["victim_vm_private_ip"] == "10.0.0.5"   # dc, not fixed
    assert flat["attack_vm_private_ip"] == "10.20.1.6"


@pytest.mark.parametrize("provider_class", ["vm", "any"])
def test_supports_vm_and_any(provider_class):
    assert AWSProvider._supports({"requires": {"provider_class": provider_class}})
