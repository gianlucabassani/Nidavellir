"""UX-27: the run tree, aggregated on the server.

Routes come from declared hypotheses (else HTTP path prefixes); self-reported
twins fold into enforced calls; a route that goes quiet splits into episodes
and short sporadic episodes stay on the trunk (no branch across the whole
run); cycles open at announce_agent; findings attach to their route; search
counts matches per route. Operator-only endpoints."""
from datetime import datetime, timedelta

import run_tree
import spans as span_store
from database import Database
from tests.research_support import active_arena, client

T0 = datetime(2026, 11, 26, 10, 0, 0)
_id = iter(range(1, 100000))


def row(minute, name, preview="", *, kind="tool", status="ok", self_reported=False, actor="agent-1"):
    at = T0 + timedelta(minutes=minute)
    return {"id": next(_id), "kind": kind, "name": name, "status": status, "actor": actor,
            "started_at": at, "ended_at": at + timedelta(seconds=1), "duration_ms": 1000,
            "error_class": "Timeout" if status == "error" else None, "input_preview": preview,
            "attrs": {"nv.self_reported": True} if self_reported else {}}


def probe(minute, hyp, path="/x", **kw):
    return row(minute, "http/request",
               f'{{"hypothesis_id":"{hyp}","method":"GET","path":"{path}"}}', **kw)


def run():
    rows = [row(0, "announce_agent", kind="agent", self_reported=True),
            row(0.2, "get_briefing", kind="agent", self_reported=True),
            probe(1, "H-MAINT"),  # housekeeping at the start ...
            row(2, "register_hypothesis",
                '{"contract":{"id":"H-1","invariant":"Exports never execute."}}',
                kind="agent", self_reported=True)]
    for m in range(3, 13):
        rows.append(probe(m, "H-1", "/export/a.jspf"))
        rows.append(probe(m, "H-1", "/export/a.jspf", kind="agent", self_reported=True))
    rows.append(probe(13, "H-1", status="error"))
    rows.append(row(14, "findings", '{"hypothesis_id":"H-1","title":"RCE"}'))
    rows.append(row(15, "mark_hypothesis_tested",
                    '{"hypothesis_id":"H-1","outcome":"supported","finding_ids":["f1"]}',
                    kind="agent", self_reported=True))
    rows.append(row(60, "announce_agent", kind="agent", self_reported=True))  # a second cycle
    for m in range(61, 65):
        rows.append(probe(m, "H-2"))
    rows.append(probe(66, "H-MAINT"))  # ... and again an hour later
    for m in range(80, 84):
        rows.append(probe(m, "H-2"))  # H-2 resumes after a quiet stretch
    return rows


def test_tree_has_routes_episodes_cycles_and_findings():
    tree = run_tree.build(run(), findings=[{"finding_id": "f1", "title": "RCE", "severity": "high",
                                            "ts": T0 + timedelta(minutes=14)}],
                          tested=[{"hypothesis_id": "H-1", "outcome": "supported",
                                   "finding_ids": ["f1"]}],
                          started_at=T0, now=T0 + timedelta(minutes=90), live=False)
    routes = {r["name"]: r for r in tree["routes"]}
    h1 = routes["H-1"]
    assert h1["state"] == "finding" and h1["claim"] == "Exports never execute."
    assert h1["steps"] == 14 and h1["errors"] == 1  # twins folded: 11 probes + register + finding + tested
    assert len(h1["episodes"]) == 1 and h1["episodes"][0]["errors"][0]["error"] == "Timeout"
    assert tree["findings"][0]["route"] == "h:H-1"
    assert len(routes["H-2"]["episodes"]) == 2  # split by the quiet stretch
    assert routes["H-MAINT"]["episodes"] == []  # sporadic steps stay on the trunk
    assert tree["trunk"]["steps"] >= 2
    assert [c["i"] for c in tree["cycles"]] == [0, 1] and tree["cycles"][1]["a"] == 3600.0
    assert tree["totals"]["errors"] == 1 and tree["totals"]["spans"] > tree["totals"]["steps"]


def test_steps_of_a_route_and_search():
    rows = run()
    steps = run_tree.route_steps(rows, "h:H-1", started_at=T0)
    assert steps["count"] == 14 and steps["steps"][0]["name"] == "register_hypothesis"
    assert steps["steps"][1]["target"] == "GET /export/a.jspf"
    trunk = run_tree.route_steps(rows, None, started_at=T0)
    assert {s["name"] for s in trunk["steps"]} >= {"announce_agent", "get_briefing"}
    found = run_tree.search(rows, "a.jspf")
    assert found["hits"] == {"h:H-1": 10} and found["total"] == 10


def test_endpoints_are_operator_only_and_aggregate_real_spans():
    arena = active_arena("ux27-scenario")
    db = Database()
    for minute in range(5):
        at = T0 + timedelta(minutes=minute)
        span_store.record(db, name="http/request", kind="tool", actor="agent-1", actor_kind="agent",
                          arena_id=arena, input={"hypothesis_id": "H-9", "method": "GET", "path": "/a"},
                          started_at=at, ended_at=at + timedelta(seconds=1))
    operator = client("operator")
    tree = operator.get(f"/arenas/{arena}/run-tree?q=/a").json()
    assert tree["schema"] == "nidavellir.run-tree.v1"
    assert [r["name"] for r in tree["routes"]] == ["H-9"]
    assert tree["search"]["hits"] == {"h:H-9": 5}
    steps = operator.get(f"/arenas/{arena}/run-tree/steps?route=h:H-9").json()
    assert steps["count"] == 5
    assert client("agent").get(f"/arenas/{arena}/run-tree").status_code == 403
    assert client("agent").get(f"/arenas/{arena}/run-tree/steps?route=trunk").status_code == 403
    assert operator.get("/arenas/nope/run-tree").status_code == 404


def test_background_work_that_wraps_other_routes_stays_on_the_trunk():
    rows = []
    for m in range(0, 40, 4):  # housekeeping every 4 minutes for 40 minutes
        rows.append(probe(m, "H-MAINT"))
    for start, hyp in ((5, "H-A"), (20, "H-B")):
        for k in range(6):
            rows.append(probe(start + k, hyp))
    tree = run_tree.build(rows, findings=[], tested=[], started_at=T0,
                          now=T0 + timedelta(minutes=45), live=False)
    routes = {r["name"]: r for r in tree["routes"]}
    assert routes["H-MAINT"]["episodes"] == [] and routes["H-MAINT"]["background"] is True
    assert len(routes["H-A"]["episodes"]) == 1 and len(routes["H-B"]["episodes"]) == 1
    assert tree["trunk"]["steps"] == 10


def test_activity_buckets_count_steps_and_errors():
    tree = run_tree.build(run(), findings=[], tested=[], started_at=T0,
                          now=T0 + timedelta(minutes=90), live=False)
    activity = tree["activity"]
    assert activity["bucket"] == 60
    assert sum(activity["steps"]) == tree["totals"]["steps"]
    assert sum(activity["errors"]) == tree["totals"]["errors"] == 1
    assert activity["steps"][30] == 0  # the quiet stretch between cycles
