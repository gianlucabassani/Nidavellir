"""Configuration capture uses retained inputs, never caller assertions."""
from copy import deepcopy

import configuration_lineage as lineage
import lifecycle_manifest


PROFILE = {
    "schema": "nidavellir/configuration-profile/v1", "id": "lineage-fixture", "version": 1,
    "precedence": ["source", "build", "scenario", "deployment", "setup", "runtime"],
    "facts": [{"key": "service.authorization.disabled", "type": "bool",
               "required": True, "sensitive": False, "security_tags": ["authorization"],
               "sources": [{"kind": "scenario_env", "node": "target", "selector": "DISABLE_AUTH"}]}],
}


def recipe(value="false", profile=None):
    spec = {"name": "lineage-fixture", "nodes": [{"name": "target", "role": "victim",
            "image": "sha256:" + "a" * 64,
            "environment": {"DISABLE_AUTH": value, "UNDECLARED": "do-not-copy"}}],
            "lifecycle": {"configuration_profile": deepcopy(profile or PROFILE)}}
    return lifecycle_manifest.build_recipe(scenario=spec, scenario_name="lineage-fixture",
        requested_provider="docker-local", effective_provider="docker-local")


def test_recipe_retains_normalized_profile_and_projects_identity_only():
    saved = recipe()
    assert saved["configuration_profile"]["digest"] == lineage.validate_profile(PROFILE)["digest"]
    public = lifecycle_manifest.public_recipe(saved)
    assert public["configuration_profile"] == {
        "id": "lineage-fixture", "version": 1,
        "digest": saved["configuration_profile_digest"],
    }
    assert "DISABLE_AUTH" not in repr(public["configuration_profile"])


def test_deployment_capture_extracts_only_declared_typed_facts():
    from configuration_capture import deployment_snapshot

    snapshot = deployment_snapshot("capture-arena", recipe())
    assert snapshot["effective"][0]["value"] is False
    assert "do-not-copy" not in repr(snapshot)
    assert snapshot["completeness"]["status"] == "complete"
    no_profile = recipe()
    no_profile.pop("configuration_profile")
    assert deployment_snapshot("capture-arena", no_profile) is None


def test_deployment_capture_does_not_guess_invalid_values():
    from configuration_capture import deployment_snapshot

    snapshot = deployment_snapshot("capture-invalid", recipe("maybe"))
    assert snapshot["completeness"]["status"] == "partial"
    assert snapshot["effective"] == []


def test_controlled_transition_rejects_undeclared_changes():
    from configuration_capture import controlled_transition

    assert controlled_transition(recipe("false"), recipe("true")) is True
    changed = recipe("true")
    changed["equivalence_projection"]["scenario"]["nodes"][0]["command"] = "changed-startup"
    assert controlled_transition(recipe("false"), changed) is False


def test_setup_provenance_requires_approved_success_and_active_readback():
    from configuration_capture import runtime_snapshot

    profile = deepcopy(PROFILE)
    profile["facts"][0]["sources"] = [{"kind": "setup", "node": "target", "selector": "DISABLE_AUTH", "step": "configure-auth"}]
    observed = {"facts": [{"key": "service.authorization.disabled", "value": True,
        "source_kind": "runtime_readback", "complete": True,
        "source_ref": {"node": "target", "selector": "DISABLE_AUTH", "pristine": False}}]}
    events = [
        {"id": 3, "type": "setup_finished", "payload": {"session_id": "session"}},
        {"id": 2, "type": "setup_step", "payload": {"session_id": "session", "node": "target",
            "configuration_step": "configure-auth", "ok": True, "exit_code": 0,
            "via": "operator", "stdout": "do-not-copy"}}]
    snapshot = runtime_snapshot("setup-arena", recipe(profile=profile), observed,
                                stage="post_setup", setup_events=events)
    assert snapshot["effective"][0]["value"] is True
    assert snapshot["effective"][0]["source_class"] == "setup"
    assert snapshot["effective"][0]["source_ref"]["setup_event_id"] == 2
    assert "do-not-copy" not in repr(snapshot)
    events[1]["payload"]["ok"] = False
    missing = runtime_snapshot("setup-arena", recipe(profile=profile), observed,
                               stage="post_setup", setup_events=events)
    assert missing["effective"] == []
    assert missing["completeness"]["status"] == "partial"
