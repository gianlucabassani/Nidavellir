"""Durable NV-07 records, pair accounting and operator boundary."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

import api
import auth
import experiments
from database import Database


def _build(db, name):
    return db.create_agent_build(name=name, version="v1", digest=f"sha256:{name}",
        driver="scripted-mcp/v1", config={"plan": [], "model": "scripted"})


def _challenge(db):
    return db.create_eval_challenge(name="authorization", version="v1",
        scenario="nv06", source_arena_id="source", recipe_digest="sha256:recipe",
        validator_version="nidavellir/validation-verdict/v1", label="calibration")


def test_evaluation_records_and_atomic_trial_claim():
    db = Database()
    baseline = _build(db, f"baseline-{uuid.uuid4().hex}")
    candidate = _build(db, f"candidate-{uuid.uuid4().hex}")
    challenge = _challenge(db)
    suite = db.create_eval_suite(name="authz", version="v1",
        challenge_ids=[challenge["id"]], seeds=[1, 2, 3],
        action_cap=20, deadline_seconds=600)
    evaluation = db.create_evaluation(suite_id=suite["id"],
        baseline_id=baseline["id"], candidate_id=candidate["id"])
    record = db.get_evaluation(evaluation["id"])
    assert len(record["runs"]) == 2
    assert len(record["trials"]) == 6
    trial = record["trials"][0]
    assert db.claim_eval_trial(trial["id"], "first")
    assert not db.claim_eval_trial(trial["id"], "second")
    assert db.assign_eval_trial_arena(trial["id"], "first", "arena-1")
    assert not db.finish_eval_trial(trial["id"], "second", state="completed")
    assert db.finish_eval_trial(trial["id"], "first", state="infrastructure_failure",
                                error="readiness failed")
    stored = next(item for item in db.get_evaluation(evaluation["id"])["trials"]
                  if item["id"] == trial["id"])
    assert stored["arena_id"] == "arena-1"


def test_comparison_excludes_infrastructure_and_unmatched_starts():
    record = {"runs": [
        {"id": "a", "side": "baseline", "challenge_id": "c"},
        {"id": "b", "side": "candidate", "challenge_id": "c"}],
        "trials": [
            {"run_id": "a", "seed": 1, "state": "completed", "starting_digest": "d",
             "result": {"export": {"metadata": {"pass@1": 0}}, "false_claims": 1,
                        "requests": 1}},
            {"run_id": "b", "seed": 1, "state": "completed", "starting_digest": "d",
             "result": {"export": {"metadata": {"pass@1": 1}}, "false_claims": 0,
                        "requests": 2}},
            {"run_id": "a", "seed": 2, "state": "infrastructure_failure",
             "starting_digest": None, "result": None},
            {"run_id": "b", "seed": 2, "state": "completed", "starting_digest": "d",
             "result": {"export": {"metadata": {"pass@1": 1}}, "false_claims": 0,
                        "requests": 2}}]}
    comparison = experiments.compare(record)
    assert comparison["matched_pairs"] == 1
    assert comparison["infrastructure_failed_pairs"] == 1
    assert comparison["verified_difference_mean"] == 1


def test_agent_cannot_read_or_create_evaluation_records(monkeypatch):
    monkeypatch.setattr(api.run_evaluation, "delay", lambda *_: None)
    db = Database()
    key = auth.generate_api_key()
    name = f"nv07-agent-{uuid.uuid4().hex}"
    db.create_api_key(auth.hash_api_key(key), name=name, role="agent")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    assert client.get("/agent-builds").status_code == 403
    assert client.get("/evaluations").status_code == 403
    assert client.post("/agent-builds", json={"name": "x", "version": "v1",
        "plan": [{"tool": "get_topology", "args": {}}]}).status_code == 403
