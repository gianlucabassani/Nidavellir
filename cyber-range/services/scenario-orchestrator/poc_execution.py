"""Pure contracts for durable confined PoC jobs (NV-03 / ADR-0014)."""
import base64
import hashlib
import json
from pathlib import PurePosixPath

import config

TERMINAL_STATES = frozenset({"succeeded", "failed", "timed_out", "cancelled"})
ACTIVE_STATES = frozenset({"queued", "running"})


def safe_relative_path(raw: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("input file path is invalid")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("input file path must stay below /workspace/input")
    if len(path.parts) > 16 or len(str(path).encode("utf-8")) > 512:
        raise ValueError("input file path exceeds the configured limit")
    return str(path)


def canonical_payload(source: str, files: list[dict]) -> tuple[dict, str]:
    try:
        source_bytes = source.encode("utf-8")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise ValueError("source must be UTF-8 text") from exc
    if not source_bytes or len(source_bytes) > config.POC_MAX_SOURCE_BYTES:
        raise ValueError("source exceeds the configured UTF-8 byte limit")
    normalized = []
    total = 0
    for item in files:
        path = safe_relative_path(item["path"])
        data = item["content"]
        if not isinstance(data, bytes):
            raise ValueError("input file content must be bytes")
        total += len(data)
        if total > config.POC_MAX_TRANSFER_BYTES:
            raise ValueError("selected transfer files exceed the aggregate limit")
        normalized.append({
            "path": path,
            "content_b64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data),
            "sha256": f"sha256:{hashlib.sha256(data).hexdigest()}",
        })
    if len(normalized) > config.POC_MAX_TRANSFER_FILES:
        raise ValueError("too many selected transfer files")
    normalized.sort(key=lambda value: value["path"])
    payload = {"schema": "nidavellir.poc-input/v1", "source": source, "files": normalized}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return payload, f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def public_job(job: dict, *, include_result: bool = False) -> dict:
    keys = (
        "id", "arena_id", "principal", "principal_role", "binding_stance", "input_digest",
        "runner_image", "runner_image_id", "target_node", "target_policy",
        "limits", "deadline", "state", "cancel_requested", "cleanup_state",
        "cleanup_error", "created_at", "updated_at", "started_at", "completed_at",
    )
    view = {key: job.get(key) for key in keys}
    if include_result:
        view["result"] = job.get("result")
    return view
