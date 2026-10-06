#!/usr/bin/env python3
"""Run exactly one authorized Gemini calibration smoke from a prepared setup."""
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


def main(setup_path: Path) -> None:
    setup = json.loads(setup_path.read_text())
    if setup["schema"] != "nidavellir/nv07-r1-smoke-setup/v1" or setup["model_requests"]:
        raise RuntimeError("not an unused NV07-R1 setup")
    request = setup["proposed_request"]
    if (request["seed"], request["action_cap"], request["deadline_seconds"]) != (1, 12, 600):
        raise RuntimeError("smoke request exceeds the authorized scope")
    if nv07.fixture.api("GET", f"/status/{setup['source_arena']}")["status"] != "active":
        raise RuntimeError("source arena expired; prepare a new setup before asking permission")
    if nv07.fixture.api("GET", "/evaluations")["evaluations"]:
        raise RuntimeError("isolated stack already has an evaluation")

    # Exclusive attempt marker prevents this setup from issuing a second POST,
    # including when the first response is lost after the server accepts it.
    marker = setup_path.with_name(setup_path.stem + "-attempt.json")
    with marker.open("x") as handle:
        handle.write(json.dumps({"setup": setup_path.name, "request": request,
                                 "started_at": datetime.now().isoformat()}, indent=2) + "\n")
    evaluation_id = None
    record = None
    error = None
    try:
        submitted = nv07.fixture.api("POST", "/evaluation-smokes", request,
                                    expected=(202,))
        evaluation_id = submitted["id"]
        print(f"Submitted exactly one smoke: {evaluation_id}", flush=True)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            record = nv07.fixture.api("GET", f"/evaluations/{evaluation_id}")
            if record["state"] in {"complete", "failed"}:
                break
            time.sleep(2)
        else:
            raise RuntimeError("timed out waiting for the single smoke")
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
        trial_results = []
        for trial in (record or {}).get("trials", []):
            result = trial.get("result") or {}
            trial_results.append({"id": trial["id"], "arena_id": trial.get("arena_id"),
                                  "state": trial["state"],
                                  "error": trial.get("error"),
                                  "termination": result.get("termination"),
                                  "model_usage": result.get("model_usage"),
                                  "transcript": result.get("transcript"),
                                  "score": (result.get("export") or {}).get("score"),
                                  "metadata": (result.get("export") or {}).get("metadata")})
        try:
            nv07.fixture.cleanup_arenas()
        finally:
            nv07.fixture.run(*nv07.fixture.COMPOSE, "down", "--volumes",
                             "--remove-orphans", check=False)
        resources = {arena: nv07.fixture.inventory(arena) for arena in arenas}
        evidence = {"schema": "nidavellir/nv07-r1-smoke/v1",
                    "setup": setup_path.name, "attempt": marker.name,
                    "evaluation_id": evaluation_id, "state": (record or {}).get("state"),
                    "trials": trial_results, "error": error,
                    "final_resources": resources}
        path = setup_path.with_name(setup_path.stem.replace("-setup-", "-smoke-") + ".json")
        with path.open("x") as handle:
            handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        print(f"Smoke evidence: {path}", flush=True)
        print(f"State: {evidence['state']}; trials: {len(trial_results)}; error: {error}")
    if error:
        raise RuntimeError(error)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] != "--authorized":
        raise SystemExit("usage: run-nv07-r1-smoke.py SETUP_JSON --authorized")
    main(Path(sys.argv[1]))
