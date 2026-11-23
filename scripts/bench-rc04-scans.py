#!/usr/bin/env python3
"""RC-04: cost of F2's scenario binding scan and R2's finding scan at scale.

F2's carry-over reads every binding event of a scenario
(``Database.scenario_binding_events``). R2's relation and lookup read every
finding event (``Database.list_events(types=("finding",))``), then match the
lineage in Python. This seeds a scratch database with the production event mix
(2026-11-23: 7,784 events, 56 findings, 16 deployments over 4 scenarios) at the
requested multiples and reports p50 and p95 per query.

  DATABASE_URL=postgresql+psycopg://... .venv/bin/python scripts/bench-rc04-scans.py 1 10

The database must be empty and disposable: the schema is migrated and filled.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cyber-range" / "services" / "scenario-orchestrator"))
os.environ.setdefault("MOCK_MODE", "true")

BASE = {"events": 7784, "findings": 56, "deployments": 16, "scenarios": 4}
BINDING_TYPES = ("agent_binding", "agent_binding_revoked", "agent_binding_paused",
                 "agent_binding_resumed")
OTHER_TYPES = ("budget_settled", "budget_reserved", "poc_job_finished",
               "helper_job_submitted", "http_request", "hypothesis_probe", "state")
RUNS = 40
BUDGET_MS = 150.0


def _seed(engine, scale: int) -> dict:
    from sqlalchemy import text

    rng = random.Random(scale)  # nosec B311 - synthetic benchmark data, not security
    scenarios = [f"bench-scenario-{i}" for i in range(BASE["scenarios"])]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deployments = []
    with engine.begin() as conn:
        for i in range(BASE["deployments"] * scale):
            dep_id = str(uuid.uuid4())
            deployments.append(dep_id)
            conn.execute(text(
                "INSERT INTO deployments (id, user_id, scenario, status, created_at, updated_at) "
                "VALUES (:id, :u, :s, 'destroyed', :t, :t)"),
                {"id": dep_id, "u": f"bench-{i}", "s": scenarios[i % len(scenarios)], "t": now})
        rows = []
        for i in range(BASE["events"] * scale):
            lab = rng.choice(deployments)
            kind = rng.random()
            if kind < BASE["findings"] / BASE["events"]:
                type_ = "finding"
                payload = {"finding_id": str(uuid.uuid4()), "title": "bench",
                           "root_cause": {"fingerprint": "sha256:" + uuid.uuid4().hex * 2,
                                          "oracle_digest": "sha256:" + uuid.uuid4().hex * 2,
                                          "lineage": f"arena:{lab}"}}
            elif kind < 0.03:
                type_ = rng.choice(BINDING_TYPES)
                payload = {"agent_name": f"agent-{rng.randrange(20)}", "stance": "attacker",
                           "persistent": rng.random() < 0.3}
            else:
                type_ = rng.choice(OTHER_TYPES)
                payload = {"n": i, "detail": "x" * rng.randrange(40, 400)}
            rows.append({"lab": lab, "ts": now - timedelta(seconds=i), "type": type_,
                         "payload": json.dumps(payload)})
        conn.execute(text("INSERT INTO events (lab_id, ts, actor, type, payload) "
                          "VALUES (:lab, :ts, 'bench', :type, :payload)"), rows)
        conn.execute(text("ANALYZE"))
    return {"scenarios": scenarios, "deployments": deployments}


def _time(fn) -> dict:
    fn()  # warm the cache once; interactive reads run warm
    samples = []
    for _ in range(RUNS):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {"p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 2)}


def main(scales: list[int]) -> int:
    from sqlalchemy import create_engine, text

    import migrate
    import research_integrity
    from database import Database

    url = os.environ["DATABASE_URL"]
    report = {"budget_ms": BUDGET_MS, "runs": RUNS, "results": {}}
    for scale in scales:
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        engine.dispose()
        migrate.migrate(url)
        Database._instance = None
        db = Database()
        seeded = _seed(db._engine, scale)
        scenario, exclude = seeded["scenarios"][0], seeded["deployments"][0]
        f2 = _time(lambda: db.scenario_binding_events(scenario, BINDING_TYPES,
                                                       exclude_lab_id=exclude))
        r2 = _time(lambda: research_integrity.lineage_matches(
            db.list_events(limit=None, types=("finding",)), f"arena:{exclude}",
            "sha256:" + "0" * 64))
        report["results"][f"{scale}x"] = {
            "events": BASE["events"] * scale, "f2_scenario_binding_scan": f2,
            "r2_finding_scan": r2,
            "over_budget": [name for name, value in (("f2", f2), ("r2", r2))
                            if value["p95_ms"] > BUDGET_MS]}
    print(json.dumps(report, indent=2))
    return 1 if any(r["over_budget"] for r in report["results"].values()) else 0


if __name__ == "__main__":
    sys.exit(main([int(arg) for arg in sys.argv[1:]] or [1, 10]))
