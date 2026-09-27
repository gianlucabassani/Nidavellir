"""Offline, encrypted NV-10 recovery bundles.

Run with every API, worker, beat and gateway stopped.  A database transaction
cannot make independently written filesystem objects atomic; the offline
boundary is part of this format's consistency contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.exceptions import InvalidTag
from sqlalchemy import DateTime, create_engine, inspect, select

from database import database_url
from models import Base
from crypto import SecretCipher

MAGIC = b"NIDAVELLIR-RECOVERY-V1\n"
VERSION = "nidavellir/recovery/v1"
ROOTS = ("data", "runs", "keys", "traces")
CHUNK = 1024 * 1024


class RecoveryError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _key(passphrase, salt):
    if len(passphrase) < 16:
        raise RecoveryError("recovery passphrase must have at least 16 characters")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=600_000).derive(passphrase.encode())


def _crypt_file(source, dest, passphrase):
    salt, nonce = os.urandom(16), os.urandom(12)
    encryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce)).encryptor()
    with source.open("rb") as inp, dest.open("xb") as out:
        out.write(MAGIC + salt + nonce)
        for block in iter(lambda: inp.read(CHUNK), b""):
            out.write(encryptor.update(block))
        out.write(encryptor.finalize())
        out.write(encryptor.tag)


def _decrypt_file(source, dest, passphrase):
    with source.open("rb") as inp:
        if inp.read(len(MAGIC)) != MAGIC:
            raise RecoveryError("unsupported recovery bundle version")
        salt, nonce = inp.read(16), inp.read(12)
        length = source.stat().st_size - len(MAGIC) - 16 - 12 - 16
        if length < 0:
            raise RecoveryError("truncated recovery bundle")
        inp.seek(-16, os.SEEK_END)
        tag = inp.read(16)
        inp.seek(len(MAGIC) + 28)
        decryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce, tag)).decryptor()
        with dest.open("xb") as out:
            while length:
                block = inp.read(min(CHUNK, length))
                out.write(decryptor.update(block))
                length -= len(block)
            try:
                out.write(decryptor.finalize())
            except InvalidTag as exc:
                raise RecoveryError("bundle authentication failed") from exc


def _schema(engine):
    database = inspect(engine)
    expected = {}
    for name, table in sorted(Base.metadata.tables.items()):
        if not database.has_table(name):
            raise RecoveryError(f"missing database table: {name}")
        columns_info = database.get_columns(name)
        actual = {item["name"] for item in columns_info}
        columns = {column.name for column in table.columns}
        if actual != columns:
            raise RecoveryError(f"incompatible database table: {name}")
        expected[name] = {
            "columns": [{"name": item["name"], "type": str(item["type"]),
                         "nullable": item["nullable"]} for item in sorted(
                             columns_info, key=lambda item: item["name"])],
            "primary_key": sorted(database.get_pk_constraint(name)["constrained_columns"]),
        }
    revision = None
    if database.has_table("alembic_version"):
        with engine.connect() as conn:
            revision = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    return {"tables": expected, "alembic_revision": revision}


def _rows(conn):
    result = {}
    for name, table in sorted(Base.metadata.tables.items()):
        values = []
        for row in conn.execute(select(table)).mappings():
            values.append({key: value.isoformat() if isinstance(value, datetime) else value
                           for key, value in row.items()})
        result[name] = values
    return result


def _check_references(rows):
    ids = {name: {row["id"] for row in values if "id" in row}
           for name, values in rows.items()}
    checks = (("lifecycle_recipes", "deployment_id", "deployments"),
              ("budget_accounts", "arena_id", "deployments"),
              ("budget_actions", "arena_id", "deployments"),
              ("poc_jobs", "arena_id", "deployments"),
              ("forward_leases", "arena_id", "deployments"),
              ("eval_challenges", "source_arena_id", "deployments"),
              ("evaluations", "suite_id", "eval_suites"),
              ("evaluations", "baseline_id", "agent_builds"),
              ("evaluations", "candidate_id", "agent_builds"),
              ("eval_runs", "evaluation_id", "evaluations"),
              ("eval_runs", "build_id", "agent_builds"),
              ("eval_runs", "challenge_id", "eval_challenges"),
              ("eval_trials", "run_id", "eval_runs"),
              ("eval_trials", "evaluation_id", "evaluations"))
    for table, field, target in checks:
        for row in rows[table]:
            if row[field] not in ids[target]:
                raise RecoveryError(f"broken reference: {table}.{field}")
    for row in rows["eval_trials"]:
        if row["arena_id"] is not None and row["arena_id"] not in ids["deployments"]:
            raise RecoveryError("broken trial arena reference")
    for row in rows["eval_suites"]:
        for challenge in json.loads(row["challenge_ids"]):
            if challenge not in ids["eval_challenges"]:
                raise RecoveryError("broken suite challenge reference")
    recipes = {row["deployment_id"]: row["digest"] for row in rows["lifecycle_recipes"]}
    for challenge in rows["eval_challenges"]:
        if recipes.get(challenge["source_arena_id"]) != challenge["recipe_digest"]:
            raise RecoveryError("challenge recipe reference is missing or changed")
    evaluations = {row["id"]: row for row in rows["evaluations"]}
    suites = {row["id"]: set(json.loads(row["challenge_ids"])) for row in rows["eval_suites"]}
    runs = {row["id"]: row for row in rows["eval_runs"]}
    for run in runs.values():
        evaluation = evaluations[run["evaluation_id"]]
        if run["challenge_id"] not in suites[evaluation["suite_id"]] or run["build_id"] not in (
            evaluation["baseline_id"], evaluation["candidate_id"]):
            raise RecoveryError("run is outside its evaluation suite or builds")
    for trial in rows["eval_trials"]:
        if runs[trial["run_id"]]["evaluation_id"] != trial["evaluation_id"]:
            raise RecoveryError("trial run belongs to another evaluation")


def _check_quiescent(rows):
    if any(row["status"] not in ("destroyed", "failed") for row in rows["deployments"]):
        raise RecoveryError("destroy all arenas before offline backup")
    if any(row["state"] not in ("complete", "failed") for row in rows["evaluations"]):
        raise RecoveryError("finish all evaluations before offline backup")


def _check_encrypted_records(rows, key):
    try:
        cipher = SecretCipher(key)
    except (ValueError, TypeError) as exc:
        raise RecoveryError("invalid saved encryption key") from exc
    for table in rows.values():
        for row in table:
            for value in row.values():
                if isinstance(value, str) and value.startswith("enc:v1:") and cipher.decrypt(value) is None:
                    raise RecoveryError("saved encryption key cannot decrypt database records")
    for row in rows["lifecycle_recipes"]:
        plaintext = cipher.decrypt(row["encrypted_payload"])
        if plaintext is None:
            raise RecoveryError("lifecycle recipe cannot be decrypted")
        recipe = json.loads(plaintext)
        content = {key: value for key, value in recipe.items()
                   if key not in ("captured_at", "recipe_digest")}
        digest = "sha256:" + _sha(_json(content))
        if recipe.get("recipe_digest") != row["digest"] or digest != row["digest"]:
            raise RecoveryError("lifecycle recipe digest mismatch")


def _state_files(root):
    for dirname in ROOTS:
        directory = root / dirname
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise RecoveryError(f"invalid state directory: {dirname}")
        for path in sorted(directory.rglob("*")):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise RecoveryError(f"unsupported state entry: {path}")
            if stat.S_ISREG(mode) and not (dirname == "data" and path.name.startswith("deployments.db")) and not (
                dirname == "keys" and path.name == "recovery.env"):
                yield path, path.relative_to(root).as_posix()


def _check_content(root, rows):
    """Check store invariants and event references before accepting a snapshot."""
    for store, body in (("evidence-artifacts", "artifact.patch"),
                        ("http-transactions", "transaction.json")):
        for manifest_path in (root / "data" / store).glob("*/*/manifest.json"):
            manifest = json.loads(manifest_path.read_text())
            digest = manifest.get("digest", "")
            payload = manifest_path.with_name(body)
            if (digest != "sha256:" + _file_hash(payload)
                    or manifest_path.parent.name != digest.removeprefix("sha256:")
                    or manifest_path.parent.parent.name != _sha(manifest["arena_id"].encode())):
                raise RecoveryError(f"invalid {store} content address")
    for path in (root / "data" / "validation-evidence").glob("*/*.json"):
        if path.stem != _file_hash(path):
            raise RecoveryError("invalid validation evidence content address")
    for row in rows["events"]:
        if row["type"] != "finding" or not row["payload"]:
            continue
        payload = json.loads(row["payload"])
        arena = _sha(row["lab_id"].encode())
        for item in payload.get("evidence_artifacts") or []:
            digest = item["digest"].removeprefix("sha256:")
            path = root / "data" / "evidence-artifacts" / arena / digest / "artifact.patch"
            if not path.is_file() or _file_hash(path) != digest:
                raise RecoveryError("finding evidence reference is missing")
        for item in payload.get("http_transactions") or []:
            digest = item["digest"].removeprefix("sha256:")
            path = root / "data" / "http-transactions" / arena / digest / "transaction.json"
            if not path.is_file() or _file_hash(path) != digest:
                raise RecoveryError("finding transaction reference is missing")
        validation = payload.get("validation") or {}
        for field in ("observation_digest", "control_digest"):
            digest = validation.get(field)
            if digest:
                path = root / "data" / "validation-evidence" / arena / (digest[7:] + ".json")
                if not path.is_file() or _file_hash(path) != digest[7:]:
                    raise RecoveryError("finding validation reference is missing")


def backup(root, destination, passphrase, *, url=None):
    """Snapshot an offline installation into one authenticated encrypted file."""
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise RecoveryError("backup destination already exists")
    engine = create_engine(url or database_url())
    try:
        schema = _schema(engine)
        with tempfile.TemporaryDirectory(prefix="nidavellir-backup-") as temp:
            temp = Path(temp)
            archive = temp / "content.zip"
            with engine.connect() as conn:
                with conn.begin():
                    rows = _rows(conn)
                    _check_references(rows)
                    _check_quiescent(rows)
                    _check_encrypted_records(rows, os.getenv("SECRETS_ENCRYPTION_KEY"))
                    _check_content(root, rows)
                    database = _json({"schema": VERSION, "tables": rows})
                    files = {}
                    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                                         allowZip64=True) as zipout:
                        zipout.writestr("database.json", database)
                        for path, relative in _state_files(root):
                            files[relative] = {"sha256": _file_hash(path), "bytes": path.stat().st_size}
                            zipout.write(path, "state/" + relative)
                        secrets = {"SECRETS_ENCRYPTION_KEY": os.getenv("SECRETS_ENCRYPTION_KEY")}
                        zipout.writestr("secrets.json", _json(secrets))
                        manifest = {"schema": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                                    "database_sha256": _sha(database), "database_schema": schema,
                                    "files": files, "secrets_sha256": _sha(_json(secrets))}
                        zipout.writestr("manifest.json", _json(manifest))
                    for path, relative in _state_files(root):
                        if _file_hash(path) != files[relative]["sha256"]:
                            raise RecoveryError("state changed during backup")
            temporary = destination.with_name(destination.name + ".partial")
            if temporary.exists():
                raise RecoveryError("partial backup already exists")
            try:
                _crypt_file(archive, temporary, passphrase)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return manifest
    finally:
        engine.dispose()


def _archive(archive, stage):
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise RecoveryError("duplicate archive entry")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or name.startswith("/"):
                raise RecoveryError("unsafe archive path")
            if name not in ("database.json", "manifest.json", "secrets.json") and not (
                len(path.parts) >= 3 and path.parts[0] == "state" and path.parts[1] in ROOTS
            ):
                raise RecoveryError("unknown archive entry")
        manifest = json.loads(source.read("manifest.json"))
        if manifest.get("schema") != VERSION:
            raise RecoveryError("unsupported recovery manifest")
        expected = {"database.json", "manifest.json", "secrets.json"} | {
            "state/" + name for name in manifest["files"]}
        if set(names) != expected:
            raise RecoveryError("archive entries do not match manifest")
        database = source.read("database.json")
        secrets = source.read("secrets.json")
        if _sha(database) != manifest["database_sha256"] or _sha(secrets) != manifest["secrets_sha256"]:
            raise RecoveryError("database or configuration digest mismatch")
        rows = json.loads(database)
        if rows.get("schema") != VERSION or set(rows["tables"]) != set(Base.metadata.tables):
            raise RecoveryError("database record version mismatch")
        _check_references(rows["tables"])
        for relative, meta in manifest["files"].items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with source.open("state/" + relative) as inp, path.open("xb") as out:
                for block in iter(lambda: inp.read(CHUNK), b""):
                    size += len(block)
                    digest.update(block)
                    out.write(block)
            if size != meta["bytes"] or digest.hexdigest() != meta["sha256"]:
                raise RecoveryError(f"state digest mismatch: {relative}")
        _check_content(stage, rows["tables"])
        return manifest, rows["tables"], json.loads(secrets)


def restore(source, root, passphrase, *, url=None):
    """Validate fully, then install into an empty destination and database."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url or database_url())
    try:
        with tempfile.TemporaryDirectory(prefix="nidavellir-restore-", dir=root) as temp:
            temp = Path(temp)
            archive = temp / "content.zip"
            _decrypt_file(Path(source), archive, passphrase)
            stage = temp / "stage"
            stage.mkdir()
            manifest, rows, secrets = _archive(archive, stage)
            if _schema(engine) != manifest["database_schema"]:
                raise RecoveryError("database schema or Alembic revision mismatch")
            if set(secrets) != {"SECRETS_ENCRYPTION_KEY"}:
                raise RecoveryError("unsupported encryption configuration")
            key = secrets["SECRETS_ENCRYPTION_KEY"]
            _check_encrypted_records(rows, key)
            _check_quiescent(rows)
            config_file = root / "keys" / "recovery.env"
            if config_file.exists():
                raise RecoveryError("restore configuration already exists")
            for dirname in ROOTS:
                target = root / dirname
                if target.exists() and any(target.iterdir()):
                    raise RecoveryError(f"restore destination is not empty: {dirname}")
            installed = []
            created_dirs = []
            try:
                with engine.begin() as conn:
                    for name, table in Base.metadata.tables.items():
                        if name == "budget_gates":
                            existing = conn.execute(select(table)).mappings().all()
                            if existing and not (len(existing) == 1 and existing[0]["scope"] == "system"
                                                 and existing[0]["state"] == "open"):
                                raise RecoveryError("destination database is not empty")
                        elif conn.execute(select(table).limit(1)).first():
                            raise RecoveryError("destination database is not empty")
                    for dirname in ROOTS:
                        staged = stage / dirname
                        if staged.exists():
                            target = root / dirname
                            if not target.exists():
                                target.mkdir()
                                created_dirs.append(target)
                            for source_file in staged.rglob("*"):
                                if source_file.is_file():
                                    destination = target / source_file.relative_to(staged)
                                    destination.parent.mkdir(parents=True, exist_ok=True)
                                    installed.append(destination)
                                    shutil.copy2(source_file, destination)
                    if not config_file.parent.exists():
                        config_file.parent.mkdir(parents=True)
                        created_dirs.append(config_file.parent)
                    installed.append(config_file)
                    config_file.write_text("SECRETS_ENCRYPTION_KEY=" + (key or "") + "\n")
                    config_file.chmod(0o600)
                    for name, table in Base.metadata.tables.items():
                        if name == "budget_gates":
                            conn.execute(table.delete())
                        converted = []
                        for row in rows[name]:
                            converted.append({column.name: datetime.fromisoformat(row[column.name])
                                              if isinstance(column.type, DateTime) and row[column.name] is not None
                                              else row[column.name] for column in table.columns})
                        if converted:
                            conn.execute(table.insert(), converted)
                    if engine.dialect.name == "postgresql":
                        # Explicit audit IDs do not advance PostgreSQL's SERIAL sequence.
                        conn.exec_driver_sql(
                            "SELECT setval(pg_get_serial_sequence('events', 'id'), "
                            "GREATEST(COALESCE(MAX(id), 0), 1), MAX(id) IS NOT NULL) FROM events"
                        )
            except Exception:
                for target in installed:
                    target.unlink(missing_ok=True)
                for dirname in ROOTS:
                    target = root / dirname
                    if target.is_dir():
                        for directory in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                            if directory.is_dir():
                                directory.rmdir()
                for target in created_dirs:
                    target.rmdir()
                raise
            return manifest
    finally:
        engine.dispose()


def share(source, destination, passphrase):
    """Write an allowlisted, aggregate-only report from a verified bundle."""
    destination = Path(destination)
    if destination.exists():
        raise RecoveryError("sharing destination already exists")
    with tempfile.TemporaryDirectory(prefix="nidavellir-share-") as temp:
        temp = Path(temp)
        archive = temp / "content.zip"
        _decrypt_file(Path(source), archive, passphrase)
        manifest, rows, _ = _archive(archive, temp / "state")
        verdicts = {name: 0 for name in ("confirmed", "refuted", "inconclusive", "infrastructure_failure")}
        for row in rows["events"]:
            if row["type"] == "finding" and row["payload"]:
                verdict = (json.loads(row["payload"]).get("validation") or {}).get("verdict")
                if verdict in verdicts:
                    verdicts[verdict] += 1
        report = {"schema": "nidavellir/recovery-share/v1",
                  "source_created_at": manifest["created_at"],
                  "redaction": "aggregate counts only; no identities, prompts, evidence, traces, keys or target manifests",
                  "counts": {"engagements": len(rows["deployments"]),
                             "evaluations": len(rows["evaluations"]),
                             "trials": len(rows["eval_trials"]), "finding_verdicts": verdicts}}
        destination.write_bytes(_json(report) + b"\n")
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore", "share"))
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path, help="redacted sharing report destination")
    parser.add_argument("--database-url", help="SQLAlchemy URL for the offline installation")
    args = parser.parse_args()
    passphrase = os.getenv("NIDAVELLIR_RECOVERY_PASSPHRASE")
    if not passphrase:
        parser.error("NIDAVELLIR_RECOVERY_PASSPHRASE is required")
    if args.action == "share":
        if not args.output:
            parser.error("share requires --output")
        result = share(args.bundle, args.output, passphrase)
        print(json.dumps(result, sort_keys=True))
    else:
        if not args.root:
            parser.error("backup and restore require --root")
        function = backup if args.action == "backup" else restore
        result = function(args.root, args.bundle, passphrase, url=args.database_url) if args.action == "backup" else function(
            args.bundle, args.root, passphrase, url=args.database_url)
        print(json.dumps({"schema": result["schema"], "created_at": result["created_at"],
                          "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
