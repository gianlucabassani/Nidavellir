"""Trusted fact adapters for versioned configuration profiles."""
from __future__ import annotations

from copy import deepcopy

import configuration_lineage as lineage


def typed_value(value, declaration):
    """Parse explicit configuration types without truthiness or shell evaluation."""
    kind = declaration["type"]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false", "1", "0"}:
            return value.lower() in {"true", "1"}
    elif kind == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lstrip("-").isdigit() and len(value) < 32:
            return int(value)
    elif kind in {"string", "enum"} and isinstance(value, str) and len(value) <= 4096:
        if kind != "enum" or value in declaration["enum"]:
            return value
    raise lineage.ConfigurationLineageError("configuration value does not match declared type")


def target_identity(recipe):
    target = recipe.get("target") or {}
    identity = target.get("identity") or {}
    return {
        "kind": target.get("kind", "recipe"),
        "digest": identity.get("digest") or recipe["equivalence_digest"],
        "lineage": target.get("source") or recipe["scenario_name"],
    }


def recipe_facts(recipe):
    """Extract only profile-declared scenario and immutable build inputs."""
    profile = recipe.get("configuration_profile")
    if not profile:
        return []
    nodes = {node["name"]: node for node in recipe.get("nodes") or []}
    facts = []
    for declaration in profile["facts"]:
        for source in declaration["sources"]:
            node = nodes.get(source.get("node")) or {}
            if source["kind"] == "scenario_env":
                values = node.get("environment") or {}
            elif source["kind"] == "build":
                values = {key: node.get(key) for key in ("image", "platform", "package")}
            else:
                continue
            raw = values.get(source["selector"])
            if raw is None:
                continue
            try:
                value = typed_value(raw, declaration)
            except lineage.ConfigurationLineageError:
                continue
            facts.append({"key": declaration["key"], "value": value,
                          "source_kind": source["kind"], "complete": True,
                          "source_ref": {**source, "recipe_digest": recipe["recipe_digest"]}})
    return facts


def deployment_snapshot(arena_id, recipe):
    profile = recipe.get("configuration_profile")
    if not profile:
        return None
    identity = target_identity(recipe)
    return lineage.capture_snapshot(arena_id=arena_id, target_identity=identity,
        profile=profile, facts=recipe_facts(recipe), stage="deployment",
        lineage_id=identity["lineage"])


def runtime_selectors(profile):
    result = []
    for declaration in profile["facts"]:
        for source in declaration["sources"]:
            if source["kind"] in {"runtime_env", "runtime_readback", "build", "setup"}:
                result.append({"kind": "runtime_readback" if source["kind"] == "setup" else source["kind"],
                    "key": declaration["key"], "node": source.get("node"), "selector": source["selector"]})
    return [dict(item) for item in {tuple(sorted(item.items())): item for item in result}.values()]


def runtime_snapshot(arena_id, recipe, observation, *, stage="runtime", setup_events=()):
    profile = recipe["configuration_profile"]
    declarations = {item["key"]: item for item in profile["facts"]}
    facts = recipe_facts(recipe)
    finished = next((event.get("payload", {}).get("session_id") for event in setup_events
                     if event.get("type") == "setup_finished"), None)
    for raw in observation.get("facts") or []:
        declaration = declarations.get(raw.get("key"))
        if declaration is None:
            continue
        try:
            value = typed_value(raw["value"], declaration)
        except (KeyError, lineage.ConfigurationLineageError):
            continue
        kinds = {source["kind"] for source in declaration["sources"]}
        if raw["source_kind"] in kinds:
            facts.append({**raw, "value": value})
        if raw["source_kind"] == "runtime_readback" and raw.get("complete"):
            for source in declaration["sources"]:
                if source["kind"] != "setup" or not finished:
                    continue
                event = next((event for event in setup_events
                    if event.get("type") == "setup_step"
                    and event.get("payload", {}).get("session_id") == finished
                    and event.get("payload", {}).get("configuration_step") == source.get("step")
                    and event.get("payload", {}).get("node") == source.get("node")
                    and event.get("payload", {}).get("ok") is True
                    and event.get("payload", {}).get("exit_code") == 0
                    and event.get("payload", {}).get("via") in {"operator", "hitl"}), None)
                if event and raw["source_ref"].get("node") == source.get("node") and raw["source_ref"].get("selector") == source["selector"]:
                    facts.append({"key": declaration["key"], "value": value, "source_kind": "setup", "complete": True,
                        "source_ref": {**source, "setup_event_id": event["id"], "session_id": finished}})
    identity = target_identity(recipe)
    return lineage.capture_snapshot(arena_id=arena_id, target_identity=identity,
        profile=profile, facts=facts, stage=stage, lineage_id=identity["lineage"])


def controlled_transition(before, after):
    """Prove the bounded recipe transition changes only declared environment keys.

    This establishes adjacency in an operator-selected configuration experiment;
    it makes no claim about the first upstream Git commit or a production date.
    """
    if not before or not after or before.get("configuration_profile_digest") != after.get("configuration_profile_digest"):
        return False
    profile = before.get("configuration_profile")
    if not profile:
        return False
    allowed = {(source.get("node"), source["selector"])
               for fact in profile["facts"] for source in fact["sources"]
               if source["kind"] == "scenario_env"}
    if not allowed:
        return False
    projections = []
    for recipe in (before, after):
        projection = deepcopy(recipe["equivalence_projection"])
        for nodes in (projection.get("nodes", []), projection.get("scenario", {}).get("nodes", [])):
            for node in nodes:
                for key in list(node.get("environment") or {}):
                    if (node.get("name"), key) in allowed:
                        node["environment"].pop(key)
        projections.append(projection)
    return projections[0] == projections[1]
