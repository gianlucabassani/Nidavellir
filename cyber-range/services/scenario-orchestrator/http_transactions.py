"""Arena HTTP transaction store (ROADMAP R1 slice 3).

Every `http_request` primitive transaction is persisted as one canonical
request+response envelope, content-addressed by the SHA-256 of its exact
bytes. The store follows the evidence-artifact discipline (ADR-0011): bodies
live outside the event stream, records are arena-scoped and integrity-checked,
and they outlive the arena so a destroyed engagement stays reviewable.

Identical re-sends hash to the same envelope and dedup onto one record; a
replay (slice 4) hashes differently and links to its parent via `replay_of`.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import config

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class HttpTransactionError(ValueError):
    """A transaction record is invalid, missing, or outside its arena scope."""


def _arena_dir(arena_id: str) -> Path:
    key = hashlib.sha256(arena_id.encode("utf-8")).hexdigest()
    return config.HTTP_TRANSACTIONS_DIR / key


def _paths(arena_id: str, digest: str) -> tuple[Path, Path]:
    if not _DIGEST_RE.fullmatch(digest):
        raise HttpTransactionError("invalid transaction digest")
    root = _arena_dir(arena_id) / digest.removeprefix("sha256:")
    return root / "transaction.json", root / "manifest.json"


def _canonical(envelope: dict) -> bytes:
    return json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _store_size() -> int:
    root = config.HTTP_TRANSACTIONS_DIR
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def record(
    arena_id: str,
    *,
    request: dict,
    response: dict,
    replay_of: str | None = None,
    actor: str | None = None,
    elapsed_ms: int | None = None,
) -> dict:
    """Persist one transaction atomically and return its public manifest.

    The digest covers ONLY the deterministic envelope (request + response), so
    an identical re-send is an idempotent no-op while any edit — including a
    slice-4 replay modification — produces a new linked record.
    """
    envelope = {"schema": "nidavellir/http-transaction/v1", "request": request, "response": response}
    try:
        payload = _canonical(envelope)
    except (TypeError, ValueError) as exc:
        raise HttpTransactionError("transaction is not JSON-serializable") from exc
    if len(payload) > config.HTTP_TRANSACTION_MAX_BYTES:
        raise HttpTransactionError("transaction exceeds the configured limit")
    if replay_of is not None and not _DIGEST_RE.fullmatch(replay_of):
        raise HttpTransactionError("invalid replay parent digest")
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    payload_path, manifest_path = _paths(arena_id, digest)

    config.HTTP_TRANSACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = config.HTTP_TRANSACTIONS_DIR / ".store.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if payload_path.exists() and manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if payload_path.read_bytes() != payload:
                raise HttpTransactionError("transaction integrity mismatch")
            return existing
        if _store_size() + len(payload) > config.HTTP_TRANSACTION_STORE_MAX_BYTES:
            raise HttpTransactionError("transaction store has reached its capacity")

        public = {
            "schema": "nidavellir/http-transaction/v1",
            "kind": "http_transaction",
            "digest": digest,
            "bytes": len(payload),
            "media_type": "application/json",
            "arena_id": arena_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "elapsed_ms": elapsed_ms,
            "replay_of": replay_of,
        }
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=payload_path.parent, delete=False) as handle:
            handle.write(payload)
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


def get(arena_id: str, digest: str) -> tuple[dict, dict]:
    """Load and verify one transaction within one arena's namespace."""
    payload_path, manifest_path = _paths(arena_id, digest)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        content = payload_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise HttpTransactionError("http transaction was not found") from exc
    actual = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if actual != digest or manifest.get("digest") != digest:
        raise HttpTransactionError("http transaction integrity check failed")
    if manifest.get("arena_id") != arena_id:
        raise HttpTransactionError("http transaction is outside this arena")
    envelope = json.loads(content.decode("utf-8"))
    return manifest, envelope


def list_transactions(
    arena_id: str, *, limit: int | None = None, offset: int = 0
) -> dict:
    """List one arena's transactions, newest first, bounded."""
    limit = min(limit or config.HTTP_TRANSACTIONS_LIST_LIMIT, 500)
    root = _arena_dir(arena_id)
    manifests: list[dict] = []
    if root.exists():
        for manifest_path in root.glob("*/manifest.json"):
            try:
                manifests.append(
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue  # a torn/partial write must never break listing
    manifests.sort(key=lambda m: (m.get("created_at") or "", m.get("digest") or ""))
    manifests.reverse()  # newest first
    total = len(manifests)
    window = manifests[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "transactions": window}
