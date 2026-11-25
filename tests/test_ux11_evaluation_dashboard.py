"""UX-11/UX-12: evaluation dashboard data, suite history, the evaluation push
stream and trial comparison aligned by step."""
from __future__ import annotations

import json
import time
import uuid

import pytest

import api
import experiments
import spans
import streams
from database import Database
from tests.research_support import client


def _build(db, name):
    return db.create_agent_build(name=name, version="v1", digest=f"sha256:{name}",
        driver="scripted-mcp/v1", config={"plan": [], "model": "scripted"})


def _challenge(db, label="calibration"):
    return db.create_eval_challenge(name=f"authz-{label}", version="v1",
        scenario="nv06", source_arena_id="source", recipe_digest="sha256:recipe",
        validator_version="nidavellir/validation-verdict/v1", label=label)


@pytest.fixture
def evaluation(monkeypatch):
    """One paired evaluation (2 builds × 1 challenge × 2 seeds), closed afterwards
    so no queued row leaks into later reaper tests."""
    monkeypatch.setattr(api, "enqueue_evaluation", lambda *_: None)
    db = Database()
    created = []

    def make(suite=None, baseline=None, candidate=None):
        baseline = baseline or _build(db, f"baseline-{uuid.uuid4().hex}")
        candidate = candidate or _build(db, f"candidate-{uuid.uuid4().hex}")
        suite = suite or db.create_eval_suite(name="authz", version="v1",
            challenge_ids=[_challenge(db)["id"]], seeds=[1, 2],
            action_cap=20, deadline_seconds=600)
        record = db.create_evaluation(suite_id=suite["id"], baseline_id=baseline["id"],
                                      candidate_id=candidate["id"])
        created.append(record["id"])
        return db.get_evaluation(record["id"]), suite, baseline, candidate

    yield make
    for evaluation_id in created:
        db.set_evaluation_state(evaluation_id, "complete")


def _by_side(record):
    sides = {run["id"]: run["side"] for run in record["runs"]}
    return {(sides[t["run_id"]], t["seed"]): t for t in record["trials"]}


def _finish(db, trial, *, passed, arena=None, digest="sha256:start"):
    claim = uuid.uuid4().hex
    assert db.claim_eval_trial(trial["id"], claim)
    if arena:
        assert db.assign_eval_trial_arena(trial["id"], claim, arena)
    if passed is None:
        return db.finish_eval_trial(trial["id"], claim, state="infrastructure_failure",
                                    error="readiness failed")
    return db.finish_eval_trial(trial["id"], claim, state="completed",
        starting_digest=digest, result={"false_claims": 0, "requests": 1,
            "export": {"metadata": {"pass@1": 1 if passed else 0}}})


def _tool(db, arena, name, body, **attrs):
    spans.record(db, name=name, kind="tool", actor="byo-agent", actor_kind="agent",
                 arena_id=arena, input=body, attrs={"http.method": "POST", **attrs})


# --- step alignment (FR-17) --------------------------------------------------


def _steps(*calls):
    return experiments.trial_steps([
        {"kind": "tool", "actor_kind": "agent", "name": name, "span_id": f"s{i}",
         "input_digest": spans.digest(body), "attrs": {}}
        for i, (name, body) in enumerate(calls)])


def test_candidate_without_http_tool_never_issues_the_baseline_request():
    recon = ("exec", {"command": "curl -s target/"})
    request = ("http/request", {"method": "GET", "url": "http://target/admin"})
    finding = ("findings/submit", {"title": "admin without auth"})
    baseline = _steps(recon, request, finding)
    candidate = _steps(recon, ("exec", {"command": "nmap target"}), finding)
    result = experiments.align(baseline, candidate)
    assert result["first_divergence"] == 1
    assert [s["relation"] for s in result["steps"]] == ["same", "different_tool", "same"]
    assert result["only_in_a"] == [1] and result["only_in_b"] == [1]
    assert result["tools_only_in_a"] == ["http/request"]
    assert result["tools_only_in_b"] == []


def test_alignment_reports_input_changes_length_and_identity():
    a = _steps(("exec", {"command": "id"}), ("exec", {"command": "ls"}))
    b = _steps(("exec", {"command": "id"}), ("exec", {"command": "ls -la"}),
               ("exec", {"command": "whoami"}))
    result = experiments.align(a, b)
    assert [s["relation"] for s in result["steps"]] == [
        "same", "different_input", "only_b"]
    assert result["first_divergence"] == 1
    assert experiments.align(a, a)["first_divergence"] is None


def test_steps_are_agent_tool_calls_only():
    rows = [{"kind": "tool", "actor_kind": "human", "name": "exec"},
            {"kind": "model", "actor_kind": "agent", "name": "model.call"},
            {"kind": "tool", "actor_kind": "agent", "name": "exec", "attrs": {
                "nv.transaction_digest": "sha256:t", "http.status_code": 200}}]
    steps = experiments.trial_steps(rows)
    assert len(steps) == 1 and steps[0]["index"] == 0
    assert steps[0]["transaction_digest"] == "sha256:t"


# --- usage and history (FR-16) -------------------------------------------------


def test_usage_counts_agent_actions_and_leaves_unmeasured_tokens_empty():
    usage = experiments.trial_usage({
        "a": [{"kind": "tool", "actor_kind": "agent"},
              {"kind": "tool", "actor_kind": "human"},
              {"kind": "model", "attrs": {"gen_ai.usage.input_tokens": 100,
                                          "gen_ai.usage.output_tokens": 20}}],
        "b": [{"kind": "tool", "actor_kind": "agent"}]})
    assert usage["a"] == {"actions": 1, "tokens": 120}
    assert usage["b"] == {"actions": 1, "tokens": None}


def _record(eid, at, label, trials):
    return {"id": eid, "created_at": at,
            "runs": [{"id": "r", "build_id": "b1", "challenge_id": "c", "side": "baseline"}],
            "challenges": [{"id": "c", "label": label}],
            "trials": [{"run_id": "r", "seed": seed, "state": state,
                        "result": None if passed is None else {
                            "export": {"metadata": {"pass@1": passed}}}}
                       for seed, state, passed in trials]}


def test_history_separates_scopes_flags_flaky_seeds_and_never_scores_failures():
    records = [
        _record("e2", "2026-11-02", "calibration", [(1, "completed", 0),
                                                    (2, "infrastructure_failure", None)]),
        _record("e1", "2026-11-01", "calibration", [(1, "completed", 1), (2, "completed", 1)]),
        _record("e3", "2026-11-03", "held-out", [(1, "infrastructure_failure", None)]),
    ]
    data = experiments.history(records)
    series = {(s["build_id"], s["scope"]): s["points"] for s in data["series"]}
    assert set(series) == {("b1", "calibration"), ("b1", "held-out")}
    calibration = series[("b1", "calibration")]
    assert [p["evaluation_id"] for p in calibration] == ["e1", "e2"]
    assert calibration[0]["pass_rate"] == 1.0
    assert calibration[1]["pass_rate"] == 0.0 and calibration[1]["completed"] == 1
    assert calibration[1]["infrastructure_failures"] == 1
    held_out = series[("b1", "held-out")][0]
    assert held_out["pass_rate"] is None and held_out["infrastructure_failures"] == 1
    assert data["flaky"] == [{"build_id": "b1", "challenge_id": "c", "seed": 1,
        "verdicts": [{"evaluation_id": "e1", "passed": True},
                     {"evaluation_id": "e2", "passed": False}]}]


# --- the push stream ---------------------------------------------------------------


def test_trial_state_changes_publish_one_evaluation_notice(evaluation, monkeypatch):
    sent = []

    class Redis:
        def publish(self, channel, message):
            sent.append((channel, message))

    monkeypatch.setattr(streams, "_client", Redis())
    db = Database()
    record, *_ = evaluation()
    trial = record["trials"][0]
    channel = streams.EVALUATION_CHANNEL.format(record["id"])
    assert (channel, "changed") in sent  # creating it is a change too
    sent.clear()
    claim = uuid.uuid4().hex
    assert db.claim_eval_trial(trial["id"], claim)
    assert sent.count((channel, "changed")) == 1
    assert not db.claim_eval_trial(trial["id"], "other")  # no change, no notice
    assert sent.count((channel, "changed")) == 1
    db.finish_eval_trial(trial["id"], claim, state="infrastructure_failure", error="x")
    db.set_evaluation_state(record["id"], "running")
    assert sent.count((channel, "changed")) == 3


def test_evaluation_frames_push_progress_and_end_when_finished(monkeypatch):
    monkeypatch.setattr(streams, "KEEPALIVE_SECONDS", 0.05)
    states = iter(["running", "running", "complete"])

    class PubSub:
        def __init__(self):
            self.queue = [{"type": "message"}, None, {"type": "message"}]

        def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
            item = self.queue.pop(0) if self.queue else None
            if item is None:
                time.sleep(timeout)
            return item

        def close(self):
            pass

    frames = list(streams.board_frames(lambda: {"state": next(states)},
        name="evaluation", subscribe=PubSub, min_interval=0.01, max_seconds=5,
        done=lambda s: s["state"] == "complete"))
    payloads = [json.loads(f.split("data: ", 1)[1]) for f in frames
                if f.startswith("event: evaluation")]
    assert [p["state"] for p in payloads] == ["running", "running", "complete"]


def test_evaluation_stream_route_is_operator_only_and_ends_for_finished(evaluation):
    record, *_ = evaluation()
    Database().set_evaluation_state(record["id"], "complete")
    operator = client("operator")
    response = operator.get(f"/evaluations/{record['id']}/stream")
    assert response.status_code == 200
    assert "event: evaluation" in response.text and '"state": "complete"' in response.text
    assert client("agent").get(f"/evaluations/{record['id']}/stream").status_code == 403
    assert operator.get("/evaluations/missing/stream").status_code == 404


# --- endpoints -----------------------------------------------------------------------


def test_compare_endpoint_aligns_two_trials_with_findings_and_verdicts(evaluation):
    db = Database()
    record, *_ = evaluation()
    trials = _by_side(record)
    arena_a, arena_b = f"ux12-a-{uuid.uuid4().hex}", f"ux12-b-{uuid.uuid4().hex}"
    _finish(db, trials[("baseline", 1)], passed=True, arena=arena_a)
    _finish(db, trials[("candidate", 1)], passed=False, arena=arena_b)
    _tool(db, arena_a, "exec", {"command": "id"})
    _tool(db, arena_a, "http/request", {"url": "http://target/admin"},
          **{"nv.transaction_digest": "sha256:tx"})
    _tool(db, arena_b, "exec", {"command": "id"})
    db.record_event(arena_a, "finding", {"finding_id": "f1", "title": "admin open",
        "validation": {"verdict": "confirmed"}}, actor="byo-agent")
    operator = client("operator")
    a, b = trials[("baseline", 1)]["id"], trials[("candidate", 1)]["id"]
    data = operator.get(f"/evaluations/{record['id']}/compare",
                        params={"a": a, "b": b}).json()
    assert data["same_start"] is True
    assert data["first_divergence"] == 1
    assert data["tools_only_in_a"] == ["http/request"]
    assert data["steps"][1]["a"]["transaction_digest"] == "sha256:tx"
    assert data["steps"][1]["b"] is None
    assert data["a"]["passed"] is True and data["b"]["passed"] is False
    assert data["a"]["findings"] == [{"id": "f1", "title": "admin open",
                                      "verdict": "confirmed"}]
    other = trials[("baseline", 2)]["id"]
    assert operator.get(f"/evaluations/{record['id']}/compare",
                        params={"a": a, "b": "nope"}).status_code == 404
    assert operator.get(f"/evaluations/{record['id']}/compare",
                        params={"a": a, "b": a}).status_code == 422
    assert client("agent").get(f"/evaluations/{record['id']}/compare",
                               params={"a": a, "b": other}).status_code == 403


def test_evaluation_detail_carries_per_trial_actions_and_tokens(evaluation):
    db = Database()
    record, *_ = evaluation()
    trials = _by_side(record)
    arena = f"ux11-{uuid.uuid4().hex}"
    _finish(db, trials[("baseline", 1)], passed=True, arena=arena)
    _tool(db, arena, "exec", {"command": "id"})
    spans.record(db, name="model.call", kind="model", actor="m", actor_kind="agent",
                 arena_id=arena, attrs={"gen_ai.usage.input_tokens": 7,
                                        "gen_ai.usage.output_tokens": 3})
    detail = client("operator").get(f"/evaluations/{record['id']}").json()
    by_id = {t["id"]: t for t in detail["trials"]}
    assert by_id[trials[("baseline", 1)]["id"]]["usage"] == {"actions": 1, "tokens": 10}
    assert by_id[trials[("candidate", 1)]["id"]]["usage"] is None


def test_suite_history_endpoint_names_builds_and_is_operator_only(evaluation):
    db = Database()
    first, suite, baseline, candidate = evaluation()
    second, *_ = evaluation(suite=suite, baseline=baseline, candidate=candidate)
    _finish(db, _by_side(first)[("baseline", 1)], passed=True)
    _finish(db, _by_side(second)[("baseline", 1)], passed=False)
    data = client("operator").get(f"/eval-suites/{suite['id']}/history").json()
    assert data["evaluations"] == 2
    assert data["builds"][baseline["id"]]["name"] == baseline["name"]
    assert data["flaky"][0]["build_id"] == baseline["id"]
    assert data["challenges"][data["flaky"][0]["challenge_id"]].startswith("authz-")
    assert client("agent").get(f"/eval-suites/{suite['id']}/history").status_code == 403
    assert client("operator").get("/eval-suites/missing/history").status_code == 404
