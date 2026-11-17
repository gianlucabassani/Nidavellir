"""Bounded, immutable local source-bundle intake (ROADMAP M4-B2).

Only regular files and directories from tar/tar.gz inputs are accepted. Intake
never extracts onto the control-plane filesystem and never executes target
content. A sanitized canonical tar is stored beside the original bytes under the
original SHA-256 identity for provider-side materialization.
"""
from __future__ import annotations

import hashlib
import json
import fcntl
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import config

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_MEMBERS = 5000
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_PATH_BYTES = 512
_MAX_DEPTH = 32
_CHUNK = 1024 * 1024


class SourceBundleError(ValueError):
    """The uploaded archive is malformed, unsafe, or violates an intake bound."""


class SourceBundleTooLarge(SourceBundleError):
    """The upload, expanded archive, or artifact store exceeds its configured cap."""


def _safe_name(raw: str) -> PurePosixPath:
    name = raw.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    if not name or "\x00" in name or len(name.encode("utf-8")) > _MAX_PATH_BYTES:
        raise SourceBundleError("archive contains an empty or overlong path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise SourceBundleError(f"archive path escapes its root: {raw!r}")
    if len(path.parts) > _MAX_DEPTH:
        raise SourceBundleError(f"archive path is deeper than {_MAX_DEPTH} components")
    if ".git" in path.parts:
        raise SourceBundleError("bundled .git metadata is not accepted")
    return path


def _members(archive: tarfile.TarFile) -> tuple[list[tuple[tarfile.TarInfo, PurePosixPath]], int]:
    members = []
    names = set()
    expanded = 0
    for member in archive:
        if len(members) >= _MAX_MEMBERS:
            raise SourceBundleTooLarge(f"archive exceeds {_MAX_MEMBERS} members")
        path = _safe_name(member.name)
        if path in names:
            raise SourceBundleError(f"archive contains duplicate path {str(path)!r}")
        names.add(path)
        if not (member.isdir() or member.isreg()):
            raise SourceBundleError(
                f"archive member {str(path)!r} is a link or special file"
            )
        if member.isreg():
            if member.size < 0 or member.size > _MAX_MEMBER_BYTES:
                raise SourceBundleTooLarge(
                    f"archive member {str(path)!r} exceeds 64 MiB"
                )
            expanded += member.size
            if expanded > config.SOURCE_BUNDLE_MAX_EXPANDED_BYTES:
                raise SourceBundleTooLarge(
                    "archive expanded content exceeds the configured limit"
                )
            if getattr(member, "sparse", None):
                raise SourceBundleError("sparse archive members are not accepted")
        members.append((member, path))
    if not members:
        raise SourceBundleError("source bundle is empty")
    if not any(member.isreg() for member, _ in members):
        raise SourceBundleError("source bundle contains no regular files")
    return members, expanded


def _common_root(paths: list[PurePosixPath]) -> str | None:
    first = paths[0].parts[0]
    if all(path.parts[0] == first for path in paths) and any(
        len(path.parts) > 1 for path in paths
    ):
        return first
    return None


def _normalize(source_path: Path, payload_path: Path) -> dict:
    try:
        archive = tarfile.open(source_path, mode="r:*")
    except (tarfile.TarError, OSError) as exc:
        raise SourceBundleError("file is not a valid tar or tar.gz archive") from exc
    with archive:
        members, expanded = _members(archive)
        root = _common_root([path for _, path in members])
        normalized_names = set()
        files = 0
        with tarfile.open(payload_path, mode="w", format=tarfile.PAX_FORMAT) as output:
            for member, original_path in sorted(members, key=lambda item: str(item[1])):
                parts = original_path.parts[1:] if root else original_path.parts
                if not parts:
                    continue
                normalized = PurePosixPath(*parts)
                if normalized in normalized_names:
                    raise SourceBundleError(
                        f"archive paths collide after root normalization: {normalized}"
                    )
                normalized_names.add(normalized)
                info = tarfile.TarInfo(str(normalized))
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                info.pax_headers = {}
                if member.isdir():
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    output.addfile(info)
                    continue
                info.type = tarfile.REGTYPE
                info.size = member.size
                info.mode = 0o755 if member.mode & 0o111 else 0o644
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SourceBundleError(
                        f"could not read archive member {str(original_path)!r}"
                    )
                with extracted:
                    output.addfile(info, extracted)
                files += 1
    return {
        "expanded_bytes": expanded,
        "member_count": len(members),
        "file_count": files,
        "stripped_root": root,
    }


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK), b""):
            size += len(chunk)
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}", size


def _store_size(*, exclude: Path | None = None) -> int:
    root = config.SOURCE_BUNDLES_DIR
    if not root.exists():
        return 0
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and (exclude is None or exclude not in path.parents)
    )


def _artifact_dir(digest: str) -> Path:
    if not _DIGEST_RE.fullmatch(digest or ""):
        raise SourceBundleError("artifact digest must be sha256 followed by 64 hex digits")
    hex_digest = digest.removeprefix("sha256:")
    return config.SOURCE_BUNDLES_DIR / hex_digest[:2] / hex_digest


def get_artifact(digest: str) -> dict:
    """Return persisted public metadata for a source bundle by exact digest."""
    artifact_dir = _artifact_dir(digest)
    manifest_path = artifact_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceBundleError("source-bundle artifact was not found") from exc
    if manifest.get("digest") != digest:
        raise SourceBundleError("source-bundle manifest identity mismatch")
    for name in ("original.tar", "payload.tar"):
        path = artifact_dir / name
        if path.is_symlink() or not path.is_file():
            raise SourceBundleError("source-bundle artifact payload is missing")
    return manifest


def read_payload(digest: str, expected_payload_digest: str) -> bytes:
    """Load the canonical tar for Docker transport and verify it before use."""
    artifact_dir = _artifact_dir(digest)
    payload_path = artifact_dir / "payload.tar"
    try:
        actual, size = _sha256_file(payload_path)
    except OSError as exc:
        raise SourceBundleError("source-bundle payload could not be read") from exc
    if actual != expected_payload_digest:
        raise SourceBundleError("source-bundle payload integrity check failed")
    if size > config.SOURCE_BUNDLE_MAX_EXPANDED_BYTES + (16 * 1024 * 1024):
        raise SourceBundleTooLarge("canonical source-bundle payload exceeds its bound")
    return payload_path.read_bytes()


def ingest(stream, filename: str | None) -> dict:
    """Stream, validate, normalize, and atomically persist one source bundle."""
    config.SOURCE_BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=".intake-", dir=config.SOURCE_BUNDLES_DIR))
    original_path = work_dir / "original.tar"
    payload_path = work_dir / "payload.tar"
    digest = hashlib.sha256()
    uploaded = 0
    try:
        with original_path.open("xb") as destination:
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                uploaded += len(chunk)
                if uploaded > config.SOURCE_BUNDLE_MAX_UPLOAD_BYTES:
                    raise SourceBundleTooLarge(
                        "source-bundle upload exceeds the configured limit"
                    )
                digest.update(chunk)
                destination.write(chunk)
        if uploaded == 0:
            raise SourceBundleError("source-bundle upload is empty")

        identity = f"sha256:{digest.hexdigest()}"
        artifact_dir = _artifact_dir(identity)
        if artifact_dir.exists():
            return get_artifact(identity)

        archive_meta = _normalize(original_path, payload_path)
        payload_digest, payload_bytes = _sha256_file(payload_path)
        safe_filename = (
            (filename or "source.tar").replace("\\", "/").split("/")[-1][
                :255
            ]
            or "source.tar"
        )
        manifest = {
            "schema": "nidavellir/source-bundle/v1",
            "digest": identity,
            "algorithm": "sha256",
            "filename": safe_filename,
            "upload_bytes": uploaded,
            "payload_digest": payload_digest,
            "payload_bytes": payload_bytes,
            **archive_meta,
        }
        manifest_path = work_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        for path in work_dir.iterdir():
            path.chmod(0o400)

        # Serialize the capacity check and immutable publish across API workers.
        # The archive was already bounded while streaming, so the lock covers
        # only local metadata and an atomic same-filesystem rename.
        lock_path = config.SOURCE_BUNDLES_DIR / ".intake.lock"
        with lock_path.open("a+b") as store_lock:
            fcntl.flock(store_lock.fileno(), fcntl.LOCK_EX)
            if artifact_dir.exists():
                return get_artifact(identity)
            projected = _store_size(exclude=work_dir) + uploaded + payload_bytes
            if projected > config.SOURCE_BUNDLE_STORE_MAX_BYTES:
                raise SourceBundleTooLarge(
                    "source-bundle store has reached its configured capacity"
                )
            artifact_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(work_dir, artifact_dir)
            except OSError:
                if artifact_dir.exists():
                    return get_artifact(identity)
                raise
            artifact_dir.chmod(0o500)
        return manifest
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
