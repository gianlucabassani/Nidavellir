"""Arena-scoped, content-addressed research evidence (ROADMAP M4-A).

Evidence bodies can contain source, secrets, and exploit material. They are
therefore kept out of the append-only event stream: events and findings store a
digest reference plus public metadata, while this module owns the bounded body.
"""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path

import config

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class EvidenceArtifactError(ValueError):
    """An artifact is invalid, missing, or outside its arena scope."""


def _arena_dir(arena_id: str) -> Path:
    key = hashlib.sha256(arena_id.encode("utf-8")).hexdigest()
    return config.EVIDENCE_ARTIFACTS_DIR / key


def _paths(arena_id: str, digest: str) -> tuple[Path, Path]:
    if not _DIGEST_RE.fullmatch(digest):
        raise EvidenceArtifactError("invalid evidence artifact digest")
    root = _arena_dir(arena_id) / digest.removeprefix("sha256:")
    return root / "artifact.patch", root / "manifest.json"


def _store_size() -> int:
    root = config.EVIDENCE_ARTIFACTS_DIR
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def store_patch(arena_id: str, content: bytes, metadata: dict) -> dict:
    """Persist one canonical patch atomically and return its public reference."""
    if not content:
        raise EvidenceArtifactError("cannot export an empty patch artifact")
    if len(content) > config.EVIDENCE_ARTIFACT_MAX_BYTES:
        raise EvidenceArtifactError("patch artifact exceeds the configured limit")
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    payload_path, manifest_path = _paths(arena_id, digest)
    public = {
        **metadata,
        "schema": "nidavellir/evidence-patch/v1",
        "digest": digest,
        "kind": "workspace_patch",
        "media_type": "text/x-diff; charset=utf-8",
        "bytes": len(content),
        "arena_id": arena_id,
    }
    config.EVIDENCE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = config.EVIDENCE_ARTIFACTS_DIR / ".store.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if payload_path.exists() and manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if payload_path.read_bytes() != content:
                raise EvidenceArtifactError("evidence artifact integrity mismatch")
            return existing
        if _store_size() + len(content) > config.EVIDENCE_ARTIFACT_STORE_MAX_BYTES:
            raise EvidenceArtifactError("evidence artifact store has reached its capacity")

        payload_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=payload_path.parent, delete=False) as handle:
            handle.write(content)
            tmp_payload = Path(handle.name)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=payload_path.parent, delete=False
        ) as handle:
            json.dump(public, handle, sort_keys=True, separators=(",", ":"))
            tmp_manifest = Path(handle.name)
        try:
            os.replace(tmp_payload, payload_path)
            os.replace(tmp_manifest, manifest_path)
        finally:
            tmp_payload.unlink(missing_ok=True)
            tmp_manifest.unlink(missing_ok=True)
    return public


def get(arena_id: str, digest: str) -> tuple[dict, bytes]:
    """Load and verify an artifact within one arena's namespace."""
    payload_path, manifest_path = _paths(arena_id, digest)
    try:
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        content = payload_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise EvidenceArtifactError("evidence artifact was not found") from exc
    actual = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if actual != digest or metadata.get("digest") != digest:
        raise EvidenceArtifactError("evidence artifact integrity check failed")
    if metadata.get("arena_id") != arena_id:
        raise EvidenceArtifactError("evidence artifact is outside this arena")
    return metadata, content
