"""OBS-07 (FR-13, FR-37): optional OTLP export of spans, off by default.

Set ``OTEL_EXPORTER_OTLP_ENDPOINT`` (e.g. ``http://otel-collector:4318``) and
every stored span is also sent, batched, to ``<endpoint>/v1/traces`` as OTLP/HTTP
JSON. Previews are already redacted at write time (ADR-0018). Export runs on a
background thread with a bounded queue: it never blocks or fails a write, and
drops spans rather than grow without bound.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_QUEUE_MAX = 10000
_BATCH = 200
_queue: queue.Queue | None = None
_lock = threading.Lock()
_STATUS = {"ok": 1, "error": 2, "denied": 2, "budget_refused": 2}
_KIND = {"tool": 1, "agent": 1, "model": 3, "lifecycle": 1, "validation": 1}  # INTERNAL/CLIENT


def endpoint() -> str | None:
    value = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
    return value or None


def _nanos(value) -> str:
    if value is None:
        return "0"
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace(" ", "T"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return str(int(value.timestamp() * 1_000_000_000))


def _attr(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def to_otlp(row: dict) -> dict:
    """One stored span row as an OTLP JSON span."""
    import json  # noqa: PLC0415

    attrs = row.get("attrs")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            attrs = {}
    attributes = [_attr(k, v) for k, v in (attrs or {}).items() if v is not None]
    for key in ("arena_id", "trial_id", "evaluation_id", "actor", "actor_kind", "stance",
                "kind", "visibility", "input_digest", "output_digest", "error_class"):
        if row.get(key) is not None:
            attributes.append(_attr(f"nv.{key}", row[key]))
    span = {
        "traceId": row["trace_id"], "spanId": row["span_id"], "name": row["name"],
        "kind": _KIND.get(row.get("kind"), 1),
        "startTimeUnixNano": _nanos(row.get("started_at")),
        "endTimeUnixNano": _nanos(row.get("ended_at") or row.get("started_at")),
        "attributes": attributes,
        "status": {"code": _STATUS.get(row.get("status"), 0),
                   **({"message": row["status"]} if row.get("status") != "ok" else {})},
    }
    if row.get("parent_span_id"):
        span["parentSpanId"] = row["parent_span_id"]
    return span


def payload(rows: list[dict]) -> dict:
    return {"resourceSpans": [{
        "resource": {"attributes": [_attr("service.name", "nidavellir")]},
        "scopeSpans": [{"scope": {"name": "nidavellir.spans"},
                        "spans": [to_otlp(r) for r in rows]}],
    }]}


def export(row: dict) -> None:
    """Queue one span for export; a no-op unless an endpoint is configured."""
    if endpoint() is None:
        return
    global _queue
    with _lock:
        if _queue is None:
            _queue = queue.Queue(maxsize=_QUEUE_MAX)
            threading.Thread(target=_run, name="otlp-export", daemon=True).start()
    try:
        _queue.put_nowait(dict(row))
    except queue.Full:
        logger.warning("OTLP export queue full; dropping a span")


def _run() -> None:
    import requests  # noqa: PLC0415

    while True:
        batch = [_queue.get()]
        while len(batch) < _BATCH:
            try:
                batch.append(_queue.get(timeout=0.5))
            except queue.Empty:
                break
        target = endpoint()
        if target is None:
            continue
        try:
            requests.post(f"{target}/v1/traces", json=payload(batch), timeout=5)
        except Exception as exc:  # noqa: BLE001 - export is optional
            logger.warning("OTLP export failed: %s", type(exc).__name__)


def flush(timeout: float = 5.0) -> None:
    """Wait until queued spans are handed to the exporter (tests, shutdown)."""
    import time  # noqa: PLC0415

    deadline = time.monotonic() + timeout
    while _queue is not None and not _queue.empty() and time.monotonic() < deadline:
        time.sleep(0.05)
