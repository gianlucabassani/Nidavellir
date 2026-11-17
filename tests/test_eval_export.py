"""
M3 eval-export tests (ROADMAP M3, ADR-0010).

Covers the pure `eval_export.build_eval_record` projection: the convergent
dataset shape, the model+scaffold+cost tuple in metadata, ground truth in
expected_output, and honest attribution when the agent never announced.
"""
import eval_export
import scoring

MANIFEST = [{"id": "sqli", "title": "SQLi", "cwe": "CWE-89", "node": "victim", "points": 1}]


def _events(model="claude-fable-5", provider="anthropic", stance="attacker"):
    ev = [{"type": "agent_binding", "payload": {"agent_name": "a", "stance": stance}}]
    if model:
        ev.insert(0, {"type": "agent_session",
                      "payload": {"model": model, "provider": provider, "stance": stance}})
    return ev


def _report(manifest=MANIFEST, findings=None, signals=None, metrics=None, mode=None):
    return scoring.score_arena(
        arena_id="a1", scenario="container_web_pentest", manifest=manifest,
        findings=findings or [], signals=signals or [],
        run_metrics=metrics or {"steps": 3, "wall_clock_seconds": 12.0}, mode=mode,
    )


def _rec(scenario="container_web_pentest"):
    return {"id": "a1", "scenario": scenario, "provider": "docker-local"}


def test_record_has_convergent_shape():
    rec = eval_export.build_eval_record(
        arena_id="a1", record=_rec(),
        scenario_meta={"title": "Web Pentest", "difficulty": "easy", "tags": ["web", "dvwa"]},
        score_report=_report(), events=_events(),
    )
    assert set(rec) >= {"run_id", "input", "expected_output", "metadata", "tags",
                        "source_trace_id", "score"}
    assert rec["source_trace_id"] == "a1"


def test_metadata_carries_model_scaffold_cost_tuple():
    rec = eval_export.build_eval_record(
        arena_id="a1", record=_rec(), scenario_meta={"difficulty": "easy"},
        score_report=_report(metrics={"steps": 5, "wall_clock_seconds": 30.0,
                                      "tokens": 1200, "cost_usd": 0.04}),
        events=_events(model="claude-fable-5", provider="anthropic"),
    )
    m = rec["metadata"]
    assert m["gen_ai.request.model"] == "claude-fable-5"
    assert m["gen_ai.system"] == "anthropic"
    assert m["nv.stance"] == "attacker"
    assert m["steps"] == 5 and m["tokens"] == 1200 and m["cost_usd"] == 0.04
    assert m["nv.difficulty"] == "easy"
    assert m["attributed"] is True


def test_expected_output_is_ground_truth():
    rec = eval_export.build_eval_record(
        arena_id="a1", record=_rec(), scenario_meta=None,
        score_report=_report(), events=_events(),
    )
    assert rec["expected_output"]["known_vulnerabilities"] == MANIFEST
    assert rec["expected_output"]["mode"] == "benchmark"


def test_tags_include_mode_difficulty_and_cwes():
    rec = eval_export.build_eval_record(
        arena_id="a1", record=_rec(),
        scenario_meta={"difficulty": "easy", "tags": ["web"]},
        score_report=_report(), events=_events(),
    )
    assert "mode:benchmark" in rec["tags"]
    assert "difficulty:easy" in rec["tags"]
    assert "cwe:CWE-89" in rec["tags"]
    assert "web" in rec["tags"] and "nidavellir" in rec["tags"]


def test_pass_at_1_reflects_solved():
    solved_report = _report(findings=[{"matched_vuln_id": "sqli", "node": "victim",
                                       "validation": {"confirmed": True}}])
    rec = eval_export.build_eval_record(
        arena_id="a1", record=_rec(), scenario_meta=None,
        score_report=solved_report, events=_events(),
    )
    assert rec["metadata"]["pass@1"] == 1


def test_unannounced_agent_is_flagged_not_guessed():
    rec = eval_export.build_eval_record(
        arena_id="a1", record=_rec(), scenario_meta=None,
        score_report=_report(), events=_events(model=None),  # no agent_session
    )
    assert rec["metadata"]["gen_ai.request.model"] is None
    assert rec["metadata"]["attributed"] is False
    # stance still recovered from the binding event.
    assert rec["metadata"]["nv.stance"] == "attacker"


def test_discovery_run_exports_cleanly():
    rec = eval_export.build_eval_record(
        arena_id="a1", record=_rec(scenario="custom:sut"), scenario_meta=None,
        score_report=_report(manifest=[], signals=[{"kind": "crash", "node": "v", "key": "k"}]),
        events=_events(),
    )
    assert rec["metadata"]["nv.mode"] == "discovery"
    assert rec["expected_output"]["known_vulnerabilities"] == []
    assert "mode:discovery" in rec["tags"]
