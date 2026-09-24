"""Operator-only content-addressed observations for deterministic validation."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import config

ROOT = config.DATA_DIR / "validation-evidence"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_BYTES = 16384


class ValidationEvidenceError(ValueError):
    pass


def _path(arena_id: str, digest: str) -> Path:
    if not _DIGEST.fullmatch(digest):
        raise ValidationEvidenceError("invalid validation evidence digest")
    arena_key = hashlib.sha256(arena_id.encode()).hexdigest()
    return ROOT / arena_key / (digest.removeprefix("sha256:") + ".json")


def record(arena_id: str, payload: dict) -> str:
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode()
    if len(content) > _MAX_BYTES:
        raise ValidationEvidenceError("validation evidence exceeds size limit")
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    path = _path(arena_id, digest)
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / ".store.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if path.exists():
            if path.read_bytes() != content:
                raise ValidationEvidenceError("validation evidence integrity mismatch")
            return digest
        used = sum(item.stat().st_size for item in ROOT.rglob("*.json") if item.is_file())
        if used + len(content) > config.EVIDENCE_ARTIFACT_STORE_MAX_BYTES:
            raise ValidationEvidenceError("validation evidence store has reached its capacity")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(content)
            temp = Path(handle.name)
        try:
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return digest


def get(arena_id: str, digest: str) -> dict:
    path = _path(arena_id, digest)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ValidationEvidenceError("validation evidence not found") from exc
    if "sha256:" + hashlib.sha256(content).hexdigest() != digest:
        raise ValidationEvidenceError("validation evidence integrity mismatch")
    try:
        return json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationEvidenceError("validation evidence invalid") from exc
