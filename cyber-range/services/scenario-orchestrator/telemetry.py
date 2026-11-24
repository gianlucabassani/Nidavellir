"""OBS-07 (FR-13): platform telemetry shared by the API and the worker.

- **Structured logs.** One logging setup: JSON lines (``NIDAVELLIR_LOG_FORMAT=json``,
  the default) or text, each carrying ``request_id``, ``arena_id``, ``actor`` and
  ``route`` from context variables. The API mints or accepts ``X-Request-ID``
  and returns it; Celery tasks inherit the ID of the request that enqueued them.
- **Metrics.** Prometheus text exposition without a client library. In-process
  HTTP latency lives in this module; worker task durations go to Redis so the
  API's ``/metrics`` can expose them; database-derived families are computed on
  scrape.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from contextvars import ContextVar

REQUEST_ID: ContextVar[str | None] = ContextVar("nv_request_id", default=None)
ARENA_ID: ContextVar[str | None] = ContextVar("nv_arena_id", default=None)
ACTOR: ContextVar[str | None] = ContextVar("nv_actor", default=None)
ROUTE: ContextVar[str | None] = ContextVar("nv_route", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)
TASK_METRICS_KEY = "nv:metrics:task:{}"
TASK_METRICS_INDEX = "nv:metrics:tasks"


# --- logging -----------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": _SERVICE,
        }
        for key, var in (("request_id", REQUEST_ID), ("arena_id", ARENA_ID),
                         ("actor", ACTOR), ("route", ROUTE)):
            value = getattr(record, key, None) or var.get()
            if value:
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class _ContextText(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        rid = REQUEST_ID.get()
        return f"{base} [request_id={rid}]" if rid else base


_SERVICE = "nidavellir"


def configure_logging(service: str, level: int = logging.INFO) -> None:
    """Replace root handlers with one structured handler (idempotent)."""
    global _SERVICE
    _SERVICE = service
    handler = logging.StreamHandler()
    if os.getenv("NIDAVELLIR_LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(_ContextText("%(asctime)s %(name)s %(levelname)s %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True


def accept_request_id(value: str | None) -> str:
    """The caller's ``X-Request-ID`` when well-formed, else a new one."""
    if value and _REQUEST_ID_RE.match(value):
        return value
    return uuid.uuid4().hex


# --- in-process HTTP metrics --------------------------------------------------

_lock = threading.Lock()
_http: dict[tuple[str, str, str], list] = {}  # (route, method, status) -> [buckets, sum, count]


def observe_http(route: str, method: str, status: int, seconds: float) -> None:
    key = (route, method, f"{status // 100}xx")
    with _lock:
        entry = _http.setdefault(key, [[0] * len(BUCKETS), 0.0, 0])
        for i, bound in enumerate(BUCKETS):
            if seconds <= bound:
                entry[0][i] += 1
        entry[1] += seconds
        entry[2] += 1


# --- worker task metrics (Redis) ------------------------------------------------

def record_task(client, task: str, seconds: float, state: str) -> None:
    """Add one task duration to the Redis-held histogram (best-effort)."""
    if client is None:
        return
    try:
        key = TASK_METRICS_KEY.format(task)
        pipe = client.pipeline()
        for bound in BUCKETS:
            if seconds <= bound:
                pipe.hincrby(key, f"le:{bound}", 1)
        pipe.hincrbyfloat(key, "sum", seconds)
        pipe.hincrby(key, "count", 1)
        pipe.hincrby(key, f"state:{state}", 1)
        pipe.sadd(TASK_METRICS_INDEX, task)
        pipe.execute()
    except Exception:  # noqa: BLE001 - metrics never fail a task
        logging.getLogger(__name__).debug("task metric write failed", exc_info=True)


def _task_histograms(client) -> dict[str, dict]:
    if client is None:
        return {}
    try:
        names = sorted(n.decode() if isinstance(n, bytes) else n
                       for n in client.smembers(TASK_METRICS_INDEX))
        out = {}
        for name in names:
            raw = client.hgetall(TASK_METRICS_KEY.format(name))
            out[name] = {(k.decode() if isinstance(k, bytes) else k):
                         float(v) for k, v in raw.items()}
        return out
    except Exception:  # noqa: BLE001
        return {}


# --- exposition -----------------------------------------------------------------

def _labels(**labels) -> str:
    inner = ",".join(f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
                     for k, v in labels.items())
    return "{" + inner + "}" if inner else ""


def _histogram(lines, name, help_text, series):
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} histogram")
    for labels, buckets, total, count in series:
        for bound, value in zip(BUCKETS, buckets):
            lines.append(f"{name}_bucket{_labels(**labels, le=bound)} {int(value)}")
        lines.append(f"{name}_bucket{_labels(**labels, le='+Inf')} {int(count)}")
        lines.append(f"{name}_sum{_labels(**labels)} {total}")
        lines.append(f"{name}_count{_labels(**labels)} {int(count)}")


def render(*, redis_client, arena_states: dict[str, int], budget_refusals: int,
           verdicts: dict[str, int], reaper_actions: dict[str, int],
           queue_depths: dict[str, int]) -> str:
    lines: list[str] = []
    with _lock:
        http = [({"route": r, "method": m, "status": s}, list(e[0]), e[1], e[2])
                for (r, m, s), e in sorted(_http.items())]
    _histogram(lines, "nidavellir_http_request_duration_seconds",
               "API request latency by route template.", http)

    tasks = _task_histograms(redis_client)
    task_series, lifecycle = [], []
    for name, data in tasks.items():
        buckets = [data.get(f"le:{b}", 0) for b in BUCKETS]
        row = (buckets, data.get("sum", 0.0), data.get("count", 0))
        task_series.append(({"task": name}, *row))
        short = name.rsplit(".", 1)[-1]
        if short in ("deploy_lab", "destroy_lab"):
            lifecycle.append(({"operation": short.split("_")[0]}, *row))
    _histogram(lines, "nidavellir_task_duration_seconds", "Celery task duration by task.",
               task_series)
    _histogram(lines, "nidavellir_arena_lifecycle_duration_seconds",
               "Deploy and destroy duration.", lifecycle)

    def gauge(name, help_text, kind, values: dict, label):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        for key, value in sorted(values.items()):
            lines.append(f"{name}{_labels(**{label: key})} {value}")

    gauge("nidavellir_celery_queue_depth", "Messages waiting per Celery queue.", "gauge",
          queue_depths, "queue")
    gauge("nidavellir_arenas", "Arena records by state.", "gauge", arena_states, "state")
    lines.append("# HELP nidavellir_budget_refusals_total Actions refused by the budget gate.")
    lines.append("# TYPE nidavellir_budget_refusals_total counter")
    lines.append(f"nidavellir_budget_refusals_total {budget_refusals}")
    gauge("nidavellir_validator_verdicts_total", "Validator verdicts on findings.", "counter",
          verdicts, "verdict")
    gauge("nidavellir_reaper_actions_total", "Reaper actions by type.", "counter",
          reaper_actions, "action")
    return "\n".join(lines) + "\n"
