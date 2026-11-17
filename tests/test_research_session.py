"""Immutable research target manifests and infrastructure preflight."""
import research_session


def _manifest(confirmed=True):
    return research_session.git_target_manifest(
        repo="https://github.com/org/project",
        requested_ref="main",
        resolved_commit="a" * 40,
        authorization_basis="public_oss",
        authorization_confirmed=confirmed,
        scope_note="public security research",
        actor="operator",
    )


def test_git_manifest_separates_requested_ref_from_immutable_identity():
    manifest = _manifest()
    assert manifest["requested_ref"] == "main"
    assert manifest["resolved_ref"] == "a" * 40
    assert manifest["identity"] == {
        "algorithm": "git-oid", "digest": "a" * 40,
    }
    assert manifest["reset"]["strategy"] == "destroy_redeploy"


def test_preflight_passes_for_pinned_running_workspace():
    outputs = {
        "node_sut_name": "nv-sut",
        "node_sut_state": "running",
        "node_sut_sut_source": "/opt/sut",
        "node_kali_name": "nv-kali",
        "node_kali_state": "running",
        "node_kali_ssh_command": "docker exec nv-kali sh",
    }
    result = research_session.evaluate_preflight(
        outputs, _manifest(), include_attacker=True, auto_build=False
    )
    assert result["ready"] is True and result["status"] == "passed"
    assert result["next"] == "service_setup"
    assert result["failed_checks"] == []


def test_preflight_fails_closed_on_authorization_and_unhealthy_target():
    outputs = {
        "node_sut_name": "nv-sut",
        "node_sut_state": "exited",
        "node_sut_sut_source": "/opt/sut",
        "unhealthy_nodes": ["sut"],
    }
    result = research_session.evaluate_preflight(
        outputs, _manifest(confirmed=False), include_attacker=True, auto_build=False
    )
    assert result["ready"] is False and result["status"] == "failed"
    assert {"authorization", "target_node", "foothold"} <= set(result["failed_checks"])


def test_packaged_target_without_foothold_does_not_require_workspace():
    outputs = {"node_sut_name": "nv-sut", "node_sut_state": "running"}
    result = research_session.evaluate_preflight(
        outputs, _manifest(), include_attacker=False, auto_build=True
    )
    workspace = next(c for c in result["checks"] if c["id"] == "workspace")
    assert workspace["required"] is False and workspace["ok"] is True
    assert result["ready"] is True


def test_preflight_rejects_explicit_non_running_target_state():
    result = research_session.evaluate_preflight(
        {
            "node_sut_name": "nv-sut",
            "node_sut_state": "exited",
            "node_sut_sut_source": "/opt/sut",
        },
        _manifest(),
        include_attacker=False,
        auto_build=False,
    )

    assert result["ready"] is False
    assert "target_node" in result["failed_checks"]


def test_oci_target_with_foothold_does_not_require_source_workspace():
    manifest = research_session.oci_target_manifest(
        requested_image="nginx:1.27",
        runtime_ref="docker.io/library/nginx@sha256:" + "b" * 64,
        resolved_digest="sha256:" + "b" * 64,
        authorization_basis="public_oss",
        authorization_confirmed=True,
        scope_note=None,
        actor="operator",
    )
    result = research_session.evaluate_preflight(
        {
            "node_sut_name": "nv-sut",
            "node_sut_state": "running",
            "node_kali_name": "nv-kali",
            "node_kali_state": "running",
            "node_kali_ssh_command": "docker exec nv-kali sh",
        },
        manifest,
        include_attacker=True,
        auto_build=True,
    )

    workspace = next(c for c in result["checks"] if c["id"] == "workspace")
    assert workspace["required"] is False
    assert result["ready"] is True


def test_source_bundle_requires_materialized_workspace_before_setup():
    manifest = research_session.source_bundle_target_manifest(
        artifact={
            "schema": "cyberguard.source-bundle/v1",
            "filename": "product.tar.gz",
            "digest": "a" * 64,
            "upload_bytes": 512,
            "payload_digest": "b" * 64,
            "payload_bytes": 2048,
            "expanded_bytes": 1024,
            "file_count": 4,
            "member_count": 5,
            "stripped_root": "product",
        },
        authorization_basis="customer_authorized",
        authorization_confirmed=True,
        scope_note="Customer-provided source snapshot",
        actor="operator",
    )
    outputs = {
        "node_sut_name": "nv-sut",
        "node_sut_state": "running",
        "node_sut_sut_source": "/opt/sut",
    }

    passed = research_session.evaluate_preflight(
        outputs, manifest, include_attacker=False, auto_build=False
    )
    assert passed["ready"] is True
    assert passed["next"] == "service_setup"

    missing = research_session.evaluate_preflight(
        {key: value for key, value in outputs.items() if key != "node_sut_sut_source"},
        manifest,
        include_attacker=False,
        auto_build=False,
    )
    workspace = next(c for c in missing["checks"] if c["id"] == "workspace")
    assert workspace["required"] is True
    assert workspace["ok"] is False
    assert "workspace" in missing["failed_checks"]
