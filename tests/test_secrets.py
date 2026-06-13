"""
Secrets hygiene (P2-4, audit #14 / SECURITY gap #6):
  - redaction.py masks secrets in log/error text and variable dicts;
  - crypto.py encrypts lab outputs at rest behind SECRETS_ENCRYPTION_KEY;
  - the Database facade encrypts on write and decrypts on read, transparently.
"""
import json

import pytest
from cryptography.fernet import Fernet

import crypto
import redaction
from database import Database
from redaction import MASK


# --- redaction -------------------------------------------------------------

def test_redact_masks_known_secret_value(monkeypatch):
    monkeypatch.setenv("OS_PASSWORD", "sup3r-s3cret-pw")
    text = "Auth error for user admin with password sup3r-s3cret-pw on cloud"
    out = redaction.redact(text)
    assert "sup3r-s3cret-pw" not in out
    assert MASK in out


def test_redact_masks_key_value_pairs():
    assert redaction.redact("os_password=topsecret123").endswith(MASK)
    # JSON-style sensitive key
    out = redaction.redact('{"password": "topsecret123", "host": "10.0.0.1"}')
    assert "topsecret123" not in out
    assert "10.0.0.1" in out  # non-sensitive value preserved
    # api_key variants
    assert "abcdef123456" not in redaction.redact("X-Api-Key: abcdef123456")


def test_redact_leaves_non_sensitive_untouched():
    text = "victim_image_name=ubuntu-22.04 private_cidr=10.0.0.0/24"
    assert redaction.redact(text) == text


def test_redact_handles_none_and_non_strings():
    assert redaction.redact(None) is None
    assert redaction.redact(1234) == "1234"


def test_redact_mapping_masks_sensitive_keys_only():
    out = redaction.redact_mapping(
        {"victim_image_name": "ubuntu", "OS_PASSWORD": "secret", "api_key": "abc"}
    )
    assert out["victim_image_name"] == "ubuntu"
    assert out["OS_PASSWORD"] == MASK
    assert out["api_key"] == MASK
    # non-dicts pass through
    assert redaction.redact_mapping(None) is None


def test_short_secret_value_not_masked(monkeypatch):
    # Too short to mask safely (and an empty default must never blank the line).
    monkeypatch.setenv("OS_PASSWORD", "ab")
    crypto.reset_default_cipher()
    assert redaction.redact("connecting with token ab here") == (
        "connecting with token ab here"
    )


# --- crypto: cipher unit behaviour -----------------------------------------

def test_disabled_cipher_is_passthrough():
    cipher = crypto.SecretCipher(key=None)
    assert cipher.enabled is False
    assert cipher.encrypt('{"a": 1}') == '{"a": 1}'
    assert cipher.decrypt('{"a": 1}') == '{"a": 1}'


def test_enabled_cipher_roundtrips_and_tags():
    cipher = crypto.SecretCipher(key=Fernet.generate_key())
    assert cipher.enabled is True
    plaintext = '{"soc_credentials": {"password": "hunter2"}}'
    token = cipher.encrypt(plaintext)
    assert token.startswith("enc:v1:")
    assert "hunter2" not in token
    assert cipher.decrypt(token) == plaintext


def test_decrypt_passes_through_legacy_plaintext():
    cipher = crypto.SecretCipher(key=Fernet.generate_key())
    # A row written before encryption existed has no tag — return it as-is.
    assert cipher.decrypt('{"legacy": true}') == '{"legacy": true}'


def test_decrypt_with_wrong_key_returns_none():
    token = crypto.SecretCipher(key=Fernet.generate_key()).encrypt("data")
    other = crypto.SecretCipher(key=Fernet.generate_key())
    assert other.decrypt(token) is None


def test_decrypt_tagged_value_without_key_returns_none():
    token = crypto.SecretCipher(key=Fernet.generate_key()).encrypt("data")
    assert crypto.SecretCipher(key=None).decrypt(token) is None


# --- database integration: encryption at rest ------------------------------

@pytest.fixture
def encryption_on(monkeypatch):
    """Enable at-rest encryption for one test, then restore disabled state."""
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_default_cipher()
    yield
    monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)
    crypto.reset_default_cipher()


def test_outputs_encrypted_at_rest_but_readable(encryption_on):
    from sqlalchemy import text

    db = Database()
    dep_id = "sec-enc-roundtrip"
    db.create_deployment(dep_id, "enc-test", "basic_pentest")
    outputs = {
        "soc_credentials": {"username": "admin", "password": "SecretPassword!"},
        "attack_vm_floating_ip": "192.168.1.80",
    }
    db.update_deployment(dep_id, outputs=outputs, actor="worker")

    # Stored column is ciphertext: tagged and free of the plaintext secret.
    with db._engine.connect() as conn:
        raw = conn.execute(
            text("SELECT outputs FROM deployments WHERE id = :id"), {"id": dep_id}
        ).scalar_one()
    assert raw.startswith("enc:v1:")
    assert "SecretPassword" not in raw

    # But callers get plaintext back, transparently decrypted.
    record = db.get_deployment(dep_id)
    decoded = json.loads(record["outputs"])
    assert decoded["soc_credentials"]["password"] == "SecretPassword!"
    assert decoded["attack_vm_floating_ip"] == "192.168.1.80"


def test_outputs_plaintext_when_encryption_disabled():
    # Default test environment has no key — behaviour must be unchanged.
    from sqlalchemy import text

    crypto.reset_default_cipher()
    db = Database()
    dep_id = "sec-plaintext"
    db.create_deployment(dep_id, "plain-test", "basic_pentest")
    db.update_deployment(dep_id, outputs={"k": "v"}, actor="worker")

    with db._engine.connect() as conn:
        raw = conn.execute(
            text("SELECT outputs FROM deployments WHERE id = :id"), {"id": dep_id}
        ).scalar_one()
    assert raw == '{"k": "v"}'
    assert not crypto.encryption_enabled()
