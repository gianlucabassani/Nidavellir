"""Pure effective-configuration lineage rules (RESEARCH-W1)."""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import PurePosixPath

import crypto
from lifecycle_manifest import canonical_json, digest

PROFILE_SCHEMA = "nidavellir/configuration-profile/v1"
SNAPSHOT_SCHEMA = "nidavellir/configuration-snapshot/v1"
DELTA_SCHEMA = "nidavellir/configuration-delta/v1"
INTRODUCTION_SCHEMA = "nidavellir/configuration-introduction/v1"

_PRECEDENCE = ("source", "build", "scenario", "deployment", "setup", "runtime")
_STAGE_LAYERS = {
    "deployment": frozenset(_PRECEDENCE[:4]),
    "post_setup": frozenset(_PRECEDENCE[:5]),
    "runtime": frozenset(_PRECEDENCE),
    "historical_candidate": frozenset({"source"}),
}
_SOURCE_CLASS = {
    "source_file": "source",
    "build": "build",
    "scenario_env": "scenario",
    "deployment": "deployment",
    "setup": "setup",
    "runtime_env": "runtime",
}
_TYPE_NAMES = frozenset({"bool", "int", "string", "enum"})
_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_KEY_RE = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
_TAG_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


class ConfigurationLineageError(ValueError):
    """A profile, fact, snapshot or analysis request is invalid."""


def _require_fields(value: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigurationLineageError(
            f"{label} contains unknown field {unknown[0]!r}"
        )


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ConfigurationLineageError("source path must be a bounded relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ConfigurationLineageError("source path must be normalized and relative")
    return path.as_posix()


def _normalize_source(source: dict) -> dict:
    if not isinstance(source, dict):
        raise ConfigurationLineageError("profile source must be an object")
    kind = source.get("kind")
    if kind not in _SOURCE_CLASS:
        raise ConfigurationLineageError(f"unsupported source kind {kind!r}")
    common = {"kind", "selector"}
    if kind == "source_file":
        allowed = common | {"path", "parser"}
        _require_fields(source, allowed, "profile source")
        parser = source.get("parser")
        if parser not in {"dotenv", "json_pointer"}:
            raise ConfigurationLineageError("source parser must be dotenv or json_pointer")
        path = _relative_path(source.get("path"))
        selector = source.get("selector")
        if not isinstance(selector, str) or not selector or len(selector) > 128:
            raise ConfigurationLineageError("source selector must be a bounded string")
        if parser == "json_pointer" and not selector.startswith("/"):
            raise ConfigurationLineageError("json_pointer selector must start with /")
        return {"kind": kind, "parser": parser, "path": path, "selector": selector}
    allowed = common | {"node", "step"}
    _require_fields(source, allowed, "profile source")
    selector = source.get("selector")
    if not isinstance(selector, str) or not selector or len(selector) > 128:
        raise ConfigurationLineageError("source selector must be a bounded string")
    result = {"kind": kind, "selector": selector}
    for field in ("node", "step"):
        if field in source:
            item = source[field]
            if not isinstance(item, str) or not item or len(item) > 64:
                raise ConfigurationLineageError(f"source {field} must be a bounded string")
            result[field] = item
    return result


def validate_profile(profile: dict) -> dict:
    """Validate and canonicalize one declarative configuration profile."""
    if not isinstance(profile, dict):
        raise ConfigurationLineageError("configuration profile must be an object")
    _require_fields(
        profile, {"schema", "id", "version", "precedence", "facts", "digest"},
        "configuration profile",
    )
    if profile.get("schema") != PROFILE_SCHEMA:
        raise ConfigurationLineageError(f"profile schema must be {PROFILE_SCHEMA}")
    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not _ID_RE.fullmatch(profile_id):
        raise ConfigurationLineageError("profile id is invalid")
    version = profile.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ConfigurationLineageError("profile version must be a positive integer")
    if tuple(profile.get("precedence") or ()) != _PRECEDENCE:
        raise ConfigurationLineageError("profile precedence is unsupported")
    raw_facts = profile.get("facts")
    if not isinstance(raw_facts, list) or not raw_facts or len(raw_facts) > 128:
        raise ConfigurationLineageError("profile facts must contain 1 to 128 entries")
    facts = []
    keys = set()
    for raw in raw_facts:
        if not isinstance(raw, dict):
            raise ConfigurationLineageError("profile fact must be an object")
        _require_fields(
            raw,
            {"key", "type", "sensitive", "required", "security_tags", "sources", "enum"},
            "profile fact",
        )
        key = raw.get("key")
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key) or key in keys:
            raise ConfigurationLineageError("profile fact key is invalid or duplicated")
        keys.add(key)
        type_name = raw.get("type")
        if type_name not in _TYPE_NAMES:
            raise ConfigurationLineageError("profile fact type is unsupported")
        enum_values = raw.get("enum")
        if type_name == "enum":
            if (
                not isinstance(enum_values, list)
                or not enum_values
                or len(enum_values) > 32
                or any(not isinstance(item, str) or len(item) > 128 for item in enum_values)
            ):
                raise ConfigurationLineageError("enum facts require bounded string values")
            enum_values = sorted(set(enum_values))
        elif enum_values is not None:
            raise ConfigurationLineageError("enum values are valid only for enum facts")
        tags = raw.get("security_tags") or []
        if (
            not isinstance(tags, list)
            or len(tags) > 16
            or any(not isinstance(tag, str) or not _TAG_RE.fullmatch(tag) for tag in tags)
        ):
            raise ConfigurationLineageError("security tags are invalid")
        sources = raw.get("sources")
        if not isinstance(sources, list) or not sources or len(sources) > 16:
            raise ConfigurationLineageError("profile fact sources are invalid")
        normalized = {
            "key": key,
            "type": type_name,
            "sensitive": bool(raw.get("sensitive", False)),
            "required": bool(raw.get("required", False)),
            "security_tags": sorted(set(tags)),
            "sources": sorted(
                (_normalize_source(source) for source in sources),
                key=lambda item: canonical_json(item),
            ),
        }
        if enum_values is not None:
            normalized["enum"] = enum_values
        facts.append(normalized)
    normalized_profile = {
        "schema": PROFILE_SCHEMA,
        "id": profile_id,
        "version": version,
        "precedence": list(_PRECEDENCE),
        "facts": sorted(facts, key=lambda item: item["key"]),
    }
    if len(canonical_json(normalized_profile)) > 65536:
        raise ConfigurationLineageError("configuration profile exceeds 64 KiB")
    normalized_profile["digest"] = digest(normalized_profile)
    supplied_digest = profile.get("digest")
    if supplied_digest is not None and supplied_digest != normalized_profile["digest"]:
        raise ConfigurationLineageError("configuration profile digest mismatch")
    return normalized_profile


def _check_type(value: object, profile_fact: dict) -> None:
    type_name = profile_fact["type"]
    valid = (
        (type_name == "bool" and isinstance(value, bool))
        or (type_name == "int" and isinstance(value, int) and not isinstance(value, bool))
        or (type_name in {"string", "enum"} and isinstance(value, str))
    )
    if not valid:
        raise ConfigurationLineageError(
            f"fact {profile_fact['key']!r} does not match type {type_name}"
        )
    if type_name == "enum" and value not in profile_fact["enum"]:
        raise ConfigurationLineageError(f"fact {profile_fact['key']!r} is outside its enum")


def _fact_value_token(fact: dict) -> bytes:
    if fact["value_state"] == "plain":
        return canonical_json(fact["value"])
    if fact["value_state"] == "withheld":
        return fact["value_hmac"].encode()
    return b"unknown"


def capture_snapshot(
    *,
    arena_id: str,
    target_identity: dict,
    profile: dict,
    facts: list[dict],
    stage: str,
    lineage_id: str,
    captured_at: str | None = None,
) -> dict:
    """Normalize facts and freeze one immutable effective-configuration snapshot."""
    if stage not in _STAGE_LAYERS:
        raise ConfigurationLineageError("snapshot stage is unsupported")
    if not isinstance(arena_id, str) or not arena_id or len(arena_id) > 128:
        raise ConfigurationLineageError("arena id is invalid")
    if not isinstance(lineage_id, str) or not lineage_id or len(lineage_id) > 256:
        raise ConfigurationLineageError("lineage id is invalid")
    normalized_profile = validate_profile(profile)
    by_key = {item["key"]: item for item in normalized_profile["facts"]}
    allowed_sources = {
        key: {source["kind"] for source in item["sources"]}
        for key, item in by_key.items()
    }
    normalized_facts = []
    for raw in facts:
        if not isinstance(raw, dict):
            raise ConfigurationLineageError("configuration fact must be an object")
        _require_fields(
            raw, {"key", "value", "source_kind", "source_ref", "complete"},
            "configuration fact",
        )
        key = raw.get("key")
        profile_fact = by_key.get(key)
        source_kind = raw.get("source_kind")
        if profile_fact is None or source_kind not in allowed_sources.get(key, set()):
            raise ConfigurationLineageError("fact is not declared by the profile")
        value = raw.get("value")
        _check_type(value, profile_fact)
        source_ref = raw.get("source_ref") or {}
        if not isinstance(source_ref, dict) or len(source_ref) > 16:
            raise ConfigurationLineageError("fact source reference is invalid")
        if any(
            not isinstance(k, str)
            or not isinstance(v, (str, int, bool, type(None)))
            or len(str(v)) > 256
            for k, v in source_ref.items()
        ):
            raise ConfigurationLineageError("fact source reference is invalid")
        item = {
            "key": key,
            "source_kind": source_kind,
            "source_class": _SOURCE_CLASS[source_kind],
            "source_ref": dict(sorted(source_ref.items())),
            "precedence": _PRECEDENCE.index(_SOURCE_CLASS[source_kind]),
            "security_tags": deepcopy(profile_fact["security_tags"]),
            "complete": bool(raw.get("complete", False)),
            "value_state": "plain",
            "value": deepcopy(value),
        }
        if profile_fact["sensitive"]:
            try:
                item["value_hmac"] = crypto.lineage_secret_hmac(
                    value, lineage_id=lineage_id
                )
            except RuntimeError as exc:
                raise ConfigurationLineageError(str(exc)) from exc
            item["value_state"] = "withheld"
            item.pop("value")
        normalized_facts.append(item)
    normalized_facts.sort(
        key=lambda item: (item["key"], item["precedence"], canonical_json(item))
    )
    effective = []
    conflicts = []
    for key, profile_fact in by_key.items():
        candidates = [
            item for item in normalized_facts
            if item["key"] == key
            and item["complete"]
            and item["source_class"] in _STAGE_LAYERS[stage]
        ]
        if not candidates:
            continue
        top = max(item["precedence"] for item in candidates)
        winners = [item for item in candidates if item["precedence"] == top]
        values = {_fact_value_token(item) for item in winners}
        if len(values) > 1:
            conflicts.append({
                "key": key,
                "precedence": top,
                "source_refs": [deepcopy(item["source_ref"]) for item in winners],
            })
            continue
        effective.append(deepcopy(sorted(winners, key=canonical_json)[0]))
    declared_layers = {
        _SOURCE_CLASS[source["kind"]]
        for item in normalized_profile["facts"] if item["required"]
        for source in item["sources"]
        if _SOURCE_CLASS[source["kind"]] in _STAGE_LAYERS[stage]
    }
    observed_layers = {
        item["source_class"] for item in normalized_facts
        if item["complete"] and item["source_class"] in _STAGE_LAYERS[stage]
    }
    missing_layers = sorted(declared_layers - observed_layers)
    missing_keys = sorted(
        key for key, item in by_key.items()
        if item["required"] and key not in {value["key"] for value in effective}
    )
    completeness = {
        "status": "complete" if not missing_layers and not missing_keys and not conflicts
        else "partial",
        "missing_layers": missing_layers,
    }
    if missing_keys:
        completeness["missing_keys"] = missing_keys
    projection = {
        "schema": SNAPSHOT_SCHEMA,
        "arena_id": arena_id,
        "lineage_id": lineage_id,
        "target_identity": deepcopy(target_identity),
        "profile": {
            "id": normalized_profile["id"],
            "version": normalized_profile["version"],
            "digest": normalized_profile["digest"],
        },
        "stage": stage,
        "facts": normalized_facts,
        "effective": sorted(effective, key=lambda item: item["key"]),
        "conflicts": sorted(conflicts, key=lambda item: item["key"]),
        "completeness": completeness,
    }
    snapshot_digest = digest(projection)
    return {
        **projection,
        "snapshot_id": snapshot_digest.removeprefix("sha256:")[:12],
        "snapshot_digest": snapshot_digest,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
    }


def public_snapshot(snapshot: dict) -> dict:
    """Return the operator-safe snapshot projection."""
    projection = deepcopy(snapshot)
    for field in ("facts", "effective"):
        for fact in projection.get(field) or []:
            fact.pop("value_hmac", None)
            if fact.get("value_state") == "withheld":
                fact.pop("value", None)
    return projection


def agent_snapshot(snapshot: dict) -> dict:
    """Return the participant-safe snapshot projection."""
    return public_snapshot(snapshot)


def _safe_fact(fact: dict | None) -> dict | None:
    if fact is None:
        return None
    result = deepcopy(fact)
    result.pop("value_hmac", None)
    if result.get("value_state") == "withheld":
        result.pop("value", None)
    return result


def _effective_map(snapshot: dict) -> dict[str, dict]:
    return {item["key"]: item for item in snapshot.get("effective") or []}


def compare_snapshots(before: dict, after: dict) -> dict:
    """Compare effective facts without exposing withheld comparison tokens."""
    if before.get("schema") != SNAPSHOT_SCHEMA or after.get("schema") != SNAPSHOT_SCHEMA:
        raise ConfigurationLineageError("comparison requires configuration snapshots")
    if before.get("lineage_id") != after.get("lineage_id"):
        raise ConfigurationLineageError("snapshots belong to different lineages")
    if (before.get("profile") or {}).get("digest") != (after.get("profile") or {}).get(
        "digest"
    ):
        raise ConfigurationLineageError("snapshots use different configuration profiles")
    before_map = _effective_map(before)
    after_map = _effective_map(after)
    before_conflicts = {item["key"] for item in before.get("conflicts") or []}
    after_conflicts = {item["key"] for item in after.get("conflicts") or []}
    changes = []
    candidate_keys = []
    for key in sorted(set(before_map) | set(after_map) | before_conflicts | after_conflicts):
        left = before_map.get(key)
        right = after_map.get(key)
        if key in after_conflicts:
            change = "became_conflicted" if key not in before_conflicts else "conflicted"
        elif key in before_conflicts:
            change = "conflict_resolved"
        elif left is None:
            change = "added"
        elif right is None:
            change = "removed"
        elif _fact_value_token(left) != _fact_value_token(right):
            change = "value_changed"
        elif (
            left.get("source_kind"), left.get("source_ref"), left.get("source_class")
        ) != (
            right.get("source_kind"), right.get("source_ref"), right.get("source_class")
        ):
            change = "provenance_changed"
        else:
            continue
        changes.append({
            "key": key,
            "change": change,
            "before": _safe_fact(left),
            "after": _safe_fact(right),
        })
        if change in {"added", "removed", "value_changed", "conflict_resolved"}:
            candidate_keys.append(key)
    complete = bool(
        (before.get("completeness") or {}).get("status") == "complete"
        and (after.get("completeness") or {}).get("status") == "complete"
        and not before_conflicts
        and not after_conflicts
    )
    projection = {
        "schema": DELTA_SCHEMA,
        "lineage_id": before.get("lineage_id"),
        "profile_digest": (before.get("profile") or {}).get("digest"),
        "before_snapshot_id": before.get("snapshot_id"),
        "after_snapshot_id": after.get("snapshot_id"),
        "changes": changes,
        "candidate_keys": candidate_keys,
        "complete": complete,
    }
    projection["delta_digest"] = digest(projection)
    return projection


def analyze_history(*, snapshots: list[dict], observations: list[dict],
                    research_key: str) -> dict:
    """Find the earliest observed vulnerable state in caller-declared order."""
    if not isinstance(research_key, str) or not research_key or len(research_key) > 128:
        raise ConfigurationLineageError("research key is invalid")
    if not isinstance(snapshots, list) or len(snapshots) < 2 or len(snapshots) > 32:
        raise ConfigurationLineageError("history requires 2 to 32 ordered snapshots")
    ids = [item.get("snapshot_id") for item in snapshots]
    if any(item.get("schema") != SNAPSHOT_SCHEMA for item in snapshots):
        raise ConfigurationLineageError("history contains an invalid snapshot")
    if None in ids or len(set(ids)) != len(ids):
        raise ConfigurationLineageError("history snapshot ids must be present and unique")
    lineages = {item.get("lineage_id") for item in snapshots}
    profiles = {(item.get("profile") or {}).get("digest") for item in snapshots}
    if len(lineages) != 1 or None in lineages:
        raise ConfigurationLineageError("history snapshots belong to different lineages")
    if len(profiles) != 1 or None in profiles:
        raise ConfigurationLineageError("history snapshots use different profiles")
    by_snapshot = {}
    for observation in observations:
        if not isinstance(observation, dict):
            raise ConfigurationLineageError("history observation must be an object")
        snapshot_id = observation.get("snapshot_id")
        if snapshot_id not in ids or snapshot_id in by_snapshot:
            raise ConfigurationLineageError("history observation snapshot is invalid")
        if observation.get("verdict") not in {
            "confirmed", "refuted", "inconclusive", "infrastructure_failure"
        }:
            raise ConfigurationLineageError("history observation verdict is invalid")
        by_snapshot[snapshot_id] = observation

    earliest_index = next((
        index for index, snapshot in enumerate(snapshots)
        if (by_snapshot.get(snapshot["snapshot_id"]) or {}).get("verdict") == "confirmed"
        and (by_snapshot.get(snapshot["snapshot_id"]) or {}).get("controls_healthy") is True
    ), None)
    predecessor_index = None
    if earliest_index is not None:
        predecessor_index = next((
            index for index in range(earliest_index - 1, -1, -1)
            if (by_snapshot.get(snapshots[index]["snapshot_id"]) or {}).get("verdict")
            == "refuted"
            and (by_snapshot.get(snapshots[index]["snapshot_id"]) or {}).get(
                "controls_healthy"
            ) is True
        ), None)

    missing_evidence = []
    delta = None
    confidence = "unknown"
    if earliest_index is None:
        missing_evidence.append("no_confirmed_state")
    elif predecessor_index is None:
        missing_evidence.append("no_refuted_predecessor")
    else:
        before = snapshots[predecessor_index]
        after = snapshots[earliest_index]
        delta = compare_snapshots(before, after)
        earlier_observation = by_snapshot[before["snapshot_id"]]
        later_observation = by_snapshot[after["snapshot_id"]]
        comparable = (
            earlier_observation.get("validator_id")
            == later_observation.get("validator_id")
            and earlier_observation.get("validator_version")
            == later_observation.get("validator_version")
            and earlier_observation.get("validator_id") is not None
        )
        if not comparable:
            missing_evidence.append("incomparable_validators")
        adjacent = bool(
            earliest_index == predecessor_index + 1
            and (after.get("target_identity") or {}).get("adjacent_to_previous") is True
        )
        if not adjacent:
            missing_evidence.append("non_adjacent_history")
        complete = delta["complete"]
        if not complete:
            missing_evidence.append("partial_configuration")
        if not delta["candidate_keys"]:
            missing_evidence.append("no_enabling_delta")
        if comparable and delta["candidate_keys"]:
            confidence = "proven" if adjacent and complete else "supported"

    if earliest_index is None and not observations:
        delta = compare_snapshots(snapshots[-2], snapshots[-1])
        if delta["candidate_keys"]:
            confidence = "inferred"
            missing_evidence.append("no_runtime_observations")

    candidate_keys = delta["candidate_keys"] if delta else []
    evidence_digests = sorted({
        evidence
        for observation in by_snapshot.values()
        for evidence in observation.get("evidence_digests") or []
        if isinstance(evidence, str)
    })
    projection = {
        "schema": INTRODUCTION_SCHEMA,
        "research_key": research_key,
        "lineage_id": snapshots[0]["lineage_id"],
        "profile_digest": snapshots[0]["profile"]["digest"],
        "ordered_snapshot_ids": ids,
        "predecessor": (
            snapshots[predecessor_index]["snapshot_id"]
            if predecessor_index is not None else None
        ),
        "earliest_known_vulnerable": (
            snapshots[earliest_index]["snapshot_id"]
            if earliest_index is not None and predecessor_index is not None else None
        ),
        "candidate_keys": candidate_keys,
        "causal_key": candidate_keys[0]
        if confidence == "proven" and len(candidate_keys) == 1 else None,
        "confidence": confidence,
        "missing_evidence": sorted(set(missing_evidence)),
        "delta_digest": delta.get("delta_digest") if delta else None,
        "evidence_digests": evidence_digests,
    }
    projection["analysis_digest"] = digest(projection)
    projection["analysis_id"] = projection["analysis_digest"].removeprefix(
        "sha256:"
    )[:12]
    return projection
