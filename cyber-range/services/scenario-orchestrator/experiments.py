"""NV-07 paired scripted-MCP execution and comparison.

Only the worker invokes ``execute``. Trial results are operator-only records;
participant calls still enter through the stance-scoped MCP gateway.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import uuid
from datetime import datetime, timedelta

import bindings
import eval_export
import lifecycle_manifest
from database import Database
from states import LabStatus


def _observation(db, arena_id):
    events = db.list_events(arena_id, limit=1, types=("lifecycle_observation",))
    return events[0]["payload"] if events else None


def _substitute(value, last_transaction):
    if value == "$last_transaction_digest":
        if not last_transaction:
            raise ValueError("script references a missing HTTP transaction")
        return last_transaction
    if isinstance(value, list):
        return [_substitute(item, last_transaction) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, last_transaction) for key, item in value.items()}
    return value


async def _play_mcp(arena_id, build):
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import streamablehttp_client  # noqa: PLC0415

    url = os.getenv("EVAL_GATEWAY_URL", "http://agent-gateway:9000/mcp")
    transcript = []
    last_transaction = None
    async with streamablehttp_client(url) as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            announce = await session.call_tool("announce_agent", arguments={
                "arena_id": arena_id, "model": build["config"]["model"],
                "provider": "scripted-mcp"})
            if announce.isError:
                raise RuntimeError("MCP agent announcement failed")
            for step in build["config"]["plan"]:
                args = _substitute(step["args"], last_transaction)
                args["arena_id"] = arena_id
                response = await session.call_tool(step["tool"], arguments=args)
                value = response.structuredContent
                if value is None:
                    value = json.loads(next((block.text for block in response.content
                                             if block.type == "text"), "{}"))
                transcript.append({"tool": step["tool"], "ok": not response.isError})
                if response.isError:
                    raise RuntimeError(f"MCP step failed: {step['tool']}")
                if step["tool"] == "http_request":
                    last_transaction = value.get("transaction_digest")
    return transcript


def _trial_result(db, arena_id, transcript):
    import api  # noqa: PLC0415 - reuse the established operator scorer/export projection

    arena = db.get_deployment(arena_id)
    report = api._score_report(arena_id, arena, "benchmark")
    row = eval_export.build_eval_record(arena_id=arena_id, record=arena,
        scenario_meta=api._scenario_meta(arena.get("scenario")),
        score_report=report, events=db.list_events(arena_id, limit=None))
    findings = [e.get("payload") or {} for e in db.list_events(
        arena_id, limit=None, types=("finding",))]
    false_claims = sum(1 for f in findings if (f.get("validation") or {}).get(
        "verdict") == "refuted")
    requests = len(db.list_events(arena_id, limit=None, types=("http_request",)))
    return {"export": row, "false_claims": false_claims,
            "requests": requests, "transcript": transcript}


def _run_trial(db, trial, run, challenge, build, suite, claim):
    from tasks import deploy_lab, destroy_lab  # noqa: PLC0415

    source_id = challenge["source_arena_id"]
    source = db.get_deployment(source_id)
    recipe = db.get_lifecycle_recipe(source_id)
    before = _observation(db, source_id)
    if not source or not recipe or not before or recipe["recipe_digest"] != challenge[
            "recipe_digest"] or (recipe.get("runtime_reset") or {}).get("status") != "eligible":
        raise RuntimeError("pinned challenge source is unavailable or changed")
    if source["effective_provider"] != "docker-local":
        raise RuntimeError("challenge provider is unsupported")
    arena_id = str(uuid.uuid4())
    if not db.assign_eval_trial_arena(trial["id"], claim, arena_id):
        raise RuntimeError("trial claim lost before arena creation")
    expires_at = datetime.now() + timedelta(seconds=suite["deadline_seconds"])
    db.create_deployment(arena_id, f"eval-{trial['seed']}-{run['side']}",
        recipe["scenario_name"], provider=recipe.get("requested_provider"),
        actor="evaluation-worker", expires_at=expires_at,
        effective_provider="docker-local")
    db.save_lifecycle_recipe(arena_id, recipe)
    db.configure_eval_budget(arena_id, action_cap=suite["action_cap"], deadline=expires_at)
    try:
        deployed = deploy_lab(arena_id, recipe["scenario_name"],
            f"eval-{trial['seed']}-{run['side']}", variables={},
            provider=recipe.get("requested_provider"), scenario_config=recipe["scenario"],
            effective_provider="docker-local")
        if not deployed.get("success"):
            raise RuntimeError("trial deployment failed")
        after = _observation(db, arena_id)
        if not after or not lifecycle_manifest.equivalent(before, after):
            raise RuntimeError("observed starting state differs from pinned source")
        principal = os.getenv("EVAL_GATEWAY_PRINCIPAL", "bootstrap")
        db.record_event(arena_id, bindings.BINDING_GRANT,
            {"agent_name": principal, "stance": "attacker", "auto": False,
             "granted_by": "evaluation-worker"}, actor="evaluation-worker")
        transcript = asyncio.run(_play_mcp(arena_id, build))
        return arena_id, after["observed_state_digest"], _trial_result(
            db, arena_id, transcript)
    finally:
        if (db.get_deployment(arena_id) or {}).get("status") == LabStatus.ACTIVE:
            db.transition_deployment(arena_id, (LabStatus.ACTIVE,), LabStatus.DESTROYING,
                                     actor="evaluation-worker")
            destroy_lab(arena_id)


def execute(evaluation_id, claim):
    db = Database()
    if not db.set_evaluation_state(evaluation_id, "running", expected="queued"):
        return {"skipped": True}
    record = db.get_evaluation(evaluation_id)
    suite = db.get_eval_suite(record["suite_id"])
    runs = {run["id"]: run for run in record["runs"]}
    for trial in record["trials"]:
        run = runs[trial["run_id"]]
        challenge = db.get_eval_challenge(run["challenge_id"])
        build = db.get_agent_build(run["build_id"])
        if not db.claim_eval_trial(trial["id"], claim):
            continue
        arena_id = digest = None
        try:
            arena_id, digest, result = _run_trial(db, trial, run, challenge, build, suite, claim)
            db.finish_eval_trial(trial["id"], claim, state="completed",
                arena_id=arena_id, starting_digest=digest, result=result)
        except Exception as exc:  # noqa: BLE001 - infrastructure and agent failures are separate
            kind = "infrastructure_failure"
            db.finish_eval_trial(trial["id"], claim, state=kind,
                arena_id=arena_id, starting_digest=digest,
                error=f"{type(exc).__name__}: {exc}"[:500])
    db.set_evaluation_state(evaluation_id, "complete", expected="running")
    return {"evaluation_id": evaluation_id, "state": "complete"}


def compare(record):
    runs = {run["id"]: run for run in record["runs"]}
    pairs = {}
    for trial in record["trials"]:
        run = runs[trial["run_id"]]
        key = (run["challenge_id"], trial["seed"])
        pairs.setdefault(key, {})[run["side"]] = trial
    rows = []
    for (challenge_id, seed), pair in sorted(pairs.items()):
        baseline, candidate = pair.get("baseline"), pair.get("candidate")
        matched = bool(baseline and candidate and baseline["state"] == "completed"
                       and candidate["state"] == "completed" and
                       baseline["starting_digest"] == candidate["starting_digest"])
        def metrics(trial):
            if not trial or not trial.get("result"):
                return None
            result = trial["result"]
            meta = result["export"].get("metadata") or {}
            return {"verified": meta.get("pass@1"), "false_claims": result["false_claims"],
                    "requests": result["requests"], "latency_seconds": meta.get(
                        "wall_clock_seconds"), "cost_usd": meta.get("cost_usd")}
        rows.append({"challenge_id": challenge_id, "seed": seed, "matched": matched,
                     "baseline": metrics(baseline), "candidate": metrics(candidate),
                     "baseline_state": baseline and baseline["state"],
                     "candidate_state": candidate and candidate["state"]})
    valid = [row for row in rows if row["matched"]]
    def delta(metric):
        return [row["candidate"][metric] - row["baseline"][metric] for row in valid
                if row["candidate"].get(metric) is not None
                and row["baseline"].get(metric) is not None]

    def summary(values):
        if not values:
            return {"pairs": 0, "mean": None, "bootstrap_95": None}
        rng = random.Random(7)
        means = sorted(sum(rng.choice(values) for _ in values) / len(values)
                       for _ in range(2000))
        return {"pairs": len(values), "mean": sum(values) / len(values),
                "bootstrap_95": [means[49], means[1949]]}

    differences = delta("verified")
    return {"pairs": rows, "matched_pairs": len(valid),
            "infrastructure_failed_pairs": sum(1 for row in rows if
                "infrastructure_failure" in (row["baseline_state"], row["candidate_state"])),
            "differences": {metric: summary(delta(metric)) for metric in
                            ("verified", "false_claims", "requests", "latency_seconds",
                             "cost_usd")},
            "verified_difference_mean": sum(differences) / len(differences)
            if differences else None, "verified_difference_range":
            [min(differences), max(differences)] if differences else None}
