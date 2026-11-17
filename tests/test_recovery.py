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


def test_restore_with_sqlite_database_inside_data_volume(tmp_path, monkeypatch):
    root, source_db, key = _source(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    passphrase = "a-long-fixture-passphrase"
    recovery.backup(root, bundle, passphrase, url=str(source_db.url))
    target = tmp_path / "clean"
    (target / "data").mkdir(parents=True)
    target_db = _database(target / "data" / "deployments.db")
    recovery.restore(bundle, target, passphrase, url=str(target_db.url))
    with target_db.connect() as conn:
        encrypted = conn.execute(select(Deployment.outputs).where(
            Deployment.id == "old-result")).scalar_one()
        assert SecretCipher(key).decrypt(encrypted) == '{"proof":"historical"}'
    assert (target / "data" / "deployments.db").is_file()
    assert (target / "traces" / "old-result.jsonl").is_file()


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


# --- UI-R4: non-arena source review snapshots ---

def _source_with_snapshot(tmp_path, monkeypatch):
    import config
    import source_review

    root, engine, key = _source(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "SOURCE_REVIEW_SNAPSHOTS_DIR",
                        root / "data" / "source-review-snapshots")
    manifest = source_review.store_snapshot({
        "schema": source_review.SNAPSHOT_SCHEMA, "repo_id": "r" * 64,
        "commit_sha": "a" * 40, "path_scope": ["src/"], "patterns": [], "fix_links": []})
    with engine.begin() as conn:
        conn.execute(Event.__table__.insert().values(
            lab_id="source-review:" + "1" * 32, ts=datetime(2026, 11, 10), actor="worker",
            type="source_review_capture", payload=json.dumps({
                "session_id": "1" * 32, "capture_state": "complete",
                "snapshot_digest": manifest["digest"]})))
    stored = root / "data" / "source-review-snapshots" / manifest["digest"][7:] / "snapshot.json"
    return root, engine, manifest, stored


def test_source_review_snapshot_survives_backup_restore(tmp_path, monkeypatch):
    import config
    import source_review

    root, source_db, manifest, stored = _source_with_snapshot(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    recorded = recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    relative = stored.relative_to(root).as_posix()
    assert recorded["files"][relative]["sha256"] == manifest["digest"][7:]

    target = tmp_path / "clean"
    target_db = _database(tmp_path / "clean.sqlite")
    recovery.restore(bundle, target, "a-long-fixture-passphrase", url=str(target_db.url))
    assert (target / relative).read_bytes() == stored.read_bytes()
    monkeypatch.setattr(config, "SOURCE_REVIEW_SNAPSHOTS_DIR",
                        target / "data" / "source-review-snapshots")
    assert source_review.load_snapshot(manifest["digest"])["commit_sha"] == "a" * 40


def test_altered_source_review_snapshot_refuses_backup(tmp_path, monkeypatch):
    root, source_db, _, stored = _source_with_snapshot(tmp_path, monkeypatch)
    altered = bytearray(stored.read_bytes())
    altered[5] ^= 0x01
    stored.write_bytes(bytes(altered))
    bundle = tmp_path / "result.nvr"
    with pytest.raises(recovery.RecoveryError, match="source review snapshot content address"):
        recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert not bundle.exists()


@pytest.mark.parametrize("manifest", ["[]", "not json", '{"digest": 7}', "wrong-bytes"])
def test_unusable_source_review_manifest_refuses_backup(tmp_path, monkeypatch, manifest):
    root, source_db, recorded, stored = _source_with_snapshot(tmp_path, monkeypatch)
    if manifest == "wrong-bytes":  # the service would refuse this snapshot too
        manifest = json.dumps({**recorded, "bytes": recorded["bytes"] + 1})
    stored.with_name("manifest.json").write_text(manifest)
    bundle = tmp_path / "result.nvr"
    with pytest.raises(recovery.RecoveryError, match="source review snapshot content address"):
        recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert not bundle.exists()


@pytest.mark.parametrize("digest", ["sha256:" + "0" * 64, "sha256:../../../etc", ""])
def test_missing_source_review_snapshot_refuses_backup(tmp_path, monkeypatch, digest):
    root, source_db, _, _ = _source_with_snapshot(tmp_path, monkeypatch)
    with source_db.begin() as conn:
        conn.execute(Event.__table__.insert().values(
            lab_id="source-review:" + "2" * 32, ts=datetime(2026, 11, 10), actor="worker",
            type="source_review_capture", payload=json.dumps({
                "session_id": "2" * 32, "capture_state": "complete",
                "snapshot_digest": digest})))
    bundle = tmp_path / "result.nvr"
    with pytest.raises(recovery.RecoveryError, match="source review snapshot reference"):
        recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert not bundle.exists()


def test_failed_source_review_capture_does_not_block_backup(tmp_path, monkeypatch):
    root, source_db, _, _ = _source_with_snapshot(tmp_path, monkeypatch)
    with source_db.begin() as conn:
        conn.execute(Event.__table__.insert().values(
            lab_id="source-review:" + "3" * 32, ts=datetime(2026, 11, 10), actor="worker",
            type="source_review_capture", payload=json.dumps({
                "session_id": "3" * 32, "capture_state": "failed",
                "reason_code": "query-failed"})))
    bundle = tmp_path / "result.nvr"
    recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert bundle.exists()


# --- MODEL-R1 (A6): headers survive backup/restore; share stays redacted ---

def _source_with_headers(tmp_path, monkeypatch):
    from models import ModelConnection

    root, engine, key = _source(tmp_path, monkeypatch)
    headers = {"User-Agent": "opencode-test/1.0", "x-opencode-session": "sess-123"}
    cipher = SecretCipher(key)
    with engine.begin() as conn:
        conn.execute(ModelConnection.__table__.insert().values(
            owner="bootstrap", provider="custom", model="m",
            encrypted_key=cipher.encrypt(""),
            encrypted_headers=cipher.encrypt(json.dumps(headers, sort_keys=True)),
            key_last4=None, base_url="http://vllm.internal:8000/v1",
            status="standby"))
    return root, engine, key, headers


def test_model_headers_survive_backup_restore(tmp_path, monkeypatch):
    from models import ModelConnection

    root, source_db, key, headers = _source_with_headers(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert b"opencode-test" not in bundle.read_bytes()
    assert b"sess-123" not in bundle.read_bytes()

    target = tmp_path / "clean"
    target_db = _database(tmp_path / "clean.sqlite")
    recovery.restore(bundle, target, "a-long-fixture-passphrase", url=str(target_db.url))
    with target_db.connect() as conn:
        row = conn.execute(select(ModelConnection).where(
            ModelConnection.owner == "bootstrap")).mappings().one()
        assert json.loads(SecretCipher(key).decrypt(row["encrypted_headers"])) == headers


def test_share_report_contains_no_header_material(tmp_path, monkeypatch):
    root, source_db, _, _ = _source_with_headers(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    share = tmp_path / "share.json"
    recovery.share(bundle, share, "a-long-fixture-passphrase")
    raw = share.read_bytes()
    assert b"opencode-test" not in raw
    assert b"sess-123" not in raw
    assert b"x-opencode-session" not in raw
    assert b"header_names" not in raw
    assert b"headers_digest" not in raw


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


# --- NV-14: disclosure bundles ---

def _source_with_bundle(tmp_path, monkeypatch):
    import campaigns
    import config

    root, engine, key = _source(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DISCLOSURE_BUNDLES_DIR", root / "data" / "disclosure-bundles")
    manifest = campaigns.store_bundle({"schema": campaigns.BUNDLE_SCHEMA, "members": []})
    with engine.begin() as conn:
        conn.execute(Event.__table__.insert().values(
            lab_id="campaign:" + "1" * 32, ts=datetime(2026, 11, 10), actor="operator",
            type="campaign_bundle", payload=json.dumps({
                "campaign_id": "1" * 32, "bundle_digest": manifest["digest"]})))
    stored = root / "data" / "disclosure-bundles" / manifest["digest"][7:] / "bundle.json"
    return root, engine, manifest, stored


def test_disclosure_bundle_survives_backup_restore(tmp_path, monkeypatch):
    import campaigns
    import config

    root, source_db, manifest, stored = _source_with_bundle(tmp_path, monkeypatch)
    bundle = tmp_path / "result.nvr"
    recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    target = tmp_path / "clean"
    target_db = _database(tmp_path / "clean.sqlite")
    recovery.restore(bundle, target, "a-long-fixture-passphrase", url=str(target_db.url))
    relative = stored.relative_to(root)
    assert (target / relative).read_bytes() == stored.read_bytes()
    monkeypatch.setattr(config, "DISCLOSURE_BUNDLES_DIR", target / "data" / "disclosure-bundles")
    assert campaigns.load_bundle(manifest["digest"])["members"] == []


def test_altered_disclosure_bundle_refuses_backup(tmp_path, monkeypatch):
    root, source_db, _, stored = _source_with_bundle(tmp_path, monkeypatch)
    altered = bytearray(stored.read_bytes())
    altered[5] ^= 0x01
    stored.write_bytes(bytes(altered))
    bundle = tmp_path / "result.nvr"
    with pytest.raises(recovery.RecoveryError, match="disclosure bundle content address"):
        recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert not bundle.exists()


@pytest.mark.parametrize("digest", ["sha256:" + "0" * 64, "sha256:../../../etc", ""])
def test_missing_disclosure_bundle_refuses_backup(tmp_path, monkeypatch, digest):
    root, source_db, _, _ = _source_with_bundle(tmp_path, monkeypatch)
    with source_db.begin() as conn:
        conn.execute(Event.__table__.insert().values(
            lab_id="campaign:" + "2" * 32, ts=datetime(2026, 11, 10), actor="operator",
            type="campaign_bundle", payload=json.dumps({
                "campaign_id": "2" * 32, "bundle_digest": digest})))
    bundle = tmp_path / "result.nvr"
    with pytest.raises(recovery.RecoveryError, match="disclosure bundle reference"):
        recovery.backup(root, bundle, "a-long-fixture-passphrase", url=str(source_db.url))
    assert not bundle.exists()
