"""Versioned, deterministic lifecycle recipes and reset observations (NV-02)."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

from scenario_spec import normalized_nodes

RECIPE_SCHEMA = "nidavellir/lifecycle-recipe/v1"
OBSERVATION_SCHEMA = "nidavellir/lifecycle-observation/v1"


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _image_is_pinned(image: str | None) -> bool:
    return bool(image and ("@sha256:" in image or image.startswith("sha256:")))


def _node_recipe(node: dict) -> dict:
    service = deepcopy(node.get("service") or {})
    image = service.get("image") or node.get("image")
    source = service.get("source") or {}
    return {
        "name": node.get("name"),
        "role": node.get("role"),
        "image": image,
        "image_pinned": _image_is_pinned(image),
        "platform": node.get("platform"),
        "source": {
            key: source.get(key)
            for key in ("repo", "ref", "dockerfile", "context")
            if source.get(key) is not None
        },
        "package": service.get("package"),
        "ports": sorted(node.get("ports") or []),
        "forward_services": sorted(node.get("forward_services") or [],
                                   key=lambda service: service["id"]),
        "segments": sorted(node.get("segments") or []),
        "environment": dict(sorted((node.get("environment") or {}).items())),
        "command": node.get("command"),
        "entrypoint": bool(node.get("entrypoint")),
    }


def build_recipe(
    *,
    scenario: dict,
    scenario_name: str,
    requested_provider: str | None,
    effective_provider: str,
    target_manifest: dict | None = None,
    expires_at: str | None = None,
    readiness: dict | None = None,
    seed: dict | None = None,
    setup: dict | None = None,
) -> dict:
    """Freeze the validated inputs used by a deployment.

    ``scenario`` is the resolved inline spec. Reset never reloads a mutable named
    scenario or resolves a moving source ref.
    """
    nodes = [_node_recipe(node) for node in normalized_nodes(scenario)]
    target = deepcopy(target_manifest) if target_manifest else None
    manual_setup = bool(setup and setup.get("open_setup", True))
    target_immutable = bool(
        target
        and (target.get("reset") or {}).get("immutable_source")
        and (target.get("identity") or {}).get("digest")
    )
    all_packaged_pinned = bool(nodes) and all(
        n["image_pinned"] for n in nodes if n.get("role") != "monitor"
    )
    has_build = any(n["source"] or n["package"] for n in nodes)

    if has_build:
        build = {"status": "unverified", "reason": "network_build_dependencies_not_locked"}
    elif target and target.get("kind") == "oci" and target_immutable:
        build = {"status": "verified", "reason": "digest_pinned_oci_artifact"}
    elif all_packaged_pinned:
        build = {"status": "verified", "reason": "all_runtime_images_digest_pinned"}
    else:
        build = {"status": "unverified", "reason": "one_or_more_runtime_images_are_mutable"}

    eligible = (
        effective_provider == "docker-local"
        and not manual_setup
        and (target_immutable or all_packaged_pinned)
        and bool(readiness)
    )
    reset = {
        "status": "eligible" if eligible else "unsupported",
        "reason": (
            "immutable_inputs_and_bounded_readiness"
            if eligible
            else (
                "manual_setup_has_no_replayable_baseline" if manual_setup
                else "missing_immutable_inputs_or_readiness_policy"
            )
        ),
    }
    projection = {
        "scenario": deepcopy(scenario),
        "target": target,
        "provider": effective_provider,
        "nodes": nodes,
        "seed": deepcopy(seed or {"strategy": "image_baked"}),
        "readiness": deepcopy(readiness),
    }
    recipe = {
        "schema": RECIPE_SCHEMA,
        "scenario_name": scenario_name,
        "scenario": deepcopy(scenario),
        "requested_provider": requested_provider,
        "effective_provider": effective_provider,
        "target": target,
        "nodes": nodes,
        "build_reproducibility": build,
        "runtime_reset": reset,
        "observed_equivalence": {"status": "pending", "reason": "not_observed"},
        "seed": deepcopy(seed or {"strategy": "image_baked"}),
        "readiness": deepcopy(readiness),
        "setup": deepcopy(setup or {}),
        "expires_at": expires_at,
        "equivalence_projection": projection,
        "equivalence_digest": digest(projection),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    recipe["recipe_digest"] = digest({k: v for k, v in recipe.items() if k != "captured_at"})
    return recipe


def public_recipe(recipe: dict) -> dict:
    """Return the operator-safe projection; hidden scenario truth is excluded."""
    target = deepcopy(recipe.get("target")) if recipe.get("target") else None
    if target:
        authorization = target.get("authorization") or {}
        target["authorization"] = {
            "confirmed": bool(authorization.get("confirmed")),
            "basis": authorization.get("basis"),
        }
        target.pop("artifact", None)
    nodes = []
    for node in recipe.get("nodes") or []:
        nodes.append({
            key: deepcopy(node.get(key))
            for key in (
                "name", "role", "image", "image_pinned", "source", "package",
                "platform", "ports", "segments", "entrypoint",
            )
        } | {
            "environment_keys": sorted((node.get("environment") or {}).keys()),
            "command_override": bool(node.get("command")),
        })
    readiness = deepcopy(recipe.get("readiness"))
    if readiness and "expected_state" in readiness:
        readiness.pop("expected_state")
    public = {
        key: deepcopy(recipe.get(key))
        for key in (
            "schema", "scenario_name", "requested_provider", "effective_provider",
            "build_reproducibility", "runtime_reset", "observed_equivalence", "expires_at",
            "equivalence_digest", "recipe_digest", "captured_at",
        )
    }
    public.update({
        "target": target,
        "nodes": nodes,
        "seed_recorded": recipe.get("seed") is not None,
        "readiness": readiness,
    })
    return public


def observation(*, recipe: dict, provider_observation: dict, readiness_result: dict) -> dict:
    state = {
        "recipe_equivalence_digest": recipe["equivalence_digest"],
        "runtime": provider_observation,
        "readiness": {
            "status": readiness_result.get("status"),
            "state_digest": readiness_result.get("state_digest"),
        },
    }
    return {
        "schema": OBSERVATION_SCHEMA,
        "status": "ready" if readiness_result.get("ready") else "unready",
        "state": state,
        "observed_state_digest": digest(state),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def equivalent(first: dict, second: dict) -> bool:
    return bool(
        first.get("status") == second.get("status") == "ready"
        and first.get("observed_state_digest") == second.get("observed_state_digest")
    )
