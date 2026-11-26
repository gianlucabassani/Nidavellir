"""UX-14 (FR-19): one operator snapshot of the platform's health.

Read-only: dependency readiness, the Celery queue depth, the worker heartbeat,
running helpers, labelled Docker resources against this installation's
arenas, store sizes, the database's migration revision and the last backup.
Every probe degrades to a short reason instead of failing the page; no
connection strings or credentials are returned.

Orphans. Several installations can share one Docker daemon (a test stack next
to production), and a resource label names only the arena id. So a resource
whose arena this installation does not know is listed but never offered for
reclaim: it may be another installation's live arena. Only leftovers of an
arena this installation destroyed (or one that failed) can be reclaimed.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import config
from states import LabStatus

LABEL_LAB_ID = "nidavellir.lab_id"
LIVE = {LabStatus.PENDING, LabStatus.DEPLOYING, LabStatus.ACTIVE, LabStatus.DESTROYING}
FAILED = {LabStatus.FAILED, LabStatus.ERROR_DESTROYING}
STORE_FILE_LIMIT = 200_000
_STORE_CACHE: dict[str, tuple[float, dict]] = {}
STORE_CACHE_SECONDS = 30


def stores() -> list[tuple[str, Path]]:
    return [
        ("Evidence artifacts", config.EVIDENCE_ARTIFACTS_DIR),
        ("HTTP transactions", config.HTTP_TRANSACTIONS_DIR),
        ("Source bundles", config.SOURCE_BUNDLES_DIR),
        ("Imported scenarios", config.SCENARIOS_DIR),
        ("Run records", config.RUNS_DIR),
    ]


def dir_usage(path: Path, *, now: float | None = None) -> dict:
    """Bytes and files below ``path``, bounded and cached briefly."""
    now = time.monotonic() if now is None else now
    cached = _STORE_CACHE.get(str(path))
    if cached and now - cached[0] < STORE_CACHE_SECONDS:
        return cached[1]
    if not path.exists():
        result = {"bytes": 0, "files": 0, "present": False, "truncated": False}
    else:
        total = files = 0
        truncated = False
        stack = [path]
        while stack and not truncated:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                                files += 1
                                if files >= STORE_FILE_LIMIT:
                                    truncated = True
                                    break
                        except OSError:
                            continue
            except OSError:
                continue
        result = {"bytes": total, "files": files, "present": True, "truncated": truncated}
    _STORE_CACHE[str(path)] = (now, result)
    return result


def database_size(engine) -> int | None:
    from sqlalchemy import text  # noqa: PLC0415

    try:
        if engine.dialect.name == "postgresql":
            with engine.connect() as conn:
                return int(conn.execute(text("SELECT pg_database_size(current_database())")).scalar())
        database = engine.url.database
        return Path(database).stat().st_size if database else None
    except Exception:  # noqa: BLE001 - size is informative only
        return None


def migration(engine) -> dict:
    import migrate  # noqa: PLC0415

    try:
        current = migrate.current_revision(engine)
    except Exception as exc:  # noqa: BLE001
        return {"current": None, "head": None, "error": type(exc).__name__}
    try:
        head = migrate.head_revision()
    except Exception:  # noqa: BLE001
        head = None
    return {"current": current, "head": head, "up_to_date": bool(current) and current == head}


def backup(now: float | None = None) -> dict:
    """The newest entry of ``NIDAVELLIR_BACKUP_DIR`` when it is mounted.

    Backups are taken on the host (scripts/backup.sh); the platform sees them
    only if their directory is mounted read-only and named here."""
    raw = os.getenv("NIDAVELLIR_BACKUP_DIR", "").strip()
    if not raw:
        return {"configured": False}
    root = Path(raw)
    try:
        entries = [entry for entry in root.iterdir() if not entry.name.startswith(".")]
    except OSError as exc:
        return {"configured": True, "error": type(exc).__name__}
    if not entries:
        return {"configured": True, "latest": None}
    newest = max(entries, key=lambda entry: entry.stat().st_mtime)
    mtime = newest.stat().st_mtime
    return {"configured": True, "latest": newest.name,
            "age_seconds": int((time.time() if now is None else now) - mtime), "count": len(entries)}


def heartbeat(client, now: float | None = None) -> dict:
    import readiness  # noqa: PLC0415

    try:
        raw = client.get(readiness.HEARTBEAT_KEY)
    except Exception as exc:  # noqa: BLE001
        return {"alive": False, "reason": f"unavailable ({type(exc).__name__})"}
    if raw is None:
        return {"alive": False, "reason": "no heartbeat",
                "max_age_seconds": readiness.HEARTBEAT_MAX_AGE_SECONDS}
    age = max(0.0, (time.time() if now is None else now) - float(raw))
    return {"alive": age <= readiness.HEARTBEAT_MAX_AGE_SECONDS, "age_seconds": round(age, 1),
            "max_age_seconds": readiness.HEARTBEAT_MAX_AGE_SECONDS}


def classify(lab_id: str, record: dict | None) -> tuple[str, str | None]:
    """(state, reclaim path) for resources labelled with ``lab_id``."""
    if record is None:
        return "unknown", None
    status = record.get("status")
    if status in LIVE:
        return "live", None
    if status == LabStatus.DESTROYED:
        return "leftover", "reclaim_orphan"
    if status in FAILED:
        return "failed", "destroy_lab"
    return "live", None


def docker_inventory(client, records: dict[str, dict]) -> dict:
    """Labelled Docker resources grouped by arena, each classified."""
    flt = {"label": LABEL_LAB_ID}
    groups: dict[str, dict] = {}

    def group(lab_id):
        return groups.setdefault(lab_id, {"lab_id": lab_id, "containers": [], "networks": 0,
                                          "volumes": 0, "images": 0})

    try:
        for container in client.containers.list(all=True, filters=flt):
            labels = container.labels or {}
            group(labels.get(LABEL_LAB_ID, ""))["containers"].append({
                "name": container.name, "status": container.status,
                "role": labels.get("nidavellir.role"), "node": labels.get("nidavellir.node")})
        for kind, listing in (("networks", client.networks.list(filters=flt)),
                              ("volumes", client.volumes.list(filters=flt)),
                              ("images", client.images.list(filters=flt))):
            for item in listing:
                labels = getattr(item, "attrs", {}).get("Labels") if kind == "volumes" \
                    else getattr(item, "labels", None)
                lab_id = (labels or {}).get(LABEL_LAB_ID)
                if lab_id:
                    group(lab_id)[kind] += 1
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"unavailable ({type(exc).__name__})", "arenas": []}
    arenas = []
    for lab_id, entry in sorted(groups.items()):
        record = records.get(lab_id)
        state, path = classify(lab_id, record)
        arenas.append({**entry, "state": state, "reclaim": path,
                       "arena_name": (record or {}).get("user_id"),
                       "arena_status": (record or {}).get("status")})
    return {"available": True, "arenas": arenas,
            "orphans": sum(1 for a in arenas if a["state"] in ("leftover", "failed")),
            "unknown": sum(1 for a in arenas if a["state"] == "unknown")}
