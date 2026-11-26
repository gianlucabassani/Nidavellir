"""UX-27/28: the run folded on the server for the Timeline page.

The console no longer draws one mark per span. It draws the shape of the
run: the agent's cycles on the trunk, the routes it pursued as branches
(split into episodes when a route goes quiet), failed calls as clustered
marks, and findings as fruit. This module folds the arena's spans into that
compact model; the steps of one route are read separately, on demand.

Routes: a declared hypothesis (``hypothesis_id`` on a call) or else an HTTP
path prefix. Self-reported gateway calls that duplicate an enforced call are
folded into it. An episode is a run of a route's steps without a gap of
EPISODE_GAP seconds; an episode with fewer than MIN_STEPS steps and no
outcome stays on the trunk, so sporadic housekeeping never draws a branch
across the whole run.

UX-28 draws the run against its time budget: ``clock`` places the arena's
start and deadline on the run's own seconds, and the model adds the agent's
verdicts, a flat list of failed calls, the tool mix and activity buckets.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime

EPISODE_GAP = 600
MIN_STEPS = 3
BACKGROUND_WRAPS = 2
TWIN_SECONDS = 3.0
MAX_ERRORS = 200
MAX_FAILURES = 500
FINDING_NAMES = {"findings", "findings/manual", "report_finding"}
CYCLE_NAMES = {"announce_agent"}

_HYP = re.compile(r'"hypothesis_id"\s*:\s*"([^"]{1,64})"')
_DECLARED = re.compile(r'"contract"\s*:\s*\{[\s\S]*?"id"\s*:\s*"([^"]{1,64})"')
_CLAIMS = [re.compile(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.){{1,240}})')
           for field in ("title", "invariant", "expected_observable")]
_PATH = re.compile(r'"path"\s*:\s*"([^"]{1,512})"')
_OUTCOME = re.compile(r'"outcome"\s*:\s*"([^"]{1,32})"')
_FINDING_IDS = re.compile(r'"finding_ids"\s*:\s*\[([^\]]*)\]')
_METHOD = re.compile(r'"method"\s*:\s*"([A-Z]{3,10})"')
_COMMAND = re.compile(r'"(?:command|cmd)"\s*:\s*"((?:[^"\\]|\\.){1,160})')


def _ts(value) -> float:
    if isinstance(value, datetime):
        return value.timestamp() if value.tzinfo else value.replace(tzinfo=None).timestamp()
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "")).timestamp()
    except ValueError:
        return 0.0


def _family(name: str, kind: str) -> str:
    if kind == "model":
        return "model"
    if name.startswith("http/") or name == "http_request":
        return "http"
    if name in ("exec", "run_command") or name.startswith("exec/"):
        return "exec"
    return "other"


def _self(row: dict) -> bool:
    attrs = row.get("attrs") or {}
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            attrs = {}
    return attrs.get("nv.self_reported") is True


def _unescape(text: str) -> str:
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        return text


def target(row: dict) -> str:
    """A one-line description of what a step did."""
    preview = row.get("input_preview") or ""
    if _family(row.get("name") or "", row.get("kind") or "") == "http":
        method = (_METHOD.search(preview) or [None, ""])[1]
        path = (_PATH.search(preview) or [None, ""])[1]
        return f"{method} {path}".strip() or row.get("name") or ""
    command = _COMMAND.search(preview)
    if command:
        return "$ " + _unescape(command.group(1))
    name = row.get("name") or ""
    if name in FINDING_NAMES:
        title = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.){1,160})', preview)
        return "Finding: " + _unescape(title.group(1)) if title else "Finding submitted"
    if name == "register_hypothesis":
        declared = _DECLARED.search(preview)
        return f"Declared {declared.group(1)}" if declared else name
    if name == "mark_hypothesis_tested":
        outcome = _OUTCOME.search(preview)
        return f"Marked tested: {outcome.group(1)}" if outcome else name
    return name


def _route_key(row: dict) -> str | None:
    preview = row.get("input_preview") or ""
    name = row.get("name") or ""
    if name == "register_hypothesis":
        match = _DECLARED.search(preview)
        return f"h:{match.group(1)}" if match else None
    match = _HYP.search(preview)
    if match:
        return f"h:{match.group(1)}"
    if _family(name, row.get("kind") or "") == "http":
        path = _PATH.search(preview)
        if path:
            parts = [p for p in path.group(1).split("?")[0].split("#")[0].split("/") if p]
            return "p:/" + "/".join(parts[:2])
    return None


def fold(rows: list[dict]) -> list[dict]:
    """Drop self-reported twins of enforced calls; attach time, route, family."""
    steps = []
    for row in rows:
        at = _ts(row.get("started_at"))
        end = _ts(row.get("ended_at")) or at + (row.get("duration_ms") or 0) / 1000
        steps.append({**row, "at": at, "end": max(end, at), "key": _route_key(row),
                      "family": _family(row.get("name") or "", row.get("kind") or ""),
                      "self": _self(row)})
    enforced: dict[tuple, list[float]] = defaultdict(list)
    for step in steps:
        if not step["self"]:
            enforced[(step["actor"], step["key"], step["family"],
                      step["name"] in FINDING_NAMES)].append(step["at"])
    out = []
    for step in steps:
        if step["self"]:
            times = enforced.get((step["actor"], step["key"], step["family"],
                                  step["name"] in FINDING_NAMES), [])
            if any(abs(t - step["at"]) <= TWIN_SECONDS for t in times):
                continue
        out.append(step)
    return out


def build(rows: list[dict], *, findings: list[dict], tested: list[dict],
          started_at, now, live: bool, truncated: bool = False,
          deadline=None, deadline_source: str | None = None) -> dict:
    """The compact run model. ``findings``: finding event payloads with ts;
    ``tested``: hypothesis_tested payloads (outcomes and finding links, with
    ts when known). ``deadline``: the end of the run's time budget (UX-28)."""
    steps = fold(rows)
    t0 = min([_ts(started_at)] + [s["at"] for s in steps if s["at"]]) if steps else _ts(started_at)
    end = max([s["end"] for s in steps] + [_ts(now) if live else 0, t0])

    def rel(t):
        return round(max(0.0, t - t0), 1)

    claims: dict[str, str] = {}
    linked: dict[str, str] = {}
    outcomes: dict[str, str] = {}
    by_key: dict[str, list[dict]] = defaultdict(list)
    verdicts: list[dict] = []
    for step in steps:
        key = step["key"]
        if step["name"] == "register_hypothesis" and key:
            preview = step.get("input_preview") or ""
            claim = next((m for m in (p.search(preview) for p in _CLAIMS) if m), None)
            if claim:
                claims.setdefault(key, _unescape(claim.group(1)))
        if step["name"] == "mark_hypothesis_tested" and key:
            outcome = _OUTCOME.search(step.get("input_preview") or "")
            if outcome:
                outcomes[key] = outcome.group(1)
            ids = _FINDING_IDS.search(step.get("input_preview") or "")
            fids = re.findall(r'"([\w.-]{1,64})"', ids.group(1) if ids else "")
            for fid in fids:
                linked.setdefault(fid, key)
            verdicts.append({"at": step["at"], "id": key[2:],
                             "outcome": outcome.group(1) if outcome else None, "findings": fids})
        if key:
            by_key[key].append(step)
    marked = {v["id"] for v in verdicts}
    for record in tested:
        if record.get("hypothesis_id") and record.get("outcome"):
            outcomes.setdefault(f"h:{record['hypothesis_id']}", record["outcome"])
            if record["hypothesis_id"] not in marked and _ts(record.get("ts")):
                verdicts.append({"at": _ts(record.get("ts")), "id": record["hypothesis_id"],
                                 "outcome": record["outcome"],
                                 "findings": list(record.get("finding_ids") or [])})
    finding_route: dict[str, str] = dict(linked)
    for record in tested:
        for fid in record.get("finding_ids") or []:
            finding_route[fid] = f"h:{record.get('hypothesis_id')}"
    # Path routes need a few steps to be a route at all.
    for key in [k for k, v in by_key.items() if k.startswith("p:") and len(v) < MIN_STEPS]:
        for step in by_key.pop(key):
            step["key"] = None

    found = []
    for item in findings:
        at = _ts(item.get("ts"))
        route = finding_route.get(item.get("finding_id"))
        if not route:
            near = [s for s in steps if s["name"] in FINDING_NAMES and s["key"]
                    and abs(s["at"] - at) <= 30]
            route = near[0]["key"] if near else None
        dedup = item.get("dedup") if isinstance(item.get("dedup"), dict) else {}
        found.append({"id": item.get("finding_id"), "title": item.get("title") or "Finding",
                      "severity": item.get("severity"), "t": rel(at), "route": route,
                      "relation": dedup.get("relation") or ("variant" if item.get("variant_of")
                                                            else "independent"),
                      "related": dedup.get("related_finding_id") or item.get("variant_of")})

    def errors_of(items):
        return [{"t": rel(s["at"]), "id": s["id"], "tool": s["name"], "status": s["status"],
                 "error": s.get("error_class"), "target": target(s)}
                for s in items if s.get("status") not in (None, "ok")][:MAX_ERRORS]

    trunk_steps = [s for s in steps if not s["key"]]
    raw: dict[str, list[list[dict]]] = {}
    for key, items in by_key.items():
        items.sort(key=lambda s: s["at"])
        episodes: list[list[dict]] = [[items[0]]]
        for step in items[1:]:
            if step["at"] - episodes[-1][-1]["end"] > EPISODE_GAP:
                episodes.append([step])
            else:
                episodes[-1].append(step)
        raw[key] = episodes
    # Background work: an episode that wraps whole episodes of other routes is
    # housekeeping interleaved with the real work; it stays on the trunk.
    spans_of = [(key, ep[0]["at"], max(s["end"] for s in ep)) for key, eps in raw.items()
                for ep in eps if len(ep) >= MIN_STEPS]

    def background(key, ep):
        a, b = ep[0]["at"], max(s["end"] for s in ep)
        return sum(1 for other, oa, ob in spans_of
                   if other != key and oa >= a and ob <= b) >= BACKGROUND_WRAPS

    routes = []
    for key, episodes in raw.items():
        items = by_key[key]
        outcome = outcomes.get(key)
        route_findings = [f for f in found if f["route"] == key]
        state = ("finding" if route_findings else
                 "refuted" if outcome in ("refuted", "unsupported") else
                 "done" if outcome else "open")
        drawn = []
        moved = 0
        for index, episode in enumerate(episodes):
            last = index == len(episodes) - 1
            meaningful = len(episode) >= MIN_STEPS or (last and state != "open")
            if not meaningful or (not route_findings and background(key, episode)):
                trunk_steps.extend(episode)
                moved += len(episode)
                continue
            drawn.append({"a": rel(episode[0]["at"]), "b": rel(max(s["end"] for s in episode)),
                          "steps": len(episode), "last": last,
                          "errors": errors_of(episode)})
        if drawn:
            drawn[-1]["last"] = True
        tools: dict[str, int] = defaultdict(int)
        for step in items:
            tools[step["family"]] += 1
        routes.append({
            "key": key, "name": key[2:], "kind": "hypothesis" if key.startswith("h:") else "path",
            "actor": items[0]["actor"], "claim": claims.get(key), "state": state,
            "outcome": outcome, "a": rel(items[0]["at"]), "b": rel(max(s["end"] for s in items)),
            "steps": len(items), "tools": dict(tools),
            "errors": len([s for s in items if s.get("status") not in (None, "ok")]),
            "findings": [f["id"] for f in route_findings], "episodes": drawn,
            "background": moved > 0 and not drawn,
        })
    routes.sort(key=lambda r: r["a"])
    actors = sorted({s["actor"] for s in steps if s.get("actor")})
    # Cycles: each agent run opens with announce_agent; otherwise one cycle.
    marks = sorted(s["at"] for s in steps if s["name"] in CYCLE_NAMES)
    starts = [t0] + [m for m in marks if m - t0 > 5]
    cycles = []
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else end
        inside = [s for s in steps if start <= s["at"] < stop]
        if not inside and index:
            continue
        cycles.append({"i": len(cycles), "a": rel(start),
                       "b": rel(max([s["end"] for s in inside] + [start])),
                       "steps": len(inside),
                       "errors": len([s for s in inside if s.get("status") not in (None, "ok")])})
    trunk_steps.sort(key=lambda s: s["at"])
    # Activity per bucket for the overview strip and idle detection.
    total = max(1.0, end - t0)
    bucket = next((b for b in (60, 120, 300, 600, 900, 1800, 3600) if total / b <= 360),
                  int(-(-total // 360)))
    count = int(total // bucket) + 1
    per_steps = [0] * count
    per_errors = [0] * count
    for step in steps:
        index = min(count - 1, max(0, int((step["at"] - t0) // bucket)))
        per_steps[index] += 1
        if step.get("status") not in (None, "ok"):
            per_errors[index] += 1
    families: dict[str, int] = defaultdict(int)
    for step in steps:
        families[step["family"]] += 1
    failed = [s for s in steps if s.get("status") not in (None, "ok")]
    return {
        "activity": {"bucket": bucket, "steps": per_steps, "errors": per_errors},
        "clock": {"start": rel(_ts(started_at)) if started_at else 0.0,
                  "deadline": rel(_ts(deadline)) if deadline else None,
                  "source": deadline_source if deadline else None},
        "verdicts": sorted(({"t": rel(v["at"]), "id": v["id"], "outcome": v["outcome"],
                             "claim": claims.get(f"h:{v['id']}"), "findings": v["findings"]}
                            for v in verdicts), key=lambda v: v["t"]),
        "failures": [{"t": rel(s["at"]), "tool": s["name"], "status": s["status"],
                      "target": target(s)} for s in failed[-MAX_FAILURES:]],
        "families": dict(families),
        "schema": "nidavellir.run-tree.v1",
        "started_at": datetime.fromtimestamp(t0).isoformat() if t0 else None,
        "duration": rel(end), "live": live, "truncated": truncated, "actors": actors,
        "cycles": cycles, "routes": routes, "findings": found,
        "trunk": {"steps": len(trunk_steps), "errors": errors_of(trunk_steps)},
        "totals": {"steps": len(steps), "spans": len(rows),
                   "errors": len([s for s in steps if s.get("status") not in (None, "ok")]),
                   "refused": len([s for s in steps if s.get("status") == "budget_refused"])},
    }


def route_steps(rows: list[dict], key: str | None, *, started_at=None, limit: int = 1000) -> dict:
    """The steps of one route (``key`` None: the trunk's), oldest first."""
    steps = fold(rows)
    t0 = min([_ts(started_at)] + [s["at"] for s in steps if s["at"]]) if steps else 0
    counts: dict[str, int] = defaultdict(int)
    for step in steps:
        if step["key"]:
            counts[step["key"]] += 1
    picked = []
    for step in steps:
        own = step["key"] if (step["key"] and not (step["key"].startswith("p:")
                                                    and counts[step["key"]] < MIN_STEPS)) else None
        if own == key:
            picked.append(step)
    return {"key": key, "count": len(picked), "steps": [{
        "id": s["id"], "t": round(max(0.0, s["at"] - t0), 1), "name": s["name"], "kind": s["kind"],
        "family": s["family"], "status": s["status"], "duration_ms": s.get("duration_ms"),
        "target": target(s), "error": s.get("error_class"),
        "input": (s.get("input_preview") or "")[:1200],
        "output": (s.get("output_preview") or "")[:1200],
    } for s in picked[-limit:]]}


def search(rows: list[dict], query: str) -> dict:
    """Matches of ``query`` (case-insensitive) in step targets and inputs,
    counted per route key ("trunk" for steps on no route)."""
    needle = query.lower()
    steps = fold(rows)
    counts: dict[str, int] = defaultdict(int)
    for step in steps:
        if step["key"]:
            counts[step["key"]] += 1
    hits: dict[str, int] = defaultdict(int)
    for step in steps:
        text = (target(step) + " " + (step.get("input_preview") or "")).lower()
        if needle in text:
            key = step["key"]
            if not key or (key.startswith("p:") and counts[key] < MIN_STEPS):
                key = "trunk"
            hits[key] += 1
    return {"query": query, "hits": dict(hits), "total": sum(hits.values())}
