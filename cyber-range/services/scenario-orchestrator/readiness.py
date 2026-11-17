"""FR-07 (B12): liveness vs readiness.

``/health`` stays a liveness probe (the process answers). ``/ready`` is 200 only
when the dependencies a request needs answer: the database, Redis (the Celery
broker) and — for the real docker-local provider outside mock mode — a worker
that has heart-beaten recently.

The worker heartbeat is a Redis key written by a daemon thread in the Celery
*main* process (started on ``worker_ready``). It therefore proves a live worker
process, not an idle queue: a single-concurrency worker busy with an hour-long
evaluation is still ready. The key carries a TTL so a dead worker expires it.
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "nidavellir:worker:heartbeat"
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("NIDAVELLIR_WORKER_HEARTBEAT_SECONDS", "15"))
# A heartbeat older than this means no worker: three missed beats.
HEARTBEAT_MAX_AGE_SECONDS = int(
    os.getenv("NIDAVELLIR_WORKER_HEARTBEAT_MAX_AGE_SECONDS", str(HEARTBEAT_INTERVAL_SECONDS * 3))
)
REDIS_TIMEOUT_SECONDS = 2.0


def redis_client(url: str | None = None):
    import redis  # noqa: PLC0415 - optional at import time for the mock demo

    url = url or os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, socket_timeout=REDIS_TIMEOUT_SECONDS,
                                socket_connect_timeout=REDIS_TIMEOUT_SECONDS)


def write_heartbeat(client, now: float | None = None) -> None:
    client.set(HEARTBEAT_KEY, f"{time.time() if now is None else now:.3f}",
               ex=HEARTBEAT_MAX_AGE_SECONDS)


def start_heartbeat_thread(client_factory=redis_client) -> threading.Thread:
    """Beat forever from a daemon thread; Redis errors are logged, not fatal."""

    def _loop():
        client = client_factory()
        while True:
            try:
                write_heartbeat(client)
            except Exception as exc:  # noqa: BLE001 - keep beating through blips
                logger.warning("worker heartbeat failed: %s", exc)
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)

    thread = threading.Thread(target=_loop, name="nidavellir-heartbeat", daemon=True)
    thread.start()
    return thread


def heartbeat_required(provider_name: str, mock_mode: bool) -> bool:
    return provider_name == "docker-local" and not mock_mode


def check_readiness(db_ping, redis_factory, *, require_worker: bool,
                    now: float | None = None) -> tuple[bool, dict]:
    """Return ``(ready, checks)``; each check is ``"ok"`` or a short reason.

    Reasons never include connection strings or credentials.
    """
    checks: dict[str, str] = {}
    try:
        db_ping()
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"unavailable ({type(exc).__name__})"
    client = None
    try:
        client = redis_factory()
        client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        client = None
        checks["redis"] = f"unavailable ({type(exc).__name__})"
    if require_worker:
        if client is None:
            checks["worker"] = "unknown (redis unavailable)"
        else:
            try:
                raw = client.get(HEARTBEAT_KEY)
                age = None if raw is None else (time.time() if now is None else now) - float(raw)
                if age is None:
                    checks["worker"] = "no heartbeat"
                elif age > HEARTBEAT_MAX_AGE_SECONDS:
                    checks["worker"] = f"stale heartbeat ({int(age)}s)"
                else:
                    checks["worker"] = "ok"
            except Exception as exc:  # noqa: BLE001
                checks["worker"] = f"unavailable ({type(exc).__name__})"
    return all(v == "ok" for v in checks.values()), checks
