#!/usr/bin/env python3
"""NV07-R5: kill the worker mid-trial and prove the reaper terminalizes it.

The worker is SIGKILLed while a trial holds a claimed arena. Seventy minutes of
worker silence are simulated by backdating the evaluation heartbeat; everything
after that is the real beat-scheduled reaper, the real worker restart and the
real arena cleanup. The evidence file records the backdating explicitly.
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "verify_nv07_live", Path(__file__).with_name("verify-nv07-live.py"))
nv07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv07)
fixture = nv07.fixture

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs/verification/nv07-recovery-live-2026-09-26.json"
evaluation_id = None


def backdate(evaluation, minutes):
    fixture.run(*fixture.COMPOSE, "exec", "-T", "orchestrator", "python", "-c",
        "from datetime import datetime, timedelta; from database import Database; "
        "from models import Evaluation; db = Database()\n"
        "with db._session() as s:\n"
        f"    row = s.get(Evaluation, {evaluation!r})\n"
        f"    row.updated_at = datetime.now() - timedelta(minutes={minutes}); s.commit()")


def main():
    global evaluation_id
    image_id, source, challenge, baseline, candidate = nv07.prepare()
    suite = fixture.api("POST", "/eval-suites", {"name": "authz-recovery",
        "version": "v1", "challenge_ids": [challenge["id"]], "seeds": [1, 2, 3],
        "action_cap": 20, "deadline_seconds": 120}, expected=(201,))
    evaluation_id = fixture.api("POST", "/evaluations", {"suite_id": suite["id"],
        "baseline_id": baseline["id"], "candidate_id": candidate["id"]},
        expected=(202,))["id"]

    # Kill as soon as a trial owns an arena: the worker is mid-deploy or mid-play.
    running = fixture.wait(f"/evaluations/{evaluation_id}", lambda data: any(
        t["state"] == "running" and t["arena_id"] for t in data.get("trials", [])),
        timeout=300)
    fixture.run(*fixture.COMPOSE, "kill", "-s", "SIGKILL", "worker")
    at_kill = fixture.api("GET", f"/evaluations/{evaluation_id}")
    killed = [t for t in at_kill["trials"] if t["state"] == "running"]
    assert killed, at_kill
    completed_before = {t["id"]: t for t in at_kill["trials"] if t["state"] == "completed"}
    fixture.ARENAS.extend(t["arena_id"] for t in at_kill["trials"] if t["arena_id"])

    # A replacement worker plus beat bring the reaper back. It must leave a
    # recently-progressing evaluation alone until the heartbeat goes stale.
    fixture.run(*fixture.COMPOSE, "up", "-d", "worker", "beat")
    time.sleep(8)
    assert fixture.api("GET", f"/evaluations/{evaluation_id}")["state"] == "running"
    backdate(evaluation_id, 71)
    record = fixture.wait(f"/evaluations/{evaluation_id}",
        lambda data: data.get("state") == "complete", timeout=120)
    by_id = {t["id"]: t for t in record["trials"]}
    for trial in killed:
        assert by_id[trial["id"]]["state"] == "infrastructure_failure", by_id[trial["id"]]
        assert by_id[trial["id"]]["error"] == "worker_interrupted", by_id[trial["id"]]
    for trial_id, trial in completed_before.items():
        assert by_id[trial_id]["state"] == "completed"
        assert by_id[trial_id]["result"] == trial["result"]
    assert all(t["state"] in ("completed", "infrastructure_failure")
               for t in record["trials"]), record
    comparison = record["comparison"]
    assert comparison["infrastructure_failed_pairs"] >= 1, comparison
    for row in comparison["pairs"]:
        if "infrastructure_failure" in (row["baseline_state"], row["candidate_state"]):
            assert not row["matched"], row

    # The orphaned arena must be reclaimed by the normal reaper/destroy path, and no
    # late or redelivered task may reopen the evaluation.
    for arena in [t["arena_id"] for t in killed]:
        fixture.wait(f"/status/{arena}", lambda data: data.get("status") in (
            "destroyed", "failed"), timeout=400)
    time.sleep(10)
    after_restart = fixture.api("GET", f"/evaluations/{evaluation_id}")
    assert after_restart["state"] == "complete"
    assert {t["id"]: (t["state"], t["result"]) for t in after_restart["trials"]} == {
        t["id"]: (t["state"], t["result"]) for t in record["trials"]}

    fixture.api("DELETE", f"/destroy/{source}", expected=(200, 202))
    for arena in fixture.ARENAS:
        fixture.wait(f"/status/{arena}", lambda data: data.get("status") in (
            "destroyed", "failed"), timeout=400)
    resources = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
    assert not any(any(counts.values()) for counts in resources.values()), resources
    evidence = {"schema": "nidavellir/nv07-recovery-live-evidence/v1",
        "fixture_image": image_id, "source_arena": source,
        "evaluation_id": evaluation_id, "running_when_observed": [
            t["id"] for t in running["trials"] if t["state"] == "running"],
        "killed_trials": [{"id": t["id"], "arena_id": t["arena_id"],
                           "final_state": by_id[t["id"]]["state"],
                           "final_error": by_id[t["id"]]["error"]} for t in killed],
        "completed_before_kill": len(completed_before),
        "simulated": "evaluation heartbeat backdated 71 minutes after SIGKILL; "
                     "recovery, worker restart and cleanup ran unmodified",
        "comparison": comparison, "final_resources": resources}
    EVIDENCE.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    finally:
        fixture.run(*fixture.COMPOSE, "up", "-d", "worker", check=False)
        if evaluation_id:
            try:
                record = fixture.api("GET", f"/evaluations/{evaluation_id}")
                fixture.ARENAS.extend(t["arena_id"] for t in record["trials"]
                                     if t["arena_id"] and t["arena_id"] not in fixture.ARENAS)
            except (OSError, RuntimeError):
                pass
        fixture.cleanup_arenas()
        fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        leftovers = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
        if any(any(value.values()) for value in leftovers.values()):
            raise RuntimeError(f"NV07-R5 cleanup left labelled resources: {leftovers}")
