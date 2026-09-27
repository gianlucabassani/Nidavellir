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

from celery.exceptions import SoftTimeLimitExceeded

import bindings
import eval_export
import lifecycle_manifest
from database import Database
from states import LabStatus

# Worst case for one trial: its budget deadline plus deploy, readiness, validation and
# teardown. The task limit scales with the suite; stale recovery waits longer than one
# trial can legitimately take, because progress refreshes the evaluation heartbeat.
TRIAL_OVERHEAD_SECONDS = 600
STALL_MINUTES = 70


def time_limits(trial_count, deadline_seconds):
    soft = trial_count * (deadline_seconds + TRIAL_OVERHEAD_SECONDS) + 60
    return soft, soft + 60


# Below this many matched pairs a bootstrap interval is reported but labelled
# ``insufficient_pairs``; it is never ``supported``.
MIN_INTERVAL_PAIRS = 5


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


async def _play_mcp(arena_id, build, *, deadline_seconds=None):
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
                "provider": build["config"].get("provider", "scripted-mcp")})
            if announce.isError:
                raise RuntimeError("MCP agent announcement failed")
            if build["driver"] == "model-mcp/v1":
                import eval_model_driver  # noqa: PLC0415
                config = build["config"]
                connection = Database().get_decrypted_model_credential(
                    config["connection_owner"])
                if not connection or any(connection.get(key) != config.get(key)
                                         for key in ("provider", "model", "base_url")):
                    raise RuntimeError("pinned model connection unavailable or changed")
                def decode(response):
                    if response.structuredContent is not None:
                        return response.structuredContent
                    raw = next((block.text for block in response.content
                                if block.type == "text"), "{}")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return {"error": raw[:200]}
                effective = {**build, "config": {**config, "deadline_seconds": min(
                    config["deadline_seconds"], deadline_seconds or config["deadline_seconds"])}}
                return await eval_model_driver.run(session, arena_id, effective,
                                                   connection, decode)
            for step in build["config"]["plan"]:
                args = _substitute(step["args"], last_transaction)
                args["arena_id"] = arena_id
                response = await session.call_tool(step["tool"], arguments=args)
                value = response.structuredContent
                if value is None:
                    value = json.loads(next((block.text for block in response.content
                                             if block.type == "text"), "{}"))
                if step["tool"] == "browser_visit" and "expect_dom" in step:
                    if step["expect_dom"] not in value.get("rendered_dom", ""):
                        raise RuntimeError("browser DOM expectation failed")
                entry = {"tool": step["tool"], "ok": not response.isError}
                if step["tool"] == "browser_visit":
                    entry["dom_sha256"] = value.get("dom_sha256")
                transcript.append(entry)
                if response.isError:
                    raise RuntimeError(f"MCP step failed: {step['tool']}")
                if step["tool"] == "http_request":
                    last_transaction = value.get("transaction_digest")
    return {"transcript": transcript, "model_usage": [], "termination": "plan_complete"}


def _trial_result(db, arena_id, execution, challenge):
    import api  # noqa: PLC0415 - reuse the established operator scorer/export projection

    arena = db.get_deployment(arena_id)
    report = api._score_report(arena_id, arena, "benchmark")
    row = eval_export.build_eval_record(arena_id=arena_id, record=arena,
        scenario_meta=api._scenario_meta(arena.get("scenario")),
        score_report=report, events=db.list_events(arena_id, limit=None))
    row["metadata"]["nv.challenge_id"] = challenge["id"]
    row["metadata"]["nv.leakage_label"] = challenge["label"]
    row["metadata"]["nv.validator_version"] = challenge["validator_version"]
    row["tags"] = sorted(set(row["tags"] + [f"leakage:{challenge['label']}"]))
    usage = execution["model_usage"]
    if usage:
        input_tokens = [item.get("input_tokens") for item in usage]
        output_tokens = [item.get("output_tokens") for item in usage]
        row["metadata"]["model_calls"] = len(usage)
        row["metadata"]["input_tokens"] = (sum(input_tokens) if all(
            item is not None for item in input_tokens) else None)
        row["metadata"]["output_tokens"] = (sum(output_tokens) if all(
            item is not None for item in output_tokens) else None)
        row["metadata"]["tokens"] = (row["metadata"]["input_tokens"] +
            row["metadata"]["output_tokens"] if row["metadata"]["input_tokens"] is not None
            and row["metadata"]["output_tokens"] is not None else None)
        costs = [item.get("cost_usd") for item in usage]
        row["metadata"]["cost_usd"] = sum(costs) if all(
            item is not None for item in costs) else None
    findings = [e.get("payload") or {} for e in db.list_events(
        arena_id, limit=None, types=("finding",))]
    false_claims = sum(1 for f in findings if (f.get("validation") or {}).get(
        "verdict") == "refuted")
    requests = len(db.list_events(arena_id, limit=None, types=("http_request",)))
    return {"export": row, "false_claims": false_claims,
            "requests": requests, "transcript": execution["transcript"],
            "model_usage": usage, "termination": execution["termination"]}


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
        execution = asyncio.run(_play_mcp(arena_id, build,
                                         deadline_seconds=suite["deadline_seconds"]))
        return arena_id, after["observed_state_digest"], _trial_result(
            db, arena_id, execution, challenge)
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
        except SoftTimeLimitExceeded:
            db.finish_eval_trial(trial["id"], claim, state="infrastructure_failure",
                arena_id=arena_id, starting_digest=digest, error="time_limit")
            db.terminalize_unfinished_eval_trials(evaluation_id, error="time_limit")
            break
        except Exception as exc:  # noqa: BLE001 - infrastructure and agent failures are separate
            kind = "infrastructure_failure"
            db.finish_eval_trial(trial["id"], claim, state=kind,
                arena_id=arena_id, starting_digest=digest,
                error=f"{type(exc).__name__}: {exc}"[:500])
    db.set_evaluation_state(evaluation_id, "complete", expected="running")
    return {"evaluation_id": evaluation_id, "state": "complete"}


def compare(record):
    runs = {run["id"]: run for run in record["runs"]}
    challenges = {challenge["id"]: challenge for challenge in record.get("challenges", [])}
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
        label = (challenges.get(challenge_id) or {}).get("label", "unknown")
        rows.append({"challenge_id": challenge_id, "leakage_label": label,
                     "seed": seed, "matched": matched,
                     "baseline": metrics(baseline), "candidate": metrics(candidate),
                     "baseline_state": baseline and baseline["state"],
                     "candidate_state": candidate and candidate["state"]})
    valid = [row for row in rows if row["matched"]]
    def delta(metric, selected=None):
        selected = valid if selected is None else selected
        return [row["candidate"][metric] - row["baseline"][metric] for row in selected
                if row["candidate"].get(metric) is not None
                and row["baseline"].get(metric) is not None]

    def summary(values):
        if not values:
            return {"pairs": 0, "mean": None, "bootstrap_95": None,
                    "distinct_values": 0, "interval_status": "no_pairs"}
        rng = random.Random(7)
        means = sorted(sum(rng.choice(values) for _ in values) / len(values)
                       for _ in range(2000))
        distinct = len(set(values))
        # Resampling identical differences always returns the point estimate, so a
        # zero-width interval says nothing about stability; label it rather than let
        # the JSON read like the console-caveated interval without the caveat.
        status = ("degenerate" if distinct < 2 else "insufficient_pairs"
                  if len(values) < MIN_INTERVAL_PAIRS else "supported")
        return {"pairs": len(values), "mean": sum(values) / len(values),
                "bootstrap_95": [means[49], means[1949]],
                "distinct_values": distinct, "interval_status": status}

    differences = delta("verified")
    metrics = ("verified", "false_claims", "requests", "latency_seconds", "cost_usd")
    by_challenge = {}
    for challenge_id in sorted({row["challenge_id"] for row in rows}):
        challenge_rows = [row for row in rows if row["challenge_id"] == challenge_id]
        matched_rows = [row for row in challenge_rows if row["matched"]]
        challenge = challenges.get(challenge_id) or {}
        by_challenge[challenge_id] = {
            "name": challenge.get("name"), "version": challenge.get("version"),
            "leakage_label": challenge_rows[0]["leakage_label"],
            "matched_pairs": len(matched_rows),
            "infrastructure_failed_pairs": sum(1 for row in challenge_rows if
                "infrastructure_failure" in (row["baseline_state"], row["candidate_state"])),
            "differences": {metric: summary(delta(metric, matched_rows)) for metric in metrics},
        }
    labels = sorted({row["leakage_label"] for row in rows})
    evidence_scope = "held-out" if labels == ["held-out"] else "calibration_or_unknown"
    return {"pairs": rows, "leakage_labels": labels,
            "evidence_scope": evidence_scope, "by_challenge": by_challenge,
            "matched_pairs": len(valid),
            "infrastructure_failed_pairs": sum(1 for row in rows if
                "infrastructure_failure" in (row["baseline_state"], row["candidate_state"])),
            "differences": {metric: summary(delta(metric)) for metric in metrics},
            "verified_difference_mean": sum(differences) / len(differences)
            if differences else None, "verified_difference_range":
            [min(differences), max(differences)] if differences else None}
