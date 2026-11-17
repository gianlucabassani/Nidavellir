"""
Tests for the libvirt/QEMU provider's scenario→Terraform compilation (local-VM
enabler). The real apply needs libvirtd + KVM + the dmacvicar/libvirt plugin, so
these pin the pure parts: the v3 topology → tfvars mapping, sizing, the
disk-source-vs-base-image fallback, the container-scenario rejection, and the
per-node output flattening — mirroring the AWS driver's posture.
"""
import json

import pytest

import providers
from providers.libvirt import LibvirtProvider

SCENARIO = {
    "requires": {"provider_class": "vm"},
    "network": {"segments": [{"name": "corp", "cidr": "10.0.0.0/24"}, {"name": "dmz"}]},
    "nodes": [
        {"name": "dc", "role": "victim", "image": "ubuntu-22.04", "size": "large",
         "segments": ["corp"]},
        {"name": "jump", "role": "attacker", "image": "kali", "size": "medium",
         "segments": ["dmz", "corp"], "entrypoint": True, "ports": [22]},
        {"name": "custom", "role": "victim",
         "image": "https://images.example/test.qcow2", "segments": ["dmz"]},
    ],
}


# --- registry ---------------------------------------------------------------


def test_libvirt_registered_as_vm_backend():
    assert "libvirt" in providers.available_providers()
    assert providers.infra_class_of("libvirt") == "vm"


# --- variable compilation ---------------------------------------------------


def test_compile_vars_shape_and_hypervisor_fields():
    v = LibvirtProvider.compile_vars(SCENARIO, "arena-x")
    assert v["arena_id"] == "arena-x"
    assert v["libvirt_uri"]       # carries the hypervisor URI
    assert v["base_image"]        # carries the default cloud image
    assert {n["name"] for n in v["nodes"]} == {"dc", "jump", "custom"}


def test_segments_keep_declared_cidr_and_synthesize_missing():
    segs = {s["name"]: s["cidr"] for s in LibvirtProvider.compile_vars(SCENARIO, "x")["segments"]}
    assert segs["corp"] == "10.0.0.0/24"      # declared cidr kept
    assert segs["dmz"].startswith("10.30.")   # synthesized /24 (libvirt range)
    assert segs["dmz"].endswith("/24")


def test_size_to_memory_and_vcpu():
    nodes = {n["name"]: n for n in LibvirtProvider.compile_vars(SCENARIO, "x")["nodes"]}
    assert (nodes["dc"]["memory"], nodes["dc"]["vcpu"]) == (4096, 2)     # large
    assert (nodes["jump"]["memory"], nodes["jump"]["vcpu"]) == (2048, 2)  # medium
    assert (nodes["custom"]["memory"], nodes["custom"]["vcpu"]) == (1024, 1)  # default small
    assert nodes["jump"]["entrypoint"] is True
    assert nodes["jump"]["ports"] == [22]
    assert nodes["jump"]["segments"] == ["dmz", "corp"]


def test_image_source_uses_concrete_disk_else_base_image():
    nodes = {n["name"]: n for n in LibvirtProvider.compile_vars(SCENARIO, "x")["nodes"]}
    # a concrete qcow2 URL is used as the disk source
    assert nodes["custom"]["image"] == "https://images.example/test.qcow2"
    # logical names (no per-image libvirt map yet) fall back to base_image (null)
    assert nodes["dc"]["image"] is None
    assert nodes["jump"]["image"] is None


def test_nodes_without_segment_get_a_default():
    scenario = {
        "requires": {"provider_class": "vm"},
        "nodes": [{"name": "solo", "role": "victim", "image": "ubuntu"}],
    }
    v = LibvirtProvider.compile_vars(scenario, "x")
    assert [s["name"] for s in v["segments"]] == ["default"]
    assert v["nodes"][0]["segments"] == ["default"]


def test_write_vars_emits_tfvars_file(tmp_path):
    extra = LibvirtProvider()._write_vars(tmp_path, SCENARIO, "arena-x", None)
    assert extra == []
    data = json.loads((tmp_path / "arena.auto.tfvars.json").read_text())
    assert data["arena_id"] == "arena-x"
    assert {n["name"] for n in data["nodes"]} == {"dc", "jump", "custom"}


# --- guards / outputs -------------------------------------------------------


def test_rejects_container_only_scenarios():
    result = LibvirtProvider().deploy({"requires": {"provider_class": "container"}}, "x")
    assert result["success"] is False
    assert "vm" in result["error"]


def test_post_process_flattens_per_node_maps():
    raw = {
        "provider": "libvirt",
        "node_private_ips": {"dc": "10.30.0.5", "jump": "", "custom": "10.30.1.7"},
        "node_instance_ids": {"dc": "uuid-1", "jump": "uuid-2", "custom": "uuid-3"},
        "node_roles": {"dc": "victim", "jump": "attacker", "custom": "victim"},
    }
    flat = LibvirtProvider()._post_process_outputs(raw)

    assert flat["provider"] == "libvirt"
    assert flat["node_dc_name"] == "nv-dc"        # WebUI node discovery key
    assert flat["node_dc_private_ip"] == "10.30.0.5"
    assert flat["node_dc_domain_id"] == "uuid-1"
    # jump has no lease yet → no private_ip key, but still a domain + name
    assert "node_jump_private_ip" not in flat
    assert flat["node_jump_domain_id"] == "uuid-2"
    # legacy role keys resolve to the FIRST node of each canonical role
    assert flat["victim_vm_private_ip"] == "10.30.0.5"   # dc, not custom
    assert flat["attack_vm_name"] == "nv-jump"


@pytest.mark.parametrize("provider_class", ["vm", "any"])
def test_supports_vm_and_any(provider_class):
    assert LibvirtProvider._supports({"requires": {"provider_class": provider_class}})
