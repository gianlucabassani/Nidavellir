"""Pure research-session target identity and infrastructure preflight logic."""
from __future__ import annotations

from datetime import datetime, timezone

import setup_phase

TARGET_MANIFEST_SCHEMA = "nidavellir/target/v1"
PREFLIGHT_EVENT = "session_preflight"
AUTHORIZATION_BASES = (
    "public_oss",
    "owned",
    "authorized_assessment",
)


def git_target_manifest(
    *,
    repo: str,
    requested_ref: str | None,
    resolved_commit: str,
    authorization_basis: str,
    authorization_confirmed: bool,
    scope_note: str | None,
    actor: str,
) -> dict:
    """Build the immutable, auditable identity for one Git target."""
    return {
        "schema": TARGET_MANIFEST_SCHEMA,
        "kind": "git",
        "source": repo,
        "requested_ref": requested_ref,
        "resolved_ref": resolved_commit,
        "identity": {
            "algorithm": "git-oid",
            "digest": resolved_commit,
        },
        "authorization": {
            "confirmed": authorization_confirmed,
            "basis": authorization_basis,
            "scope_note": scope_note,
            "confirmed_by": actor,
        },
        "reset": {
            "strategy": "destroy_redeploy",
            "immutable_source": True,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def oci_target_manifest(
    *,
    requested_image: str,
    runtime_ref: str,
    resolved_digest: str,
    authorization_basis: str,
    authorization_confirmed: bool,
    scope_note: str | None,
    actor: str,
    platform: str = "linux/amd64",
) -> dict:
    """Build the immutable, auditable identity for one OCI image target."""
    return {
        "schema": TARGET_MANIFEST_SCHEMA,
        "kind": "oci",
        "source": requested_image,
        "requested_ref": requested_image,
        "resolved_ref": resolved_digest,
        "runtime_ref": runtime_ref,
        "platform": platform,
        "identity": {
            "algorithm": "sha256",
            "digest": resolved_digest,
            "platform": platform,
        },
        "authorization": {
            "confirmed": authorization_confirmed,
            "basis": authorization_basis,
            "scope_note": scope_note,
            "confirmed_by": actor,
        },
        "reset": {
            "strategy": "destroy_redeploy",
            "immutable_source": True,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def source_bundle_target_manifest(
    *,
    artifact: dict,
    authorization_basis: str,
    authorization_confirmed: bool,
    scope_note: str | None,
    actor: str,
) -> dict:
    """Build immutable provenance for one content-addressed source bundle."""
    return {
        "schema": TARGET_MANIFEST_SCHEMA,
        "kind": "source_bundle",
        "source": artifact["filename"],
        "requested_ref": artifact["filename"],
        "resolved_ref": artifact["digest"],
        "identity": {
            "algorithm": "sha256",
            "digest": artifact["digest"],
            "payload_digest": artifact["payload_digest"],
        },
        "artifact": {
            key: artifact[key]
            for key in (
                "schema",
                "filename",
                "upload_bytes",
                "payload_digest",
                "payload_bytes",
                "expanded_bytes",
                "file_count",
                "member_count",
                "stripped_root",
            )
        },
        "authorization": {
            "confirmed": authorization_confirmed,
            "basis": authorization_basis,
            "scope_note": scope_note,
            "confirmed_by": actor,
        },
        "reset": {
            "strategy": "destroy_redeploy",
            "immutable_source": True,
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def evaluate_preflight(
    outputs: dict,
    target_manifest: dict,
    *,
    include_attacker: bool,
    auto_build: bool,
) -> dict:
    """Evaluate whether deployed infrastructure is valid for a research session.

    This is intentionally infrastructure readiness, not a claim that setup has
    produced a healthy application. Setup/service readiness is a later phase.
    """
    outputs = outputs or {}
    nodes, footholds = setup_phase.derive_nodes_footholds(outputs)
    victim_nodes = sorted(nodes - footholds)
    unhealthy = set(outputs.get("unhealthy_nodes") or [])
    explicit_bad_state = {
        node
        for node in victim_nodes
        if (
            (state := outputs.get(f"node_{node}_state")) is not None
            and str(state).lower() not in {"running", "healthy"}
        )
    }
    unavailable_targets = unhealthy | explicit_bad_state
    identity = (target_manifest.get("identity") or {}).get("digest")
    authorization = target_manifest.get("authorization") or {}
    workspace_present = any(
        key.endswith(("_sut_source", "_whitebox_source"))
        for key in outputs
    )
    workspace_required = (
        target_manifest.get("kind") in {"git", "source_bundle"}
        and (not auto_build or include_attacker)
    )

    checks = [
        {
            "id": "immutable_target",
            "required": True,
            "ok": bool(identity and target_manifest.get("resolved_ref") == identity),
            "detail": f"pinned Git object {identity}" if identity else "missing target identity",
        },
        {
            "id": "authorization",
            "required": True,
            "ok": authorization.get("confirmed") is True,
            "detail": (
                f"operator confirmed {authorization.get('basis')}"
                if authorization.get("confirmed") else "authorization not confirmed"
            ),
        },
        {
            "id": "target_node",
            "required": True,
            "ok": bool(victim_nodes) and not unavailable_targets.intersection(victim_nodes),
            "detail": (
                f"target nodes running: {', '.join(victim_nodes)}"
                if victim_nodes and not unavailable_targets.intersection(victim_nodes)
                else "target node missing or unhealthy"
            ),
        },
        {
            "id": "foothold",
            "required": include_attacker,
            "ok": bool(footholds) if include_attacker else True,
            "detail": (
                f"foothold ready: {', '.join(sorted(footholds))}"
                if footholds else
                ("not requested" if not include_attacker else "requested foothold missing")
            ),
        },
        {
            "id": "workspace",
            "required": workspace_required,
            "ok": workspace_present if workspace_required else True,
            "detail": (
                "provider workspace discovered"
                if workspace_present else
                ("not required for this packaged target"
                 if not workspace_required else "no provider workspace discovered")
            ),
        },
        {
            "id": "reset_contract",
            "required": True,
            "ok": bool(
                (target_manifest.get("reset") or {}).get("immutable_source")
                and (target_manifest.get("reset") or {}).get("strategy")
            ),
            "detail": "reset by destroy + redeploy from pinned identity",
        },
    ]
    failed = [check["id"] for check in checks if check["required"] and not check["ok"]]
    return {
        "status": "passed" if not failed else "failed",
        "phase": "infrastructure",
        "ready": not failed,
        "next": (
            "service_setup" if not auto_build and not failed
            else ("engagement" if not failed else "repair_infrastructure")
        ),
        "target": target_manifest,
        "checks": checks,
        "failed_checks": failed,
        "reset_contract": target_manifest.get("reset"),
    }
