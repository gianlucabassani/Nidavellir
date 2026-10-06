#!/usr/bin/env python3
"""Run exactly one authorized model-driven paired suite from a prepared setup."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_nv07_live", Path(__file__).with_name("verify-nv07-live.py"))
nv07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv07)
_smoke_spec = importlib.util.spec_from_file_location(
    "run_nv07_r1_smoke", Path(__file__).with_name("run-nv07-r1-smoke.py"))
smoke_run = importlib.util.module_from_spec(_smoke_spec)
_smoke_spec.loader.exec_module(smoke_run)

EXPECTED = ([1, 2, 3], 12, 600)
POLL_TIMEOUT = 5400


def main(setup_path: Path) -> None:
    setup = json.loads(setup_path.read_text())
    if setup["schema"] != "nidavellir/nv07-suite-setup/v1" or setup["model_requests"]:
        raise RuntimeError("not an unused NV07 suite setup")
    proposed = setup["proposed_evaluation"]
    if ((proposed["seeds"], proposed["action_cap"], proposed["deadline_seconds"])
            != EXPECTED):
        raise RuntimeError("suite request exceeds the authorized scope")
    if nv07.fixture.api("GET", f"/status/{setup['source_arena']}")["status"] != "active":
        raise RuntimeError("source arena expired; prepare a new setup before asking permission")
    if nv07.fixture.api("GET", "/evaluations")["evaluations"]:
        raise RuntimeError("isolated stack already has an evaluation")

    # Exclusive attempt marker binds this authorization to one evaluation:
    # a second attempt from the same setup is refused even if the first
    # response was lost after the server accepted it.
    marker = setup_path.with_name(setup_path.stem + "-attempt.json")
    with marker.open("x") as handle:
        handle.write(json.dumps({"setup": setup_path.name,
                                 "request": proposed,
                                 "started_at": datetime.now().isoformat()}, indent=2) + "\n")
    evaluation_id = None
    record = None
    error = None
    try:
        submitted = nv07.fixture.api("POST", "/evaluations", {
            "suite_id": proposed["suite_id"], "baseline_id": proposed["baseline_id"],
            "candidate_id": proposed["candidate_id"]}, expected=(202,))
        evaluation_id = submitted["id"]
        with marker.open("w") as handle:
            handle.write(json.dumps({"setup": setup_path.name, "request": proposed,
                                     "evaluation_id": evaluation_id,
                                     "started_at": datetime.now().isoformat()},
                                    indent=2) + "\n")
        print(f"Submitted exactly one suite: {evaluation_id}", flush=True)
        deadline = time.monotonic() + POLL_TIMEOUT
        while time.monotonic() < deadline:
            record = nv07.fixture.api("GET", f"/evaluations/{evaluation_id}")
            if record["state"] in {"complete", "failed"}:
                break
            time.sleep(5)
        else:
            raise RuntimeError("timed out waiting for the single suite")
    except (OSError, RuntimeError, KeyError) as exc:
        error = str(exc)
    finally:
        if evaluation_id and record is None:
            try:
                record = nv07.fixture.api("GET", f"/evaluations/{evaluation_id}")
            except (OSError, RuntimeError):
                pass
        arenas = [setup["source_arena"]]
        if record:
            arenas.extend(trial["arena_id"] for trial in record["trials"]
                          if trial.get("arena_id"))
        nv07.fixture.ARENAS.extend(arenas)
        trials = []
        for trial in (record or {}).get("trials", []):
            result = trial.get("result") or {}
            export = result.get("export") or {}
            meta = export.get("metadata") or {}
            usage = result.get("model_usage") or []
            calls, calls_error = smoke_run._http_calls(trial.get("arena_id")) \
                if trial.get("arena_id") else ([], None)
            entry = {"id": trial["id"], "arena_id": trial.get("arena_id"),
                     "run_id": trial.get("run_id"), "seed": trial.get("seed"),
                     "state": trial["state"], "error": trial.get("error"),
                     "termination": result.get("termination"),
                     "model_calls": len(usage),
                     "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
                     "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
                     "cost_usd": None if all(u.get("cost_usd") is None for u in usage)
                     else sum(u.get("cost_usd") or 0 for u in usage),
                     "model_usage": usage, "transcript": result.get("transcript"),
                     "http_calls": calls,
                     "score": (export.get("score") or {}).get("answer")
                     if isinstance(export.get("score"), dict)
                     else export.get("score"),
                     "pass_at_1": meta.get("pass@1"),
                     "metadata": meta}
            if calls_error:
                entry["http_calls_error"] = calls_error
            trials.append(entry)
        try:
            nv07.fixture.cleanup_arenas()
        finally:
            nv07.fixture.run(*nv07.fixture.COMPOSE, "down", "--volumes",
                             "--remove-orphans", check=False)
        resources = {arena: nv07.fixture.inventory(arena) for arena in arenas}
        comparison = (record or {}).get("comparison")
        evidence = {"schema": "nidavellir/nv07-suite/v1",
                    "setup": setup_path.name, "attempt": marker.name,
                    "evaluation_id": evaluation_id,
                    "state": (record or {}).get("state"),
                    "build_ids": setup["build_ids"],
                    "build_digests": setup["build_digests"],
                    "trials": trials, "comparison": comparison,
                    "error": error, "final_resources": resources}
        path = setup_path.with_name(
            setup_path.stem.replace("-setup-", "-suite-") + ".json")
        with path.open("x") as handle:
            handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        print(f"Suite evidence: {path}", flush=True)
        print(f"State: {evidence['state']}; trials: {len(trials)}; error: {error}")
    if error:
        raise RuntimeError(error)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] != "--authorized":
        raise SystemExit("usage: run-nv07-suite.py SETUP_JSON --authorized")
    main(Path(sys.argv[1]))
