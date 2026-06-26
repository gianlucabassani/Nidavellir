"""
Tests for the zero-to-prompt scenario generator (P3 / Track D).

Two layers, both offline (the model call is injected — no network, no key):
- the pure core in ``generator.py`` (prompt build + JSON extraction + the
  validate-via-ScenarioSpec round trip on a generated spec);
- the ``POST /scenarios/generate`` endpoint (operator-only, 409 without a model
  connection, the review gate: returns a validated spec + topology, never
  deploys/saves), with ``model_chat.complete_chat`` monkeypatched.
"""
import json

import pytest

import generator
from scenario_spec import ScenarioSpec

# A minimal valid v3 spec the fake model "returns".
_GOOD_SPEC = {
    "schema": "nidavellir/v3",
    "name": "Generated SQLi Lab",
    "difficulty": "easy",
    "description": "A vulnerable web app and a Kali foothold.",
    "requires": {"provider_class": "container"},
    "network": {"segments": [{"name": "lab", "description": "isolated bridge"}]},
    "nodes": [
        {"name": "victim", "role": "victim", "image": "dvwa", "segments": ["lab"], "ports": [80]},
        {"name": "attacker", "role": "attacker", "image": "kali", "segments": ["lab"],
         "entrypoint": True, "command": "sleep infinity"},
    ],
    "agents": [{"stance": "attacker", "node": "attacker"}],
    "objectives": [{"description": "Exploit the web app"}],
}


# --- core: prompt building ----------------------------------------------------


def test_build_messages_includes_brief_and_schema():
    system, messages = generator.build_messages("a redis box with RCE")
    assert "nidavellir/v3" in system  # schema guide embedded
    assert messages[0]["role"] == "user"
    assert "redis" in messages[0]["content"]


def test_build_messages_pins_provider_class():
    _, messages = generator.build_messages("anything", provider_class="container")
    assert 'provider_class MUST be "container"' in messages[0]["content"]


def test_build_messages_injects_image_catalog():
    system, _ = generator.build_messages("a dvwa lab")
    assert "Catalog logical images" in system
    assert "dvwa" in system and "kali" in system   # live catalog from images.py
    assert "never invent an image" in system.lower() or "do not invent" in system.lower() \
        or "never invent" in system.lower()


def test_build_messages_container_adds_target_settings_note():
    # Container arenas (default / container / any) get the target-settings rule so
    # the model picks a real image, real ports, and only sets a command to bring a
    # service up (the engine keeps containers alive — no bare keepalive needed).
    for pc in (None, "container", "any"):
        system, _ = generator.build_messages("a vulnerable box", provider_class=pc)
        assert "CONTAINER TARGET SETTINGS" in system
        assert "tail -f /dev/null" in system      # the multi-service command shape
        assert "6379" in system                   # real-port guidance (redis)
    # The vm prompt carries the VM note instead — not the container one.
    vm_system, _ = generator.build_messages("an AD lab", provider_class="vm")
    assert "CONTAINER TARGET SETTINGS" not in vm_system


def test_build_messages_vm_adds_vm_guidance_and_example():
    system, messages = generator.build_messages("an AD lab", provider_class="vm")
    assert "VIRTUAL MACHINES" in system          # vm note appended
    assert "ubuntu-22.04" in system               # vm worked-example present
    assert 'provider_class MUST be "vm"' in messages[0]["content"]
    # the default (container) prompt does NOT carry the vm note
    sys_default, _ = generator.build_messages("x")
    assert "VIRTUAL MACHINES" not in sys_default


# --- core: JSON extraction ----------------------------------------------------


def test_extract_plain_json():
    assert generator.extract_spec_json(json.dumps(_GOOD_SPEC))["name"] == "Generated SQLi Lab"


def test_extract_strips_markdown_fences_and_prose():
    text = "Here is your spec:\n```json\n" + json.dumps(_GOOD_SPEC) + "\n```\nEnjoy!"
    assert generator.extract_spec_json(text)["schema"] == "nidavellir/v3"


def test_extract_empty_reply_raises():
    with pytest.raises(generator.GeneratorError):
        generator.extract_spec_json("   ")


def test_extract_no_json_raises_with_raw():
    with pytest.raises(generator.GeneratorError) as exc:
        generator.extract_spec_json("sorry, I can't do that")
    assert exc.value.raw == "sorry, I can't do that"


def test_extract_malformed_json_raises():
    with pytest.raises(generator.GeneratorError):
        generator.extract_spec_json('{"name": "x",}')  # trailing comma


# --- core: generate + validate round trip ------------------------------------


def test_generate_returns_spec_that_validates():
    raw = generator.generate_scenario_spec(
        lambda system, messages: json.dumps(_GOOD_SPEC), "brief"
    )
    spec = ScenarioSpec.from_raw(raw)  # must not raise
    assert spec.requires.provider_class.value == "container"
    assert len(spec.nodes) == 2


def test_generate_rejects_unknown_provider_class():
    with pytest.raises(generator.GeneratorError):
        generator.generate_scenario_spec(lambda s, m: "{}", "x", provider_class="bogus")


def test_generate_surfaces_model_failure():
    # The model could not reach the provider (stream_chat's error sentinel).
    with pytest.raises(generator.GeneratorError):
        generator.generate_scenario_spec(
            lambda s, m: "[co-pilot] couldn't reach the provider (no egress?).", "x"
        )


# --- endpoint: POST /scenarios/generate ---------------------------------------

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import model_chat  # noqa: E402
from database import Database  # noqa: E402


def _operator_client():
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="gen-op", role="operator")
    import api

    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


def _agent_client():
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="gen-agent", role="agent")
    import api

    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


def test_generate_requires_model_connection(monkeypatch):
    c = _operator_client()
    # No stored model connection for this fresh operator.
    monkeypatch.setattr(
        "database.Database.get_decrypted_model_credential", lambda self, owner: None
    )
    resp = c.post("/scenarios/generate", json={"prompt": "a dvwa lab"})
    assert resp.status_code == 409
    assert "no model connected" in resp.text


def test_generate_returns_validated_spec_and_topology(monkeypatch):
    c = _operator_client()
    monkeypatch.setattr(
        "database.Database.get_decrypted_model_credential",
        lambda self, owner: {"provider": "anthropic", "model": "claude", "api_key": "k"},
    )
    monkeypatch.setattr(model_chat, "complete_chat", lambda *a, **k: json.dumps(_GOOD_SPEC))
    resp = c.post("/scenarios/generate", json={"prompt": "a dvwa sqli lab", "provider_class": "container"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["spec"]["schema"] == "nidavellir/v3"        # echoed for review→import
    assert body["topology"] is not None                      # the preview is rendered
    assert body["summary"]["nodes"] == 2
    assert body["suggested_id"]                              # derivable id for import


_VM_SPEC = {
    "schema": "nidavellir/v3",
    "name": "Linux VM Pentest",
    "difficulty": "medium",
    "description": "A Kali attacker VM and an Ubuntu victim VM on an isolated LAN.",
    "requires": {"provider_class": "vm"},
    "network": {"segments": [{"name": "lan", "description": "isolated"}]},
    "nodes": [
        {"name": "attacker", "role": "attacker", "image": "kali", "segments": ["lan"], "entrypoint": True},
        {"name": "web", "role": "victim", "image": "ubuntu-22.04", "segments": ["lan"], "ports": [22, 80]},
    ],
    "agents": [{"stance": "attacker", "node": "attacker"}],
    "objectives": [{"description": "Exploit and pivot"}],
}


def test_generate_vm_class_spec_validates(monkeypatch):
    """A vm-class generation validates and reports provider_class 'vm' (the spec
    is provider-agnostic; live deploy is gated on a vm backend — see the QEMU
    provider item, out of scope for generation)."""
    c = _operator_client()
    monkeypatch.setattr(
        "database.Database.get_decrypted_model_credential",
        lambda self, owner: {"provider": "anthropic", "model": "claude", "api_key": "k"},
    )
    captured = {}

    def fake_complete(provider, model, api_key, system, messages, **kw):
        captured["system"] = system
        return json.dumps(_VM_SPEC)

    monkeypatch.setattr(model_chat, "complete_chat", fake_complete)
    resp = c.post("/scenarios/generate", json={"prompt": "a linux vm lab", "provider_class": "vm"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["summary"]["provider_class"] == "vm"
    assert "VIRTUAL MACHINES" in captured["system"]   # vm guidance reached the model


def test_generate_warns_on_missing_image(monkeypatch):
    """Field-A: the generate review gate flags images Docker Hub reports missing."""
    import image_check

    c = _operator_client()
    monkeypatch.setattr(
        "database.Database.get_decrypted_model_credential",
        lambda self, owner: {"provider": "anthropic", "model": "claude", "api_key": "k"},
    )
    monkeypatch.setattr(model_chat, "complete_chat", lambda *a, **k: json.dumps(_GOOD_SPEC))
    monkeypatch.setattr(image_check, "exists_on_hub", lambda ref: False)  # all "missing"
    resp = c.post("/scenarios/generate", json={"prompt": "x", "provider_class": "container"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert any("not found on Docker Hub" in w for w in body["warnings"])


def test_generate_invalid_spec_reports_errors_not_500(monkeypatch):
    c = _operator_client()
    monkeypatch.setattr(
        "database.Database.get_decrypted_model_credential",
        lambda self, owner: {"provider": "anthropic", "model": "claude", "api_key": "k"},
    )
    # Model returns JSON that fails v3 validation (no nodes, bad schema id).
    monkeypatch.setattr(model_chat, "complete_chat", lambda *a, **k: '{"name": "x"}')
    resp = c.post("/scenarios/generate", json={"prompt": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["errors"]
    assert body["topology"] is None


def test_generate_no_json_returns_raw(monkeypatch):
    c = _operator_client()
    monkeypatch.setattr(
        "database.Database.get_decrypted_model_credential",
        lambda self, owner: {"provider": "anthropic", "model": "claude", "api_key": "k"},
    )
    monkeypatch.setattr(model_chat, "complete_chat", lambda *a, **k: "I cannot help with that.")
    resp = c.post("/scenarios/generate", json={"prompt": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "I cannot help with that." in body["raw"]


def test_generate_provider_error_is_clean_no_copilot_branding(monkeypatch):
    """An upstream provider error (model_chat's inline sentinel) is surfaced as a
    clean generator error — the 'co-pilot' branding must not leak through."""
    c = _operator_client()
    monkeypatch.setattr(
        "database.Database.get_decrypted_model_credential",
        lambda self, owner: {"provider": "anthropic", "model": "claude", "api_key": "k"},
    )
    monkeypatch.setattr(
        model_chat, "complete_chat",
        lambda *a, **k: model_chat.ERROR_SENTINEL + " the provider rate limit was hit (HTTP 429).",
    )
    resp = c.post("/scenarios/generate", json={"prompt": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "model provider could not complete" in body["errors"][0]
    assert "co-pilot" not in body["errors"][0]


def test_generate_is_operator_only():
    c = _agent_client()
    resp = c.post("/scenarios/generate", json={"prompt": "x"})
    assert resp.status_code == 403
