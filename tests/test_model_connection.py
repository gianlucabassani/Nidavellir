"""
Operator's bring-your-own model connection (the topbar bubble → store an API
key). Security-by-design contract: the key is encrypted at rest, never returned
in plaintext, operator-only (agents can't manage it), and a blank key on update
keeps the stored one.
"""
import pytest
from fastapi.testclient import TestClient


def _client(role, name=None):
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(
        auth.hash_api_key(key), name=name or f"{role}-mc", role=role
    )
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    c.principal_name = name or f"{role}-mc"
    return c


@pytest.fixture()
def operator():
    return _client("operator", name="op-mc")


@pytest.fixture()
def agent():
    return _client("agent", name="agent-mc")


def test_put_stores_masked_and_get_round_trips(operator):
    r = operator.put(
        "/agent/model",
        json={"provider": "anthropic", "model": "claude-opus-4-8", "api_key": "sk-ant-secret-9999"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # masked: provider/model/last4/status, NEVER the key
    assert body["configured"] is True
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-opus-4-8"
    assert body["key_last4"] == "9999"
    assert body["status"] == "standby"
    assert "api_key" not in body and "encrypted_key" not in body
    assert "sk-ant-secret-9999" not in r.text

    g = operator.get("/agent/model").json()
    assert g["configured"] is True and g["provider"] == "anthropic"
    assert "sk-ant-secret-9999" not in str(g)


def test_key_recoverable_in_process_only(operator):
    from database import Database

    operator.put(
        "/agent/model",
        json={"provider": "openai", "model": "gpt-4o", "api_key": "sk-openai-abcd"},
    )
    cred = Database().get_decrypted_model_credential("op-mc")
    assert cred["api_key"] == "sk-openai-abcd"  # in-process decrypt works
    assert cred["provider"] == "openai"


def test_key_encrypted_at_rest_when_cipher_enabled(operator, monkeypatch):
    import crypto
    from cryptography.fernet import Fernet
    from database import Database
    from models import ModelConnection

    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_default_cipher()
    try:
        operator.put(
            "/agent/model",
            json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-deepseek-zzzz"},
        )
        db = Database()
        with db._session() as s:  # noqa: SLF001 - test reaches into storage on purpose
            row = s.get(ModelConnection, "op-mc")
            assert row.encrypted_key != "sk-deepseek-zzzz"  # ciphertext at rest
            assert "sk-deepseek-zzzz" not in row.encrypted_key
        assert db.get_decrypted_model_credential("op-mc")["api_key"] == "sk-deepseek-zzzz"
    finally:
        monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)
        crypto.reset_default_cipher()


def test_blank_key_on_update_keeps_stored_key(operator):
    from database import Database

    operator.put(
        "/agent/model",
        json={"provider": "anthropic", "model": "claude-opus-4-8", "api_key": "sk-keep-1234"},
    )
    # update only the model, leave the key blank
    r = operator.put(
        "/agent/model",
        json={"provider": "anthropic", "model": "claude-sonnet-4-6", "api_key": ""},
    )
    assert r.status_code == 200
    assert r.json()["model"] == "claude-sonnet-4-6"
    assert r.json()["key_last4"] == "1234"  # unchanged
    assert Database().get_decrypted_model_credential("op-mc")["api_key"] == "sk-keep-1234"


def test_cloud_provider_requires_key(operator):
    r = operator.put("/agent/model", json={"provider": "gemini", "model": "gemini-2.0-flash", "api_key": ""})
    assert r.status_code == 422
    assert "requires an API key" in r.text


def test_keyless_local_provider_allowed_without_key(operator):
    r = operator.put("/agent/model", json={"provider": "ollama", "model": "llama3", "api_key": ""})
    assert r.status_code == 200
    assert r.json()["provider"] == "ollama"
    assert r.json()["key_last4"] is None


def test_unknown_provider_rejected(operator):
    r = operator.put("/agent/model", json={"provider": "skynet", "model": "x", "api_key": "k"})
    assert r.status_code == 422


def test_delete_forgets_connection(operator):
    operator.put("/agent/model", json={"provider": "openai", "model": "gpt-4o", "api_key": "sk-del-1234"})
    assert operator.delete("/agent/model").json()["removed"] is True
    assert operator.get("/agent/model").json() == {"configured": False}
    assert operator.delete("/agent/model").json()["removed"] is False  # idempotent


def test_agent_role_cannot_manage_credentials(agent):
    assert agent.get("/agent/model").status_code == 403
    assert agent.put(
        "/agent/model", json={"provider": "anthropic", "model": "m", "api_key": "k"}
    ).status_code == 403
    assert agent.delete("/agent/model").status_code == 403


def test_connections_are_per_operator(operator):
    operator.put("/agent/model", json={"provider": "openai", "model": "gpt-4o", "api_key": "sk-op-1111"})
    other = _client("operator", name="op2-mc")
    assert other.get("/agent/model").json() == {"configured": False}
    other.put("/agent/model", json={"provider": "gemini", "model": "gemini-2.0-flash", "api_key": "k-2222"})
    # each operator sees only their own
    assert operator.get("/agent/model").json()["provider"] == "openai"
    assert other.get("/agent/model").json()["provider"] == "gemini"
