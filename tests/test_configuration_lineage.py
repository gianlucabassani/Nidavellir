from copy import deepcopy

import pytest
from cryptography.fernet import Fernet

import configuration_lineage as lineage
import crypto


def _profile(*, sensitive=False):
    return {
        "schema": "nidavellir/configuration-profile/v1",
        "id": "fixture-web",
        "version": 1,
        "precedence": ["source", "build", "scenario", "deployment", "setup", "runtime"],
        "facts": [
            {
                "key": "service.auth.registration_enabled",
                "type": "bool",
                "sensitive": sensitive,
                "required": True,
                "security_tags": ["authentication"],
                "sources": [
                    {
                        "kind": "source_file",
                        "path": "config/defaults.env",
                        "parser": "dotenv",
                        "selector": "REGISTRATION_ENABLED",
                    },
                    {
                        "kind": "scenario_env",
                        "node": "victim",
                        "selector": "REGISTRATION_ENABLED",
                    },
                    {
                        "kind": "runtime_env",
                        "node": "victim",
                        "selector": "REGISTRATION_ENABLED",
                    },
                ],
            }
        ],
    }


def _identity(digest="a" * 40, *, adjacent=True):
    return {
        "kind": "git",
        "digest": digest,
        "lineage": "https://example.test/repo.git",
        "adjacent_to_previous": adjacent,
    }


def _fact(value, source_kind, **source_ref):
    return {
        "key": "service.auth.registration_enabled",
        "value": value,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "complete": True,
    }


def _named_fact(key, value, source_kind, **source_ref):
    fact = _fact(value, source_kind, **source_ref)
    fact["key"] = key
    return fact


def _two_fact_profile():
    profile = _profile()
    second = deepcopy(profile["facts"][0])
    second["key"] = "service.debug.enabled"
    second["security_tags"] = ["debug"]
    second["sources"] = [deepcopy(second["sources"][-1])]
    second["sources"][0]["selector"] = "DEBUG_ENABLED"
    profile["facts"].append(second)
    return profile


def _history_snapshot(
    *, value, digest, captured_at, adjacent=True, arena_id=None, second_value=None
):
    profile = _two_fact_profile() if second_value is not None else _profile()
    facts = [
        _fact(value, "source_file", path="config/defaults.env"),
        _fact(value, "scenario_env", node="victim"),
        _fact(value, "runtime_env", node="victim"),
    ]
    if second_value is not None:
        facts.append(
            _named_fact(
                "service.debug.enabled", second_value, "runtime_env", node="victim"
            )
        )
    return lineage.capture_snapshot(
        arena_id=arena_id or f"arena-{digest[0]}",
        target_identity=_identity(digest, adjacent=adjacent),
        profile=profile,
        facts=facts,
        stage="runtime",
        lineage_id="fixture-lineage",
        captured_at=captured_at,
    )


def _observation(snapshot, verdict, *, healthy=True):
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "verdict": verdict,
        "controls_healthy": healthy,
        "validator_id": "http_access_control",
        "validator_version": 1,
        "probe_digest": "sha256:" + "9" * 64,
        "control_plan_digest": "sha256:" + "7" * 64,
        "replay_verified": True,
        "evidence_digests": [
            "sha256:" + ("1" if verdict == "refuted" else "2") * 64
        ],
    }


@pytest.fixture
def encryption_on(monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_default_cipher()
    yield
    crypto.reset_default_cipher()


def test_validate_profile_rejects_executable_or_unknown_parser():
    executable = _profile()
    executable["facts"][0]["sources"][0]["command"] = "cat /etc/shadow"
    with pytest.raises(lineage.ConfigurationLineageError, match="unknown field"):
        lineage.validate_profile(executable)

    unknown = _profile()
    unknown["facts"][0]["sources"][0]["parser"] = "python"
    with pytest.raises(lineage.ConfigurationLineageError, match="parser"):
        lineage.validate_profile(unknown)

    traversal = _profile()
    traversal["facts"][0]["sources"][0]["path"] = "../secrets.env"
    with pytest.raises(lineage.ConfigurationLineageError, match="path"):
        lineage.validate_profile(traversal)


def test_capture_snapshot_applies_profile_precedence():
    snapshot = lineage.capture_snapshot(
        arena_id="arena-1",
        target_identity=_identity(),
        profile=_profile(),
        facts=[
            _fact(False, "source_file", ref="a" * 40, path="config/defaults.env"),
            _fact(True, "scenario_env", node="victim", selector="REGISTRATION_ENABLED"),
            _fact(False, "runtime_env", node="victim", selector="REGISTRATION_ENABLED"),
        ],
        stage="runtime",
        lineage_id="fixture-lineage",
        captured_at="2026-10-24T10:00:00+00:00",
    )

    assert snapshot["schema"] == "nidavellir/configuration-snapshot/v1"
    assert snapshot["profile"]["id"] == "fixture-web"
    assert snapshot["profile"]["digest"].startswith("sha256:")
    assert snapshot["effective"][0]["value"] is False
    assert snapshot["effective"][0]["source_class"] == "runtime"
    assert snapshot["completeness"] == {"status": "complete", "missing_layers": []}

    with pytest.raises(lineage.ConfigurationLineageError, match="stage"):
        lineage.capture_snapshot(
            arena_id="arena-1",
            target_identity=_identity(),
            profile=_profile(),
            facts=[],
            stage="after_magic",
            lineage_id="fixture-lineage",
        )


def test_capture_snapshot_is_canonical_across_fact_order():
    facts = [
        _fact(False, "source_file", ref="a" * 40, path="config/defaults.env"),
        _fact(True, "scenario_env", node="victim", selector="REGISTRATION_ENABLED"),
    ]
    common = {
        "arena_id": "arena-1",
        "target_identity": _identity(),
        "profile": _profile(),
        "stage": "deployment",
        "lineage_id": "fixture-lineage",
    }
    first = lineage.capture_snapshot(
        **common, facts=facts, captured_at="2026-10-24T10:00:00+00:00"
    )
    second = lineage.capture_snapshot(
        **common,
        facts=list(reversed(deepcopy(facts))),
        captured_at="2026-10-24T11:00:00+00:00",
    )

    assert first["facts"] == second["facts"]
    assert first["snapshot_digest"] == second["snapshot_digest"]
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["captured_at"] != second["captured_at"]


def test_sensitive_fact_uses_lineage_hmac_and_never_projects_digest(encryption_on):
    snapshot = lineage.capture_snapshot(
        arena_id="arena-secret",
        target_identity=_identity(),
        profile=_profile(sensitive=True),
        facts=[_fact(True, "runtime_env", node="victim", selector="REGISTRATION_ENABLED")],
        stage="runtime",
        lineage_id="target-family-a",
    )

    stored = snapshot["facts"][0]
    assert stored["value_state"] == "withheld"
    assert stored["value_hmac"].startswith("hmac-sha256:")
    assert "value" not in stored
    assert "True" not in stored["value_hmac"]

    for projection in (lineage.public_snapshot(snapshot), lineage.agent_snapshot(snapshot)):
        serialized = repr(projection)
        assert "value_hmac" not in serialized
        assert "hmac-sha256:" not in serialized
        assert "'value': True" not in serialized


def test_sensitive_hmac_changes_between_lineages(encryption_on):
    args = {
        "arena_id": "arena-secret",
        "target_identity": _identity(),
        "profile": _profile(sensitive=True),
        "facts": [_fact(True, "runtime_env", node="victim")],
        "stage": "runtime",
    }
    first = lineage.capture_snapshot(**args, lineage_id="target-family-a")
    second = lineage.capture_snapshot(**args, lineage_id="target-family-b")

    assert first["facts"][0]["value_hmac"] != second["facts"][0]["value_hmac"]


def test_sensitive_capture_refuses_when_encryption_is_disabled(monkeypatch):
    monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)
    crypto.reset_default_cipher()

    with pytest.raises(lineage.ConfigurationLineageError, match="encryption"):
        lineage.capture_snapshot(
            arena_id="arena-secret",
            target_identity=_identity(),
            profile=_profile(sensitive=True),
            facts=[_fact(True, "runtime_env", node="victim")],
            stage="runtime",
            lineage_id="target-family-a",
        )


def test_merge_marks_equal_precedence_conflict_unresolved():
    snapshot = lineage.capture_snapshot(
        arena_id="arena-conflict",
        target_identity=_identity(),
        profile=_profile(),
        facts=[
            _fact(True, "runtime_env", node="victim", selector="A"),
            _fact(False, "runtime_env", node="victim", selector="B"),
        ],
        stage="runtime",
        lineage_id="target-family-a",
    )

    assert snapshot["effective"] == []
    assert snapshot["conflicts"][0]["key"] == "service.auth.registration_enabled"
    assert snapshot["completeness"]["status"] == "partial"


def test_public_and_agent_projection_strip_hmac_and_withheld_value(encryption_on):
    snapshot = lineage.capture_snapshot(
        arena_id="arena-secret",
        target_identity=_identity(),
        profile=_profile(sensitive=True),
        facts=[_fact(False, "source_file", path="config/defaults.env")],
        stage="historical_candidate",
        lineage_id="target-family-a",
    )

    for projection in (lineage.public_snapshot(snapshot), lineage.agent_snapshot(snapshot)):
        fact = projection["facts"][0]
        assert fact["value_state"] == "withheld"
        assert set(fact).isdisjoint({"value", "value_hmac"})


def test_compare_reports_value_provenance_unknown_and_conflict_changes():
    before = _history_snapshot(
        value=False, digest="a" * 40, captured_at="2026-10-24T12:00:00+00:00"
    )
    changed = _history_snapshot(
        value=True, digest="b" * 40, captured_at="2026-10-24T12:01:00+00:00"
    )
    delta = lineage.compare_snapshots(before, changed)
    assert delta["schema"] == "nidavellir/configuration-delta/v1"
    assert [(item["key"], item["change"]) for item in delta["changes"]] == [
        ("service.auth.registration_enabled", "value_changed")
    ]
    assert delta["candidate_keys"] == ["service.auth.registration_enabled"]

    provenance = deepcopy(before)
    provenance["effective"][0]["source_class"] = "setup"
    provenance["effective"][0]["source_kind"] = "setup"
    provenance["effective"][0]["precedence"] = 4
    provenance["effective"][0]["source_ref"] = {"step": "approved-1"}
    provenance_delta = lineage.compare_snapshots(before, provenance)
    assert provenance_delta["changes"][0]["change"] == "provenance_changed"
    assert provenance_delta["candidate_keys"] == []

    conflicted = lineage.capture_snapshot(
        arena_id="arena-conflict",
        target_identity=_identity("c" * 40),
        profile=_profile(),
        facts=[
            _fact(True, "runtime_env", node="victim", selector="A"),
            _fact(False, "runtime_env", node="victim", selector="B"),
        ],
        stage="runtime",
        lineage_id="fixture-lineage",
    )
    conflict_delta = lineage.compare_snapshots(before, conflicted)
    assert conflict_delta["changes"][0]["change"] == "became_conflicted"
    assert conflict_delta["complete"] is False


def test_analysis_proves_adjacent_refuted_then_confirmed():
    before = _history_snapshot(
        value=False, digest="a" * 40, captured_at="2026-10-24T13:00:00+00:00"
    )
    after = _history_snapshot(
        value=True, digest="b" * 40, captured_at="2026-10-24T13:01:00+00:00"
    )

    analysis = lineage.analyze_history(
        snapshots=[before, after],
        observations=[_observation(before, "refuted"), _observation(after, "confirmed")],
        research_key="finding-root",
    )

    assert analysis["schema"] == "nidavellir/configuration-introduction/v1"
    assert analysis["confidence"] == "proven"
    assert analysis["predecessor"] == before["snapshot_id"]
    assert analysis["earliest_known_vulnerable"] == after["snapshot_id"]
    assert analysis["candidate_keys"] == ["service.auth.registration_enabled"]


def test_analysis_downgrades_when_intermediate_or_required_layer_is_missing():
    before = _history_snapshot(
        value=False, digest="a" * 40, captured_at="2026-10-24T14:00:00+00:00"
    )
    non_adjacent = _history_snapshot(
        value=True,
        digest="c" * 40,
        adjacent=False,
        captured_at="2026-10-24T14:02:00+00:00",
    )
    analysis = lineage.analyze_history(
        snapshots=[before, non_adjacent],
        observations=[
            _observation(before, "refuted"),
            _observation(non_adjacent, "confirmed"),
        ],
        research_key="finding-root",
    )
    assert analysis["confidence"] == "supported"
    assert "non_adjacent_history" in analysis["missing_evidence"]

    partial = deepcopy(non_adjacent)
    partial["target_identity"]["adjacent_to_previous"] = True
    partial["completeness"] = {
        "status": "partial",
        "missing_layers": ["deployment"],
    }
    partial_analysis = lineage.analyze_history(
        snapshots=[before, partial],
        observations=[_observation(before, "refuted"), _observation(partial, "confirmed")],
        research_key="finding-root",
    )
    assert partial_analysis["confidence"] == "supported"
    assert "partial_configuration" in partial_analysis["missing_evidence"]


def test_analysis_keeps_multiple_enabling_candidates():
    before = _history_snapshot(
        value=False,
        second_value=False,
        digest="a" * 40,
        captured_at="2026-10-24T15:00:00+00:00",
    )
    after = _history_snapshot(
        value=True,
        second_value=True,
        digest="b" * 40,
        captured_at="2026-10-24T15:01:00+00:00",
    )
    analysis = lineage.analyze_history(
        snapshots=[before, after],
        observations=[_observation(before, "refuted"), _observation(after, "confirmed")],
        research_key="finding-root",
    )
    assert analysis["confidence"] == "proven"
    assert analysis["candidate_keys"] == [
        "service.auth.registration_enabled",
        "service.debug.enabled",
    ]
    assert analysis["causal_key"] is None


def test_analysis_never_uses_timestamp_as_history_order():
    confirmed = _history_snapshot(
        value=True, digest="b" * 40, captured_at="2026-10-24T09:00:00+00:00"
    )
    refuted = _history_snapshot(
        value=False, digest="a" * 40, captured_at="2026-10-24T16:00:00+00:00"
    )

    analysis = lineage.analyze_history(
        snapshots=[confirmed, refuted],
        observations=[
            _observation(confirmed, "confirmed"),
            _observation(refuted, "refuted"),
        ],
        research_key="finding-root",
    )

    assert analysis["confidence"] == "unknown"
    assert analysis["earliest_known_vulnerable"] is None
    assert "no_refuted_predecessor" in analysis["missing_evidence"]


def test_analysis_requires_matched_probes_and_replay_evidence():
    before = _history_snapshot(value=False, digest="a" * 40, captured_at="2026-10-24T13:00:00+00:00")
    after = _history_snapshot(value=True, digest="b" * 40, captured_at="2026-10-24T13:01:00+00:00")
    left, right = _observation(before, "refuted"), _observation(after, "confirmed")
    right["probe_digest"] = "sha256:" + "8" * 64
    result = lineage.analyze_history(snapshots=[before, after], observations=[left, right], research_key="root")
    assert result["confidence"] == "unknown"
    right["probe_digest"] = left["probe_digest"]
    right["replay_verified"] = False
    result = lineage.analyze_history(snapshots=[before, after], observations=[left, right], research_key="root")
    assert result["confidence"] == "supported"


def test_historical_candidate_does_not_hide_missing_runtime_layers():
    snapshot = lineage.capture_snapshot(arena_id="partial-history", target_identity=_identity(),
        profile=_profile(), facts=[_fact(False, "source_file", path="config/defaults.env")],
        stage="historical_candidate", lineage_id="fixture")
    assert snapshot["completeness"]["status"] == "partial"
    assert "runtime" in snapshot["completeness"]["missing_layers"]


def test_profile_rejects_string_booleans_and_unnormalized_paths():
    profile = _profile()
    profile["facts"][0]["sensitive"] = "false"
    with pytest.raises(lineage.ConfigurationLineageError):
        lineage.validate_profile(profile)
    profile = _profile()
    profile["facts"][0]["sources"][0]["path"] = "config/./defaults.env"
    with pytest.raises(lineage.ConfigurationLineageError):
        lineage.validate_profile(profile)


def test_required_runtime_observation_is_checked_per_key():
    profile = _two_fact_profile()
    snapshot = lineage.capture_snapshot(arena_id="partial-key", target_identity=_identity(),
        profile=profile, facts=[
            _fact(False, "source_file", path="config/defaults.env"),
            _fact(False, "scenario_env", node="victim"),
            _named_fact("service.debug.enabled", False, "runtime_env", node="victim")],
        stage="runtime", lineage_id="fixture")
    assert snapshot["completeness"]["status"] == "partial"
    assert "service.auth.registration_enabled@runtime" in snapshot["completeness"]["missing_facts"]


def test_different_control_plans_cannot_prove_introduction():
    before = _history_snapshot(value=False, digest="a" * 40, captured_at="2026-10-24T13:00:00+00:00")
    after = _history_snapshot(value=True, digest="b" * 40, captured_at="2026-10-24T13:01:00+00:00")
    left, right = _observation(before, "refuted"), _observation(after, "confirmed")
    right["control_plan_digest"] = "sha256:" + "6" * 64
    result = lineage.analyze_history(snapshots=[before, after], observations=[left, right], research_key="root")
    assert result["confidence"] == "unknown"


def test_unknown_sensitivity_is_withheld_instead_of_defaulting_public(encryption_on):
    profile = _profile()
    profile["facts"][0].pop("sensitive")
    snapshot = lineage.capture_snapshot(arena_id="unknown-sensitivity", target_identity=_identity(),
        profile=profile, facts=[_fact(True, "runtime_env", node="victim")], stage="runtime", lineage_id="fixture")
    assert snapshot["facts"][0]["value_state"] == "withheld"
    assert "value" not in snapshot["facts"][0]
