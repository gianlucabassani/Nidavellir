"""Durable worker ownership for synchronous HTTP/browser API contracts."""
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta

import config
from database import Database


def execute(record, kind, target, arguments, principal=None):
    # Import lazily: tasks imports providers and this module is also used by API.
    from tasks import run_poc_job

    db = Database()
    payload = {"primitive": kind, "arguments": arguments}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timeout = max(config.HEADLESS_BROWSER_TIMEOUT_SECONDS + 12,
                  config.HTTP_TIMEOUT_SECONDS + 8)
    job_id = str(uuid.uuid4())
    expires = record.get("expires_at")
    deadline = datetime.now() + timedelta(seconds=timeout + 30)
    if expires:
        deadline = min(deadline, datetime.fromisoformat(expires))
    job, _ = db.create_poc_job(
        job_id=job_id, arena_id=record["id"],
        principal=principal.name if principal else "validation-worker",
        principal_role=principal.role if principal else "operator", binding_stance=None,
        idempotency_key=f"{kind}-{job_id}",
        input_digest="sha256:" + hashlib.sha256(encoded).hexdigest(), payload=payload,
        runner_image=config.HEADLESS_BROWSER_IMAGE if kind == "browser" else config.HTTP_RUNNER_IMAGE,
        target_node=target["node"], target_policy=target,
        limits={"timeout_seconds": timeout}, deadline=deadline,
        max_arena_jobs=config.POC_MAX_ARENA_JOBS, max_global_jobs=config.POC_MAX_GLOBAL_JOBS,
    )
    db.record_event(record["id"], "helper_job_submitted", {
        "job_id": job_id, "kind": kind, "input_digest": job["input_digest"],
        "node": target["node"],
    }, actor=job["principal"])
    run_poc_job.delay(job_id)
    wait_until = time.monotonic() + timeout + 4
    while time.monotonic() < wait_until:
        job = db.get_poc_job(job_id)
        if job["state"] not in {"queued", "running"}:
            result = job.get("result") or {"success": False, "error": job["state"]}
            if job["cleanup_state"] == "incomplete":
                return {"success": False, "error": "helper cleanup is pending reconciliation"}
            return result
        time.sleep(0.05)
    db.request_cancel_poc_job(job_id)
    return {"success": False, "error": "helper deadline exceeded; cancellation requested"}
