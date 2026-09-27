"""Durable NV-07 records, pair accounting and operator boundary."""
from __future__ import annotations

import builtins
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api
import auth
import experiments
from database import Database


def test_nested_trial_error_exposes_safe_cause_only():
    group = builtins.__dict__["ExceptionGroup"]
    assert experiments._safe_trial_error(group("task group", [
        RuntimeError("model provider returned HTTP 401")])) == (
            "RuntimeError: model provider returned HTTP 401")
    assert experiments._safe_trial_error(group("task group", [
        RuntimeError("private provider body and secret")])) == "RuntimeError"
    assert experiments._safe_trial_error(group("task group", [
        RuntimeError("model provider returned HTTP 401 secret")])) == "RuntimeError"
    assert experiments._safe_trial_error(group("task group", [
        OSError("credential in transport URL")])) == "OSError"


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
    monkeypatch.setattr(api, "enqueue_evaluation", lambda *_: None)
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


def test_challenge_label_is_explicit_and_public_fixture_cannot_be_held_out(monkeypatch):
    db = Database()
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name=f"nv08-operator-{uuid.uuid4().hex}",
                      role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    monkeypatch.setattr(api.db, "get_deployment", lambda _: {
        "status": "active", "effective_provider": "docker-local"})
    monkeypatch.setattr(api.db, "get_lifecycle_recipe", lambda _: {
        "scenario_name": "authz", "recipe_digest": "sha256:recipe",
        "effective_provider": "docker-local", "runtime_reset": {"status": "eligible"},
        "seed": {"schema": "nidavellir/nv06-authz/v1"},
        "scenario": {"vulnerabilities": [{"validator": "authorization_effect"}]}})
    monkeypatch.setattr(api.db, "list_events", lambda *_, **__: [{"payload": {}}])
    payload = {"name": "authz", "version": "v1", "source_arena_id": "source"}
    assert client.post("/eval-challenges", json=payload).status_code == 422
    assert client.post("/eval-challenges", json={**payload, "label": "held-out"}).status_code == 422
    response = client.post("/eval-challenges", json={**payload, "label": "calibration"})
    assert response.status_code == 201
    assert response.json()["validator_version"] == "authorization_effect/v1"
    assert response.json()["label"] == "calibration"


def test_comparison_keeps_calibration_scope_visible():
    record = _paired([1, 0, 1, 1, 0])
    record["challenges"] = [{"id": "c", "label": "calibration"}]
    result = experiments.compare(record)
    assert result["evidence_scope"] == "calibration_or_unknown"
    assert result["leakage_labels"] == ["calibration"]
    assert all(pair["leakage_label"] == "calibration" for pair in result["pairs"])


def test_trial_export_carries_challenge_label_and_validator(monkeypatch):
    import eval_export  # noqa: PLC0415

    class TrialDB:
        def get_deployment(self, _arena_id):
            return {"scenario": "authz"}

        def list_events(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr(api, "_score_report", lambda *_: {})
    monkeypatch.setattr(api, "_scenario_meta", lambda *_: None)
    monkeypatch.setattr(eval_export, "build_eval_record", lambda **_: {
        "metadata": {}, "tags": []})
    result = experiments._trial_result(TrialDB(), "arena", {
        "transcript": [], "model_usage": [{"input_tokens": 3, "output_tokens": 2,
                                        "cost_usd": None}],
        "termination": "model_end_turn"}, {
        "id": "challenge", "label": "calibration",
        "validator_version": "authorization_effect/v1"})
    row = result["export"]
    assert row["metadata"]["nv.challenge_id"] == "challenge"
    assert row["metadata"]["nv.leakage_label"] == "calibration"
    assert row["metadata"]["tokens"] == 5
    assert row["metadata"]["cost_usd"] is None
    assert result["termination"] == "model_end_turn"
    assert row["metadata"]["nv.validator_version"] == "authorization_effect/v1"
    assert "leakage:calibration" in row["tags"]


# --- scheduled recovery (NV07-R5) -------------------------------------------

def _evaluation(db):
    baseline = _build(db, f"baseline-{uuid.uuid4().hex}")
    candidate = _build(db, f"candidate-{uuid.uuid4().hex}")
    suite = db.create_eval_suite(name="authz", version="v1",
        challenge_ids=[_challenge(db)["id"]], seeds=[1, 2, 3],
        action_cap=20, deadline_seconds=600)
    return db.create_evaluation(suite_id=suite["id"], baseline_id=baseline["id"],
                                candidate_id=candidate["id"])["id"]


def _backdate(db, evaluation_id, when):
    from models import Evaluation  # noqa: PLC0415

    with db._session() as session:
        row = session.get(Evaluation, evaluation_id)
        row.created_at = row.updated_at = when
        session.commit()


@pytest.fixture
def evaluations():
    """Create evaluations that are closed afterwards: a backdated ``queued`` row left
    in the shared test database would be requeued by every later reaper test."""
    db = Database()
    created = []

    def make():
        created.append(_evaluation(db))
        return created[-1]

    yield make
    for evaluation_id in created:
        db.set_evaluation_state(evaluation_id, "complete")


def _trials(db, evaluation_id):
    record = db.get_evaluation(evaluation_id)
    runs = {run["id"]: run["side"] for run in record["runs"]}
    return {(runs[t["run_id"]], t["seed"]): t for t in record["trials"]}


def test_recover_stale_running_evaluation_terminalizes_only_unfinished_trials(evaluations):
    db = Database()
    now = datetime.now()
    evaluation_id = evaluations()
    assert db.set_evaluation_state(evaluation_id, "running", expected="queued")
    trials = _trials(db, evaluation_id)
    # Seed 1 finished on both sides before the worker was lost.
    for side in ("baseline", "candidate"):
        trial = trials[(side, 1)]
        assert db.claim_eval_trial(trial["id"], "lost")
        assert db.finish_eval_trial(trial["id"], "lost", state="completed",
            starting_digest="sha256:start", result={"export": {"metadata": {
                "pass@1": 1 if side == "candidate" else 0}},
                "false_claims": 0, "requests": 1})
    # Seed 2 baseline was mid-run; everything else was still queued.
    running = trials[("baseline", 2)]
    assert db.claim_eval_trial(running["id"], "lost")
    _backdate(db, evaluation_id, now - timedelta(minutes=71))

    assert evaluation_id in db.recover_stale_evaluations(now - timedelta(minutes=70))
    record = db.get_evaluation(evaluation_id)
    assert record["state"] == "complete"
    after = _trials(db, evaluation_id)
    for key, trial in after.items():
        if key[1] == 1:
            assert trial["state"] == "completed" and trial["result"], key
        else:
            assert trial["state"] == "infrastructure_failure", key
            assert trial["error"] == "worker_interrupted", key
    # The lost worker cannot later overwrite the terminal verdict.
    assert not db.finish_eval_trial(running["id"], "lost", state="completed")
    assert db.claim_eval_trial(after[("candidate", 3)]["id"], "late") is False
    # Recovery is idempotent and never re-selects a complete evaluation.
    assert evaluation_id not in db.recover_stale_evaluations(now - timedelta(minutes=70))

    comparison = experiments.compare(record)
    assert comparison["matched_pairs"] == 1
    assert comparison["infrastructure_failed_pairs"] == 2
    assert comparison["verified_difference_mean"] == 1


def test_recover_leaves_fresh_running_queued_and_complete_evaluations(evaluations):
    db = Database()
    now = datetime.now()
    fresh = evaluations()
    assert db.set_evaluation_state(fresh, "running", expected="queued")
    queued_old = evaluations()
    _backdate(db, queued_old, now - timedelta(hours=3))
    done_old = evaluations()
    assert db.set_evaluation_state(done_old, "complete")
    _backdate(db, done_old, now - timedelta(hours=3))

    recovered = db.recover_stale_evaluations(now - timedelta(minutes=70))
    assert not {fresh, queued_old, done_old} & set(recovered)
    assert db.get_evaluation(fresh)["state"] == "running"
    assert db.get_evaluation(queued_old)["state"] == "queued"
    assert all(t["state"] == "queued" for t in db.get_evaluation(queued_old)["trials"])
    assert db.get_evaluation(done_old)["state"] == "complete"


def test_queued_evaluations_before_selects_only_stranded_queued_rows(evaluations):
    db = Database()
    now = datetime.now()
    stranded = evaluations()
    _backdate(db, stranded, now - timedelta(minutes=5))
    fresh = evaluations()
    started = evaluations()
    assert db.set_evaluation_state(started, "running", expected="queued")
    _backdate(db, started, now - timedelta(minutes=5))

    selected = set(db.queued_evaluations_before(now - timedelta(minutes=2)))
    assert stranded in selected
    assert fresh not in selected
    assert started not in selected


def test_requeued_evaluation_runs_once_even_if_delivered_twice(monkeypatch, evaluations):
    """A requeue racing a live worker must not double-run: the queued→running
    transition is the single admission point."""
    db = Database()
    evaluation_id = evaluations()
    assert db.set_evaluation_state(evaluation_id, "running", expected="queued")
    monkeypatch.setattr(experiments, "_run_trial", lambda *a, **k: pytest.fail("ran"))
    assert experiments.execute(evaluation_id, "second") == {"skipped": True}
    assert all(t["state"] == "queued" for t in db.get_evaluation(evaluation_id)["trials"])


def test_reaper_recovers_stale_and_requeues_stranded_evaluations(monkeypatch, evaluations):
    import tasks  # noqa: PLC0415

    delivered = []
    monkeypatch.setattr(tasks.run_evaluation, "apply_async",
                        lambda args, **limits: delivered.append((args[0], limits)))
    monkeypatch.setattr(tasks, "destroy_lab", type("D", (), {"delay": lambda *a, **k: None})())
    db = Database()
    now = datetime.now()
    stale = evaluations()
    assert db.set_evaluation_state(stale, "running", expected="queued")
    _backdate(db, stale, now - timedelta(minutes=71))
    stranded = evaluations()
    _backdate(db, stranded, now - timedelta(minutes=5))

    result = tasks.reap_labs()
    assert result["evaluations_recovered"] >= 1
    assert result["evaluations_requeued"] >= 1
    assert db.get_evaluation(stale)["state"] == "complete"
    assert all(t["state"] == "infrastructure_failure"
               for t in db.get_evaluation(stale)["trials"])
    by_id = dict(delivered)
    assert stranded in by_id and stale not in by_id
    # Requeued work gets limits sized to its suite: 6 trials x (600 s + overhead).
    assert by_id[stranded]["soft_time_limit"] == experiments.time_limits(6, 600)[0]


# --- interval labelling (NV07-R3) -------------------------------------------

def _paired(values):
    runs = [{"id": "a", "side": "baseline", "challenge_id": "c"},
            {"id": "b", "side": "candidate", "challenge_id": "c"}]
    trials = []
    for seed, diff in enumerate(values, start=1):
        for run_id, verified in (("a", 0), ("b", diff)):
            trials.append({"run_id": run_id, "seed": seed, "state": "completed",
                "starting_digest": "d", "result": {"export": {"metadata": {
                    "pass@1": verified}}, "false_claims": 0, "requests": 1}})
    return {"runs": runs, "trials": trials}


def test_identical_pairs_report_a_degenerate_interval():
    verified = experiments.compare(_paired([1, 1, 1]))["differences"]["verified"]
    assert verified["bootstrap_95"] == [1.0, 1.0]
    assert verified["distinct_values"] == 1
    assert verified["interval_status"] == "degenerate"


def test_interval_support_requires_variation_and_minimum_pairs():
    few = experiments.compare(_paired([1, 0, 1]))["differences"]["verified"]
    assert few["interval_status"] == "insufficient_pairs"
    enough = experiments.compare(_paired([1, 0, 1, 1, 0]))["differences"]["verified"]
    assert enough["distinct_values"] == 2
    assert enough["interval_status"] == "supported"
    empty = experiments.compare({"runs": [], "trials": []})["differences"]["verified"]
    assert empty["interval_status"] == "no_pairs"


def test_two_class_regression_is_attributed_and_pooled_interval_supported():
    runs = []
    trials = []
    for challenge_id, good, bad in (("authz", 1, 1), ("grants", 1, 0)):
        for side, value in (("baseline", good), ("candidate", bad)):
            run_id = f"{challenge_id}-{side}"
            runs.append({"id": run_id, "side": side, "challenge_id": challenge_id})
            for seed in range(1, 6):
                trials.append({"run_id": run_id, "seed": seed, "state": "completed",
                    "starting_digest": f"start-{challenge_id}",
                    "result": {"export": {"metadata": {"pass@1": value}},
                               "false_claims": 0, "requests": 3}})
    record = {"runs": runs, "trials": trials,
              "challenges": [{"id": "authz", "label": "calibration"},
                             {"id": "grants", "label": "calibration"}]}
    comparison = experiments.compare(record)
    assert comparison["matched_pairs"] == 10
    assert comparison["infrastructure_failed_pairs"] == 0
    assert comparison["differences"]["verified"]["interval_status"] == "supported"
    assert comparison["by_challenge"]["authz"]["differences"]["verified"]["mean"] == 0
    assert comparison["by_challenge"]["grants"]["differences"]["verified"]["mean"] == -1
    assert comparison["by_challenge"]["grants"]["differences"]["verified"][
        "interval_status"] == "degenerate"


# --- heartbeat and suite-sized limits ---------------------------------------

def test_trial_progress_refreshes_the_evaluation_heartbeat(evaluations):
    """A long suite that keeps finishing trials must never look worker-lost."""
    db = Database()
    now = datetime.now()
    evaluation_id = evaluations()
    assert db.set_evaluation_state(evaluation_id, "running", expected="queued")
    _backdate(db, evaluation_id, now - timedelta(minutes=71))
    trial = db.get_evaluation(evaluation_id)["trials"][0]
    assert db.claim_eval_trial(trial["id"], "live")
    assert evaluation_id not in db.recover_stale_evaluations(now - timedelta(minutes=70))
    _backdate(db, evaluation_id, now - timedelta(minutes=71))
    assert db.finish_eval_trial(trial["id"], "live", state="completed")
    assert evaluation_id not in db.recover_stale_evaluations(now - timedelta(minutes=70))
    assert db.get_evaluation(evaluation_id)["state"] == "running"


def test_limits_cover_the_suite_and_stall_exceeds_one_trial():
    soft, hard = experiments.time_limits(320, 1800)
    assert soft >= 320 * 1800 and hard > soft
    # The longest legitimate gap between heartbeats is one maximal trial.
    assert experiments.STALL_MINUTES * 60 > 1800 + experiments.TRIAL_OVERHEAD_SECONDS


def test_soft_time_limit_terminalizes_remaining_trials(monkeypatch, evaluations):
    from celery.exceptions import SoftTimeLimitExceeded  # noqa: PLC0415

    db = Database()
    evaluation_id = evaluations()
    calls = []

    def expire(*_args, **_kwargs):
        calls.append(1)
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(experiments, "_run_trial", expire)
    assert experiments.execute(evaluation_id, "claim")["state"] == "complete"
    assert len(calls) == 1
    record = db.get_evaluation(evaluation_id)
    assert record["state"] == "complete"
    assert {t["state"] for t in record["trials"]} == {"infrastructure_failure"}
    assert {t["error"] for t in record["trials"]} == {"time_limit"}
