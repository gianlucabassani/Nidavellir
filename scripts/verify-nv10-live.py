#!/usr/bin/env python3
"""NV-10: encrypted recovery onto a fresh Docker-local PostgreSQL installation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("verify_nv09_live", Path(__file__).with_name("verify-nv09-live.py"))
nv09 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nv09)
fixture = nv09.fixture
fixture.COMPOSE = ("docker", "compose", "-f", "docker-compose.nv06.yml",
                   "-f", "docker-compose.nv07.yml", "-f", "docker-compose.nv10.yml")
PASSPHRASE = "nv10-" + uuid.uuid4().hex + uuid.uuid4().hex


def _maintenance(*args, workspace):
    return fixture.run(*fixture.COMPOSE, "run", "--rm", "--no-deps",
                       "-v", f"{workspace}:/recovery", "-e",
                       "NIDAVELLIR_RECOVERY_PASSPHRASE", "orchestrator", *args)


def main():
    os.environ["NV07_SECRETS_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["NIDAVELLIR_RECOVERY_PASSPHRASE"] = PASSPHRASE
    nv09.main()
    historical = fixture.api("GET", f"/evaluations/{nv09.evaluation_id}")
    old_trial = next(t for t in historical["trials"] if t["result"])
    old_id = old_trial["arena_id"]
    old_export = fixture.api("GET", f"/arenas/{old_id}/eval-export")
    old_status = fixture.api("GET", f"/status/{old_id}")
    assert old_status["outputs"], "historical output must be decryptable"
    resources_before = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
    assert not any(any(counts.values()) for counts in resources_before.values())

    with tempfile.TemporaryDirectory(prefix="nv10-bundle-") as workspace:
        fixture.run(*fixture.COMPOSE, "stop", "orchestrator", "worker", "webui", "agent-gateway")
        _maintenance("python", "recovery.py", "backup", "/recovery/full.nvr",
                     "--root", "/app", workspace=workspace)
        _maintenance("python", "recovery.py", "share", "/recovery/full.nvr",
                     "--output", "/recovery/share.json", workspace=workspace)
        bundle = Path(workspace) / "full.nvr"
        report = json.loads((Path(workspace) / "share.json").read_text())
        assert report["counts"]["evaluations"] >= 1
        assert old_id.encode() not in (Path(workspace) / "share.json").read_bytes()
        bundle_sha256 = hashlib.sha256(bundle.read_bytes()).hexdigest()
        bundle_bytes = bundle.stat().st_size
        fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans")

        # The second PostgreSQL service and all persistent volumes are fresh.
        os.environ["NV07_SECRETS_ENCRYPTION_KEY"] = ""
        fixture.run(*fixture.COMPOSE, "up", "-d", "--wait", "postgres", "redis")
        _maintenance("python", "-c", "from database import Database; Database()", workspace=workspace)
        _maintenance("python", "recovery.py", "restore", "/recovery/full.nvr",
                     "--root", "/app", workspace=workspace)
        saved = _maintenance("cat", "/app/keys/recovery.env", workspace=workspace).stdout.strip()
        assert saved.startswith("SECRETS_ENCRYPTION_KEY=")
        os.environ["NV07_SECRETS_ENCRYPTION_KEY"] = saved.split("=", 1)[1]
        fixture.run(*fixture.COMPOSE, "up", "-d", "orchestrator", "worker",
                    "webui", "agent-gateway")
        fixture.wait("/health", lambda data: data.get("status") == "ok")
        restored = fixture.api("GET", f"/evaluations/{nv09.evaluation_id}")
        assert restored["comparison"] == historical["comparison"]
        assert fixture.api("GET", f"/status/{old_id}")["outputs"] == old_status["outputs"]
        assert fixture.api("GET", f"/arenas/{old_id}/eval-export") == old_export
        old_finding = next(e["payload"] for e in fixture.api(
            "GET", f"/deployments/{old_id}/events")["events"] if e["type"] == "finding")
        digest = old_finding["validation"]["observation_digest"]
        assert fixture.api("GET", f"/arenas/{old_id}/validation-evidence/{digest}")

        # Re-run the pinned restored suite on the same locally built fixture image.
        replay = fixture.api("POST", "/evaluations", {
            "suite_id": historical["suite_id"], "baseline_id": historical["baseline_id"],
            "candidate_id": historical["candidate_id"]}, expected=(202,))
        rerun = fixture.wait(f"/evaluations/{replay['id']}",
                             lambda data: data.get("state") == "complete", timeout=1800)
        fixture.ARENAS.extend(t["arena_id"] for t in rerun["trials"] if t["arena_id"])
        if rerun["comparison"]["matched_pairs"] != historical["comparison"]["matched_pairs"]:
            print(json.dumps({"rerun_comparison": rerun["comparison"],
                              "trial_states": [(t["state"], t.get("error"))
                                               for t in rerun["trials"]]}, sort_keys=True), flush=True)
        assert rerun["comparison"]["matched_pairs"] == historical["comparison"]["matched_pairs"]
        assert rerun["comparison"]["infrastructure_failed_pairs"] == 0
        assert rerun["comparison"]["by_challenge"][next(iter(rerun["comparison"]["by_challenge"]))][
            "differences"]["verified"]["mean"] == -1
        for arena in fixture.ARENAS:
            assert fixture.wait(f"/status/{arena}",
                                lambda data: data.get("status") == "destroyed")
        resources = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
        assert not any(any(counts.values()) for counts in resources.values())
        evidence = {"schema": "nidavellir/nv10-live/v1",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "bundle_sha256": bundle_sha256, "bundle_bytes": bundle_bytes,
                    "historical_evaluation_id": nv09.evaluation_id,
                    "historical_arena_id": old_id, "rerun_evaluation_id": replay["id"],
                    "historical_comparison": historical["comparison"],
                    "rerun_comparison": rerun["comparison"],
                    "share_counts": report["counts"], "final_resources": resources}
        path = ROOT / "docs" / "verification" / (
            f"nv10-live-{datetime.now():%Y-%m-%d}-{uuid.uuid4().hex[:8]}.json")
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        print(f"NV-10 evidence: {path}")


if __name__ == "__main__":
    try:
        main()
    finally:
        fixture.cleanup_arenas()
        fixture.run(*fixture.COMPOSE, "down", "--volumes", "--remove-orphans", check=False)
        leftovers = {arena: fixture.inventory(arena) for arena in fixture.ARENAS}
        if any(any(counts.values()) for counts in leftovers.values()):
            raise RuntimeError(f"NV-10 cleanup left labelled resources: {leftovers}")
