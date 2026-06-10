"""
Tests for API-key authentication (ADR-0002, ROADMAP audit #2).

Pins the contract: every data route rejects missing/invalid/revoked keys with
401, /health stays open for the container healthcheck, and the bootstrap-key
path registers exactly once.
"""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
from database import Database  # noqa: E402


@pytest.fixture()
def anon_client():
    import api

    return TestClient(api.app)


def _make_key(name="auth-tests", role="student"):
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name, role=role)
    return key


def test_health_is_unauthenticated(anon_client):
    assert anon_client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/deployments"),
        ("post", "/deploy"),
        ("get", "/status/some-id"),
        ("delete", "/destroy/some-id"),
    ],
)
def test_routes_reject_missing_key(anon_client, method, path):
    resp = getattr(anon_client, method)(path)
    assert resp.status_code == 401


def test_invalid_key_rejected(anon_client):
    resp = anon_client.get("/deployments", headers={"X-API-Key": "cg_" + "0" * 48})
    assert resp.status_code == 401


def test_valid_key_accepted_for_any_role(anon_client):
    for role in auth.ROLES:
        key = _make_key(name=f"role-{role}", role=role)
        resp = anon_client.get("/deployments", headers={"X-API-Key": key})
        assert resp.status_code == 200, f"role {role} should authenticate"


def test_revoked_key_rejected(anon_client):
    key = _make_key(name="to-revoke")
    assert anon_client.get("/deployments", headers={"X-API-Key": key}).status_code == 200

    assert Database().revoke_api_keys_by_name("to-revoke") == 1
    assert anon_client.get("/deployments", headers={"X-API-Key": key}).status_code == 401


def test_plaintext_key_never_stored():
    key = _make_key(name="hash-check")
    record = Database().get_api_key(auth.hash_api_key(key))
    assert record is not None
    assert key not in record.values()


def test_bootstrap_key_registers_once(monkeypatch):
    db = Database()
    key = auth.generate_api_key()
    monkeypatch.setenv("BOOTSTRAP_API_KEY", key)
    monkeypatch.setenv("BOOTSTRAP_API_KEY_ROLE", "agent")

    before = db.count_api_keys()
    auth.ensure_bootstrap_key(db)
    assert db.count_api_keys() == before + 1
    assert db.get_api_key(auth.hash_api_key(key))["role"] == "agent"

    # Idempotent: a second startup must not duplicate it.
    auth.ensure_bootstrap_key(db)
    assert db.count_api_keys() == before + 1


def test_bootstrap_rejects_unknown_role(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_API_KEY", auth.generate_api_key())
    monkeypatch.setenv("BOOTSTRAP_API_KEY_ROLE", "superuser")
    with pytest.raises(ValueError, match="BOOTSTRAP_API_KEY_ROLE"):
        auth.ensure_bootstrap_key(Database())
