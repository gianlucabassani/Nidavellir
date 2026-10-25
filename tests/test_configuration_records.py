"""Encrypted immutable configuration records and migration integrity."""
from copy import deepcopy

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

import crypto
from database import Database
from tests.test_configuration_capture import recipe
from configuration_capture import deployment_snapshot


@pytest.fixture
def records(monkeypatch):
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_default_cipher()
    yield Database()
    crypto.reset_default_cipher()


def test_snapshot_records_encrypt_validate_and_retain_after_teardown(records):
    db = records
    db.create_deployment("lineage-record", "owner", "fixture")
    snapshot = deployment_snapshot("lineage-record", recipe())
    saved = db.save_configuration_snapshot(snapshot)
    assert saved == snapshot
    assert db.save_configuration_snapshot(snapshot) == snapshot
    assert db.get_configuration_snapshot(snapshot["snapshot_id"]) == snapshot
    assert db.list_configuration_snapshots("lineage-record") == [snapshot]
    assert db.find_configuration_snapshot_by_digest("lineage-record", snapshot["snapshot_digest"]) == snapshot
    with db._engine.connect() as conn:
        encoded = conn.execute(text("SELECT encrypted_payload FROM configuration_snapshots WHERE id=:id"),
                               {"id": snapshot["snapshot_id"]}).scalar_one()
    assert encoded.startswith("enc:v1:")
    assert "service.authorization" not in encoded
    altered = deepcopy(snapshot)
    altered["effective"][0]["value"] = True
    with pytest.raises(ValueError, match="digest"):
        db.save_configuration_snapshot(altered)


def test_snapshot_records_refuse_plaintext_and_missing_arena(monkeypatch):
    db = Database()
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "")
    crypto.reset_default_cipher()
    snapshot = deployment_snapshot("missing-record", recipe())
    with pytest.raises(ValueError, match="encryption"):
        db.save_configuration_snapshot(snapshot)


def test_snapshot_pagination_and_wrong_arena(records):
    db = records
    db.create_deployment("lineage-pages", "owner", "fixture")
    first = deployment_snapshot("lineage-pages", recipe("false"))
    second = deployment_snapshot("lineage-pages", recipe("true"))
    db.save_configuration_snapshot(first)
    db.save_configuration_snapshot(second)
    page = db.list_configuration_snapshots("lineage-pages", limit=1)
    following = db.list_configuration_snapshots("lineage-pages", limit=1, before=page[0]["snapshot_id"])
    assert len(page) == len(following) == 1
    assert page[0]["snapshot_id"] != following[0]["snapshot_id"]
    assert db.list_configuration_snapshots("unrelated-arena") == []
