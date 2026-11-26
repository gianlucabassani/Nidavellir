"""Activity summaries for the console dashboards (UX-17).

``summarize`` folds spans (ADR-0018) into fixed time buckets by action family,
with failures, refusals, submitted findings and budget spend per bucket, plus
totals per family and per actor and action-time statistics. It reads only what
the span already records; nothing here is estimated. Routes are operator-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

FAMILIES = ("http", "exec", "model", "other")
# Span kinds that are actions taken in the arena. Lifecycle and validation are
# the platform's own work and are not counted as activity.
ACTION_KINDS = ("tool", "model")
FINDING_NAMES = frozenset({"findings", "findings/manual"})
REFUSED = frozenset({"budget_refused", "denied"})
# Bucket widths in seconds; the smallest that fits the window in ``max_buckets``.
_STEPS = (10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 21600, 43200, 86400)


def family(kind: str, name: str) -> str:
    if kind == "model":
        return "model"
    if name.startswith("http/"):
        return "http"
    if name == "exec" or name.startswith("exec/"):
        return "exec"
    return "other"


def bucket_seconds(window_seconds: float, max_buckets: int) -> int:
    for step in _STEPS:
        if window_seconds / step <= max_buckets:
            return step
    return _STEPS[-1]


def _budget_outcome(attrs) -> str | None:
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs) if attrs else {}
        except ValueError:
            return None
    return attrs.get("nv.budget_outcome") if isinstance(attrs, dict) else None


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def summarize(rows, *, start: datetime, end: datetime, max_buckets: int = 24) -> dict:
    """``rows``: iterables of (kind, name, status, actor, arena_id, started_at,
    duration_ms, attrs) for spans of ACTION_KINDS, any order."""
    if end <= start:
        end = start + timedelta(seconds=1)
    step = bucket_seconds((end - start).total_seconds(), max_buckets)
    count = max(1, int(-(-(end - start).total_seconds() // step)))
    buckets = [{"start": (start + timedelta(seconds=i * step)).isoformat(sep=" "),
                **{f: 0 for f in FAMILIES}, "failed": 0, "refused": 0,
                "findings": 0, "spent": 0} for i in range(count)]
    totals = {f: 0 for f in FAMILIES}
    failed = {f: 0 for f in FAMILIES}
    refused = 0
    actors: dict[tuple[str, str | None], dict] = {}
    durations: list[int] = []
    slowest = None
    for kind, name, status, actor, arena_id, started_at, duration_ms, attrs in rows:
        if started_at < start or started_at > end:
            continue
        index = min(count - 1, int((started_at - start).total_seconds() // step))
        bucket = buckets[index]
        fam = family(kind, name)
        entry = actors.setdefault((actor, arena_id), {
            "actor": actor, "arena_id": arena_id, "actions": 0, "model_calls": 0,
            "failed": 0, "refused": 0})
        if status in REFUSED:
            bucket["refused"] += 1
            refused += 1
            entry["refused"] += 1
            continue
        bucket[fam] += 1
        totals[fam] += 1
        if fam == "model":
            entry["model_calls"] += 1
        else:
            entry["actions"] += 1
        if status == "error":
            bucket["failed"] += 1
            failed[fam] += 1
            entry["failed"] += 1
        if name in FINDING_NAMES and status == "ok":
            bucket["findings"] += 1
        if _budget_outcome(attrs) == "spent":
            bucket["spent"] += 1
        if kind == "tool" and duration_ms is not None:
            durations.append(int(duration_ms))
            if slowest is None or duration_ms > slowest["ms"]:
                slowest = {"name": name, "ms": int(duration_ms)}
    return {
        "start": start.isoformat(sep=" "),
        "end": end.isoformat(sep=" "),
        "bucket_seconds": step,
        "buckets": buckets,
        "totals": {"by_family": totals, "failed_by_family": failed,
                   "actions": sum(totals.values()), "failed": sum(failed.values()),
                   "refused": refused},
        "by_actor": sorted(actors.values(),
                           key=lambda a: (-(a["actions"] + a["model_calls"]), a["actor"])),
        "durations": {"median_ms": _median(durations), "slowest": slowest},
    }
