"""UX-28: the timeline draws the run against its time budget.

The run-tree model places the arena's start and deadline on the run's own
seconds (``clock``) and adds what the serpent sprouts: the agent's verdicts,
every failed call, the tool mix. The endpoint takes the deadline from the
budget policy, else (or when sooner) the arena's lease."""
from datetime import timedelta

from sqlalchemy import update

import run_tree
from database import Database
from models import Deployment
from tests.research_support import active_arena, client
from tests.test_ux27_run_tree import T0, probe, row, run
from timeutil import db_now


def test_clock_verdicts_failures_and_tool_mix():
    rows = run() + [row(70, "exec", '{"command":"id"}', status="budget_refused")]
    tree = run_tree.build(rows, findings=[], started_at=T0, now=T0 + timedelta(minutes=90),
                          live=False, deadline=T0 + timedelta(hours=4), deadline_source="lease",
                          tested=[{"hypothesis_id": "H-1", "outcome": "supported",
                                   "finding_ids": ["f1"], "ts": T0 + timedelta(minutes=15)},
                                  {"hypothesis_id": "H-2", "outcome": "refuted",
                                   "ts": T0 + timedelta(minutes=85)}])
    assert tree["clock"] == {"start": 0.0, "deadline": 14400.0, "source": "lease"}
    # H-1 was marked by a step; H-2 only by its event: both, once each.
    assert [(v["id"], v["outcome"], v["t"]) for v in tree["verdicts"]] == [
        ("H-1", "supported", 900.0), ("H-2", "refuted", 5100.0)]
    assert tree["verdicts"][0]["findings"] == ["f1"]
    assert tree["verdicts"][0]["claim"] == "Exports never execute."
    assert [(f["tool"], f["status"]) for f in tree["failures"]] == [
        ("http/request", "error"), ("exec", "budget_refused")]
    assert tree["failures"][1]["target"] == "$ id"
    assert sum(tree["families"].values()) == tree["totals"]["steps"]
    assert tree["families"]["http"] > tree["families"]["exec"] == 1


def test_no_deadline_leaves_the_clock_open():
    tree = run_tree.build([probe(1, "H-1")], findings=[], tested=[], started_at=T0,
                          now=T0 + timedelta(minutes=5), live=True)
    assert tree["clock"] == {"start": 0.0, "deadline": None, "source": None}


def test_endpoint_takes_the_lease_when_it_ends_before_the_budget():
    arena = active_arena("ux28-scenario")
    db = Database()
    start = db_now() - timedelta(hours=1)
    with db._session() as session:
        session.execute(update(Deployment).where(Deployment.id == arena).values(
            created_at=start, expires_at=start + timedelta(hours=24)))
        session.commit()
    tree = client("operator").get(f"/arenas/{arena}/run-tree").json()
    assert tree["clock"]["source"] == "lease"
    assert tree["clock"]["deadline"] - tree["clock"]["start"] == 24 * 3600
    assert tree["budget"] == {"cap": 1000, "spent": 0}
    assert tree["verdicts"] == [] and tree["failures"] == []
