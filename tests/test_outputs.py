"""
Tests for terraform output handling (ROADMAP audit #6 / #8).

`tofu output -json` wraps every output in {"value": ..., "type": ...}.
_get_outputs must flatten that to {name: value} so the DB/UI see the same
shape mock mode produces — and must fail soft (log + {}) instead of the old
bare `except`.
"""
import json
import subprocess

from orchestrator import Orchestrator


class _FakeCompleted:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


def test_get_outputs_flattens_terraform_envelope(monkeypatch, tmp_path):
    raw = {
        "attack_vm_floating_ip": {"value": "10.0.0.5", "type": "string", "sensitive": False},
        "soc_credentials": {"value": {"username": "admin"}, "type": ["object"]},
    }
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(json.dumps(raw))
    )

    outputs = Orchestrator()._get_outputs(tmp_path)

    assert outputs == {
        "attack_vm_floating_ip": "10.0.0.5",
        "soc_credentials": {"username": "admin"},
    }


def test_get_outputs_returns_empty_on_tool_failure(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "tofu")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert Orchestrator()._get_outputs(tmp_path) == {}


def test_get_outputs_returns_empty_on_garbage_json(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted("not-json{")
    )
    assert Orchestrator()._get_outputs(tmp_path) == {}
