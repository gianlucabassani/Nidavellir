"""NV-10 offline recovery: historical records, key custody and atomic rejection."""
from datetime import datetime
import json
import zipfile

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select

import recovery
from crypto import SecretCipher
from models import Base, Deployment, Event
from database import Database
from uuid import uuid4


def _database(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine


def _source(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", key)
    engine = _database(tmp_path / "source.sqlite")
    now = datetime(2026, 9, 27)
    with engine.begin() as conn:
        conn.execute(Deployment.__table__.insert().values(
            id="old-result", scenario="synthetic", status="destroyed",
            created_at=now, updated_at=now,
            outputs=SecretCipher(key).encrypt('{"proof":"historical"}'),
            provider="docker-local", effective_provider="docker-local"))
        conn.execute(Event.__table__.insert().values(
            lab_id="old-result", ts=now, actor="operator", type="finding",
            payload='{"validation":{"verdict":"confirmed"}}'))
    (root / "data" / "scenarios").mkdir(parents=True)
    (root / "data" / "scenarios" / "synthetic.yaml").write_text("schema: nidavellir/v3\n")
    (root / "traces").mkdir()
    (root / "traces" / "old-result.jsonl").write_text('{"tool":"http_request"}\n')
    return root, engine, key


def test_encrypted_backup_restore_and_redacted_share(tmp_path, monkeypatch):
    root, source_db, key = _source(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert b"historical" not in bundle.read_bytes()
    share = tmp_path / "share.json"
    result = recovery.share(bundle, share, "a-long-fixture-passphrase")
    assert result["counts"]["finding_verdicts"]["confirmed"] == 1
    assert b"old-result" not in share.read_bytes()
    assert key.encode() not in share.read_bytes()

    target = tmp_path / "clean"
    target_db = _database(tmp_path / "clean.sqlite")
    recovery.restore(bundle, target, "a-long-fixture-passphrase", url=str(target_db.url))
    with target_db.connect() as conn:
        old = conn.execute(select(Deployment.outputs).where(Deployment.id == "old-result")).scalar_one()
        assert SecretCipher(key).decrypt(old) == '{"proof":"historical"}'
        assert conn.execute(select(Event).where(Event.lab_id == "old-result")).first()
    assert (target / "traces" / "old-result.jsonl").is_file()
    assert (target / "data" / "scenarios" / "synthetic.yaml").is_file()
    assert (target / "keys" / "recovery.env").read_text() == f"SECRETS_ENCRYPTION_KEY={key}\n"
    assert target.joinpath("keys", "recovery.env").stat().st_mode & 0o777 == 0o600


def test_tampered_bundle_leaves_clean_target_untouched(tmp_path, monkeypatch):
    root, source_db, _ = _source(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    data = bytearray(bundle.read_bytes())
    data[-20] ^= 1
    bundle.write_bytes(data)
    target = tmp_path / "clean"
    target_db = _database(tmp_path / "clean.sqlite")
    with pytest.raises(recovery.RecoveryError, match="authentication failed"):
        recovery.restore(bundle, target, "a-long-fixture-passphrase", url=str(target_db.url))
    assert not list(target.iterdir())
    with target_db.connect() as conn:
        assert not conn.execute(select(Deployment)).first()


def test_schema_mismatch_refuses_restore_before_state_copy(tmp_path, monkeypatch):
    root, source_db, _ = _source(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    target = tmp_path / "clean"
    target_db = _database(tmp_path / "clean.sqlite")
    with target_db.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE deployments ADD COLUMN unexpected TEXT")
    with pytest.raises(recovery.RecoveryError, match="incompatible database table"):
        recovery.restore(bundle, target, "a-long-fixture-passphrase", url=str(target_db.url))
    assert not list(target.iterdir())
    with target_db.connect() as conn:
        assert not conn.execute(select(Deployment)).first()


def test_database_install_error_rolls_back_copied_files(tmp_path, monkeypatch):
    root, source_db, _ = _source(tmp_path, monkeypatch)
    bundle = tmp_path / "original.nvr"
    passphrase = "a-long-fixture-passphrase"
    recovery.backup(root, bundle, passphrase, url=str(source_db.url))
    archive = tmp_path / "original.zip"
    recovery._decrypt_file(bundle, archive, passphrase)
    with zipfile.ZipFile(archive) as source:
        members = {name: source.read(name) for name in source.namelist()}
    records = json.loads(members["database.json"])
    records["tables"]["deployments"][0]["created_at"] = "not-a-timestamp"
    members["database.json"] = recovery._json(records)
    manifest = json.loads(members["manifest.json"])
    manifest["database_sha256"] = recovery._sha(members["database.json"])
    members["manifest.json"] = recovery._json(manifest)
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(corrupt, "w") as target:
        for name, data in members.items():
            target.writestr(name, data)
    failed_bundle = tmp_path / "failed.nvr"
    recovery._crypt_file(corrupt, failed_bundle, passphrase)
    target = tmp_path / "clean"
    target_db = _database(tmp_path / "clean.sqlite")
    with pytest.raises(ValueError, match="Invalid isoformat"):
        recovery.restore(failed_bundle, target, passphrase, url=str(target_db.url))
    assert not list(target.iterdir())
    with target_db.connect() as conn:
        assert not conn.execute(select(Deployment)).first()


def test_missing_evidence_reference_refuses_backup(tmp_path, monkeypatch):
    root, source_db, _ = _source(tmp_path, monkeypatch)
    with source_db.begin() as conn:
        conn.execute(Event.__table__.insert().values(
            lab_id="old-result", ts=datetime(2026, 9, 27), actor="operator", type="finding",
            payload='{"evidence_artifacts":[{"digest":"sha256:' + '0' * 64 + '"}]}'))
    bundle = tmp_path / "result.nvr"
    with pytest.raises(recovery.RecoveryError, match="finding evidence reference"):
        recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert not bundle.exists()


def test_retention_cannot_delete_only_research_record():
    database = Database()
    arena = "nv10-retain-" + uuid4().hex
    database.create_deployment(arena, "operator", "synthetic")
    database.update_deployment(arena, status="destroying")
    database.update_deployment(arena, status="destroyed")
    database.record_event(arena, "finding", {"validation": {"verdict": "confirmed"}},
                          actor="operator")
    with pytest.raises(ValueError, match="retaining this record"):
        database.delete_deployment(arena)
    database.purge_deployments(("destroyed",))
    assert database.get_deployment(arena) is not None
