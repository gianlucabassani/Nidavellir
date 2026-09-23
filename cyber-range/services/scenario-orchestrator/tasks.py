import os
import logging
import time
import uuid
from datetime import datetime, timedelta

from celery import Celery

import config
import bindings
import lifecycle_manifest
import monitor
import research_session
import setup_phase
from database import Database
from orchestrator import Orchestrator
from providers import resolve_provider_name
from states import IllegalTransition, LabStatus

# Broker Configuration
# Connects to Redis running on localhost by default
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

# Initialize Celery app
app = Celery('nidavellir', broker=REDIS_URL, backend=REDIS_URL)

# Celery Optimization Settings
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    task_track_started=True, # Allows tracking "started" state in addition to "pending/success"
    worker_concurrency=4,    # Number of concurrent worker threads (CPU)
)

# Celery-beat schedule: the lifecycle reaper (audit #9). The `beat` service
# (see docker-compose) ticks this; the worker runs the enqueued task.
app.conf.beat_schedule = {
    "reap-labs": {
        "task": "reap_labs",
        "schedule": float(config.REAPER_INTERVAL_SECONDS),
    },
    # M2 service-under-test monitor (ADR-0009): crash / sanitizer / 5xx /
    # resource-exhaustion oracle over every ACTIVE arena.
    "monitor-arenas": {
        "task": "monitor_arenas",
        "schedule": float(config.MONITOR_INTERVAL_SECONDS),
    },
}

# Event type for a recorded monitor signal (audit stream + defender feed + the
# M2 scorer's input).
MONITOR_EVENT = "monitor_signal"


@app.task(
    name="run_poc_job", bind=True, acks_late=True, reject_on_worker_lost=True,
    soft_time_limit=config.POC_MAX_TIMEOUT_SECONDS + 30,
    time_limit=config.POC_MAX_TIMEOUT_SECONDS + 60,
)
def run_poc_job(self, job_id):
    """Worker-owned confined execution. Interrupted jobs are never replayed."""
    db = Database()
    claim = getattr(self.request, "id", None) or uuid.uuid4().hex
    if not db.claim_poc_job(job_id, claim):
        job = db.get_poc_job(job_id) or {}
        return {"success": job.get("state") == "succeeded", "skipped": True,
                "state": job.get("state", "missing")}
    job = db.get_poc_job(job_id, include_payload=True)
    record = db.get_deployment(job["arena_id"]) or {}

    def cancelled():
        current = db.get_poc_job(job_id) or {}
        arena = db.get_deployment(job["arena_id"]) or {}
        budget = db.budget_status(job["arena_id"])
        return (bool(current.get("cancel_requested"))
                or arena.get("status") != LabStatus.ACTIVE
                or budget["system"]["state"] != "open"
                or not budget["arena"] or budget["arena"]["state"] != "open")

    policy_error = None
    if record.get("status") != LabStatus.ACTIVE:
        policy_error = "arena is no longer active"
    elif datetime.fromisoformat(job["deadline"]) <= datetime.now():
        policy_error = "PoC execution deadline expired before worker start"
    elif job["principal_role"] == "agent":
        events = db.list_events(
            job["arena_id"], limit=bindings.BINDING_EVENT_WINDOW,
            types=bindings.BINDING_EVENT_TYPES,
        )
        binding = bindings.binding_for(events, job["principal"])
        if binding is None or not bindings.stance_permits(binding.get("stance"), bindings.CAP_EXEC):
            policy_error = "agent binding was revoked or no longer permits execution"
        elif binding.get("paused"):
            policy_error = "agent binding is paused"
    if policy_error:
        result = {"error": policy_error}
        db.finish_poc_job(job_id, state="cancelled", result=result,
                          cleanup_state="not_started")
        db.record_event(job["arena_id"], "poc_job_cancelled",
                        {"job_id": job_id, "reason": policy_error}, actor="poc-worker")
        return {"success": False, **result}

    # The durable absolute deadline, rather than queue latency, bounds how long
    # the provider may run. Keep the API-selected timeout only when it is lower.
    remaining = max(1, int((datetime.fromisoformat(job["deadline"]) - datetime.now()).total_seconds()))
    effective_limits = {**job["limits"]}
    effective_limits["timeout_seconds"] = min(
        int(effective_limits["timeout_seconds"]), remaining
    )

    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    try:
        if job["payload"].get("primitive") in {"http", "browser"}:
            target = job["target_policy"]
            kind = job["payload"]["primitive"]
            try:
                if cancelled():
                    outcome = {"success": False, "state": "cancelled"}
                else:
                    method = orch.provider.http_request if kind == "http" else orch.provider.browser_visit
                    outcome = method(
                        job["arena_id"], target["node"], target["ip"],
                        target["port"], target["scheme"],
                        **job["payload"]["arguments"], job_id=job_id,
                        cancel_check=cancelled,
                        start_guard=lambda: db.helper_start_guard(job["arena_id"], job_id),
                    )
            finally:
                cleanup_result = orch.cleanup_poc_job(job_id)
            outcome["cleanup"] = cleanup_result
        else:
            outcome = orch.run_poc(
                job["arena_id"], job_id, job["payload"], job["target_policy"],
                effective_limits, cancel_check=cancelled,
                start_guard=lambda: db.helper_start_guard(job["arena_id"], job_id),
            )
    except NotImplementedError as exc:
        outcome = {"success": False, "state": "failed", "error": str(exc),
                   "cleanup": {"success": True}}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[%s/%s] PoC execution crashed", job["arena_id"], job_id)
        outcome = {"success": False, "state": "failed", "error": str(exc)[:2000],
                   "cleanup": {"success": False, "error": "worker execution crashed"}}

    cleanup = outcome.pop("cleanup", {}) or {}
    state = outcome.pop("state", "succeeded" if outcome.get("success") else "failed")
    if state not in {"succeeded", "failed", "timed_out", "cancelled"}:
        state = "failed"
    if not cleanup.get("success"):
        state = "failed"
    elif cancelled():
        state = "cancelled"
        outcome["success"] = False
        outcome["cancelled"] = True
    db.finish_poc_job(
        job_id, state=state, result=outcome,
        runner_image_id=outcome.get("runner_image_id"),
        cleanup_state="complete" if cleanup.get("success") else "incomplete",
        cleanup_error=cleanup.get("error"),
    )
    state = (db.get_poc_job(job_id) or {}).get("state", state)
    db.record_event(
        job["arena_id"], "poc_job_finished",
        {
            "job_id": job_id, "state": state, "input_digest": job["input_digest"],
            "exit_code": outcome.get("exit_code"),
            "stdout_sha256": outcome.get("stdout_sha256"),
            "stderr_sha256": outcome.get("stderr_sha256"),
            "artifact_digests": [a.get("sha256") for a in outcome.get("artifacts", [])],
            "cleanup_state": "complete" if cleanup.get("success") else "incomplete",
        },
        actor="poc-worker",
    )
    return {"success": state == "succeeded", "state": state}

logger = logging.getLogger(__name__)

@app.task(
    name="deploy_lab", bind=True, acks_late=True, reject_on_worker_lost=True,
    soft_time_limit=config.LAB_DEPLOY_TIMEOUT_SECONDS,
    time_limit=config.LAB_DEPLOY_TIMEOUT_SECONDS + 30,
)
def deploy_lab(self, instance_id, scenario_name, user_id, variables=None, provider=None,
               scenario_config=None, setup_prearm=None, effective_provider=None):
    """
    Async Task: Deploys a laboratory environment.
    bind=True allows access to the task instance (e.g., self.request.id).
    `provider` is the per-request provider name (None -> install default).
    `scenario_config` is an optional inline v3 topology (a custom/generated
    arena built from the catalog); when absent the named scenario is loaded.
    `setup_prearm` is an optional SUT setup config captured at creation (review
    1.1): once the arena is active, the configurator setup session is opened
    automatically from it instead of the operator wiring it up after the fact.
    """
    db = Database()
    runtime_provider = effective_provider or provider
    orch = Orchestrator(provider_name=runtime_provider)

    logger.info(f"[{instance_id}] Task received. Scenario: {scenario_name}")

    # Claim once. Duplicate delivery must not provision a second copy, and a
    # teardown that won the race must not be reversed by a late deploy task.
    if not db.transition_deployment(
        instance_id, (LabStatus.PENDING,), LabStatus.DEPLOYING, actor="worker"
    ):
        record = db.get_deployment(instance_id) or {}
        logger.warning("[%s] deploy skipped from state %s", instance_id, record.get("status"))
        return {"success": False, "error": "deployment is no longer pending", "skipped": True}

    # 2. Execute Deployment. Wrapped: a *raised* exception must not leave the arena
    # stuck in 'deploying' with no audit trail — turn it into an observable failure
    # exactly like a returned {success: False}.
    try:
        result = orch.deploy(
            scenario_name, instance_id, variables, scenario_config=scenario_config
        )
    except Exception as e:  # noqa: BLE001 - a crash becomes a recorded failure
        logger.exception(f"[{instance_id}] deploy task crashed")
        result = {"success": False, "error": f"deploy crashed: {e}",
                  "error_kind": type(e).__name__, "phase": "task"}

    # 3. Handle Result
    if result.get("success"):
        logger.info(f"[{instance_id}] Deployment successful. Updating DB.")
        recipe = db.get_lifecycle_recipe(instance_id)
        if recipe and recipe.get("readiness"):
            deadline = time.monotonic() + min(
                max(int(recipe["readiness"].get("timeout_seconds", 30)), 1), 120
            )
            readiness = {"ready": False, "status": "timeout"}
            while time.monotonic() < deadline:
                try:
                    readiness = orch.check_readiness(
                        instance_id, result["outputs"], recipe["readiness"]
                    )
                except Exception as exc:  # noqa: BLE001
                    readiness = {
                        "ready": False,
                        "status": "check_error",
                        "error": str(exc),
                    }
                    break
                if readiness.get("ready"):
                    break
                time.sleep(min(float(recipe["readiness"].get("interval_seconds", 1)), 5.0))
            try:
                runtime = orch.observe_lifecycle(instance_id)
            except Exception as exc:  # noqa: BLE001
                runtime = {"provider": provider, "observation_error": str(exc)}
                readiness = {
                    "ready": False,
                    "status": "observation_error",
                    "error": str(exc),
                }
            observed = lifecycle_manifest.observation(
                recipe=recipe, provider_observation=runtime, readiness_result=readiness
            )
            db.record_event(instance_id, "lifecycle_observation", observed, actor="worker")
            if not readiness.get("ready"):
                cleanup = orch.destroy(instance_id)
                err = f"application readiness failed: {readiness.get('error') or readiness.get('status')}"
                if not cleanup.get("success"):
                    err += f"; cleanup incomplete: {cleanup.get('error')}"
                _terminalize_deploy_failure(db, instance_id, err, cleanup)
                db.record_event(
                    instance_id, "deploy_failed",
                    {"provider": runtime_provider, "phase": "application_readiness", "error": err},
                    actor="worker",
                )
                return {"success": False, "error": err, "phase": "application_readiness"}
        db.update_deployment(instance_id, outputs=result["outputs"], actor="worker")
        if not db.transition_deployment(
            instance_id, (LabStatus.DEPLOYING,), LabStatus.ACTIVE, actor="worker"
        ):
            cleanup = orch.destroy(instance_id)
            logger.warning(
                "[%s] deployment completed after state changed; cleanup=%s", instance_id, cleanup
            )
            return {"success": False, "error": "deployment superseded by teardown"}
        preflight_ready = True
        if setup_prearm and setup_prearm.get("target_manifest"):
            preflight = research_session.evaluate_preflight(
                result["outputs"],
                setup_prearm["target_manifest"],
                include_attacker=bool(setup_prearm.get("include_attacker")),
                auto_build=bool(setup_prearm.get("auto_build")),
            )
            db.record_event(
                instance_id,
                research_session.PREFLIGHT_EVENT,
                preflight,
                actor="worker",
            )
            if not preflight["ready"]:
                preflight_ready = False
                logger.warning(
                    "[%s] research preflight failed: %s",
                    instance_id,
                    preflight["failed_checks"],
                )
        # SUT arenas: apply the setup config captured at creation. Best-effort —
        # a failure here must not fail the (successful) deploy; the operator can
        # still open setup manually.
        if (
            setup_prearm
            and setup_prearm.get("open_setup", True)
            and preflight_ready
        ):
            try:
                _open_prearmed_setup(db, provider, instance_id, result["outputs"], setup_prearm)
            except Exception:  # noqa: BLE001 - never fail an active deploy on this
                logger.exception(f"[{instance_id}] pre-armed setup auto-open failed")
    else:
        err = result.get("error", "unknown error")
        logger.error(f"[{instance_id}] Deployment failed ({result.get('phase', '?')}): {err}")
        cleanup = result.get("cleanup")
        if not isinstance(cleanup, dict):
            try:
                cleanup = orch.destroy(instance_id)
            except Exception as exc:  # noqa: BLE001
                cleanup = {"success": False, "error": f"cleanup crashed: {exc}"}
        if not cleanup.get("success"):
            err = f"{err}; cleanup incomplete: {cleanup.get('error', 'unknown error')}"
        _terminalize_deploy_failure(db, instance_id, err, cleanup)
        # Audit trail for the failure — previously invisible in the events stream
        # (only a bare 'failed' status), which is why deploy failures were opaque.
        db.record_event(
            instance_id, "deploy_failed",
            {"provider": runtime_provider or "default",
             "phase": result.get("phase", "unknown"),
             "error_kind": result.get("error_kind"),
             "error": str(err)[:2000]},
            actor="worker",
        )

    return result


def _terminalize_deploy_failure(db, instance_id, error, cleanup):
    """Record a failed deploy without hiding an outstanding cleanup obligation."""
    if cleanup.get("success"):
        db.transition_deployment(
            instance_id, (LabStatus.DEPLOYING,), LabStatus.FAILED, actor="worker"
        )
    else:
        db.transition_deployment(
            instance_id, (LabStatus.DEPLOYING,), LabStatus.DESTROYING, actor="worker"
        )
        db.transition_deployment(
            instance_id, (LabStatus.DESTROYING,), LabStatus.ERROR_DESTROYING,
            actor="worker",
        )
    db.update_deployment(instance_id, error=error, actor="worker")


def _open_prearmed_setup(db, provider, instance_id, outputs, prearm):
    """Open the configurator setup session for a freshly-active SUT arena from the
    config captured at creation. Scope = the victim (non-foothold) nodes; egress is
    opened best-effort (a provider that can't toggle it just runs setup locked)."""
    nodes, footholds = setup_phase.derive_nodes_footholds(outputs or {})
    scope = sorted(nodes - footholds)
    if not scope:
        logger.warning(f"[{instance_id}] pre-armed setup skipped: no victim node in scope")
        return
    now = datetime.now()
    session_id = uuid.uuid4().hex[:12]
    payload = setup_phase.make_session_payload(
        session_id, now, prearm["time_box_seconds"], scope,
        prearm["command_budget"], prearm["setup_egress"], prearm["mode"],
        prearm.get("actor", "operator"),
    )
    db.record_event(instance_id, setup_phase.SETUP_OPEN, payload, actor="worker")
    egress_open = False
    if prearm["setup_egress"]:
        orch = Orchestrator(provider_name=provider)
        opened = []
        for node in scope:
            try:
                res = orch.set_node_egress(instance_id, node, True)
                if res.get("success"):
                    opened.append(node)
            except NotImplementedError:
                logger.info(f"[{instance_id}] provider can't toggle egress — setup runs locked")
                break
            except Exception as e:  # noqa: BLE001 - best-effort; revoke is idempotent
                logger.warning(f"[{instance_id}] pre-armed setup egress on {node!r} failed: {e}")
        egress_open = bool(opened)
    logger.info(
        f"[{instance_id}] pre-armed setup session {session_id} opened "
        f"(mode={prearm['mode']} scope={scope} egress={'open' if egress_open else 'off'})"
    )

@app.task(
    name="destroy_lab", acks_late=True, reject_on_worker_lost=True,
    soft_time_limit=config.LAB_DESTROY_TIMEOUT_SECONDS,
    time_limit=config.LAB_DESTROY_TIMEOUT_SECONDS + 30,
)
def destroy_lab(instance_id):
    """
    Async Task: Destroys a laboratory environment.

    Destroy must run on the SAME provider the lab was deployed with (a
    docker lab can't be torn down by the openstack driver) — the provider
    name was recorded on the deployment at deploy time.
    """
    db = Database()
    db.request_cancel_arena_poc_jobs(instance_id)
    record = db.get_deployment(instance_id) or {}
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )

    logger.info(f"[{instance_id}] Destroy task received.")
    
    # API/reaper normally claimed DESTROYING already; direct/retried tasks may
    # claim a live state. A terminal record makes this task idempotent.
    if record.get("status") == LabStatus.DESTROYED:
        return {"success": True, "already_destroyed": True}
    if record.get("status") != LabStatus.DESTROYING:
        if not db.transition_deployment(
            instance_id,
            (LabStatus.PENDING, LabStatus.DEPLOYING, LabStatus.ACTIVE,
             LabStatus.FAILED, LabStatus.ERROR_DESTROYING),
            LabStatus.DESTROYING,
            actor="worker",
        ):
            return {"success": False, "error": "arena could not be claimed for destroy"}

    try:
        # A claimed PoC may still be inside a Docker create call when destroy
        # is requested. Wait for its finally/cleanup before inventory removal;
        # otherwise that late create can outlive a successful arena teardown.
        drain_deadline = time.monotonic() + config.POC_MAX_TIMEOUT_SECONDS + 65
        while any(job["state"] == "running" for job in db.list_poc_jobs(instance_id)):
            if time.monotonic() >= drain_deadline:
                raise RuntimeError("waiting for confined execution cleanup; destroy is retryable")
            time.sleep(0.1)
        result = orch.destroy(instance_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[%s] destroy task crashed", instance_id)
        result = {"success": False, "error": f"destroy crashed: {exc}"}
    
    if result["success"]:
        finalized = db.transition_deployment(
            instance_id, (LabStatus.DESTROYING,), LabStatus.DESTROYED, actor="worker"
        )
        if not finalized:
            current = db.get_deployment(instance_id) or {}
            if current.get("status") == LabStatus.ERROR_DESTROYING:
                db.transition_deployment(
                    instance_id, (LabStatus.ERROR_DESTROYING,), LabStatus.DESTROYING,
                    actor="worker",
                )
                db.transition_deployment(
                    instance_id, (LabStatus.DESTROYING,), LabStatus.DESTROYED,
                    actor="worker",
                )
    else:
        if db.transition_deployment(
            instance_id, (LabStatus.DESTROYING,), LabStatus.ERROR_DESTROYING,
            actor="worker",
        ):
            db.update_deployment(instance_id, error=result["error"], actor="worker")
        elif (db.get_deployment(instance_id) or {}).get("status") == LabStatus.DESTROYED:
            return {"success": True, "already_destroyed": True, "cleanup_race": True}

    return result


def _latest_observation(db, arena_id):
    events = db.list_events(arena_id, limit=1, types=("lifecycle_observation",))
    return events[0].get("payload") if events else None


@app.task(
    name="reset_arena", acks_late=True, reject_on_worker_lost=True,
    soft_time_limit=config.LAB_RESET_TIMEOUT_SECONDS,
    time_limit=config.LAB_RESET_TIMEOUT_SECONDS + 30,
)
def reset_arena(operation_id):
    """Replace an arena from its immutable recipe and compare observed state."""
    db = Database()
    operation = db.get_reset_operation(operation_id)
    if operation is None:
        return {"success": False, "error": "reset operation not found"}
    if operation["status"] in {"succeeded", "failed"}:
        return {"success": operation["status"] == "succeeded", "idempotent": True}
    if not db.claim_reset_operation(operation_id):
        operation = db.get_reset_operation(operation_id) or {}
        return {
            "success": operation.get("status") == "succeeded",
            "skipped": True,
            "status": operation.get("status", "missing"),
        }
    operation = db.get_reset_operation(operation_id)
    deadline = datetime.fromisoformat(operation["deadline"])
    if deadline <= datetime.now():
        db.update_reset_operation(
            operation_id, status="failed", stage="expired",
            error="reset deadline expired", terminal=True,
        )
        return {"success": False, "error": "reset deadline expired"}

    source_id = operation["source_id"]
    replacement_id = operation["replacement_id"]
    source = db.get_deployment(source_id) or {}
    replacement = db.get_deployment(replacement_id) or {}
    if not source or not replacement:
        db.update_reset_operation(
            operation_id, status="failed", stage="records",
            error="source or replacement deployment record is unavailable", terminal=True,
        )
        return {"success": False, "error": "reset deployment records unavailable"}
    recipe = db.get_lifecycle_recipe(source_id)
    if recipe is None or recipe.get("recipe_digest") != operation["recipe_digest"]:
        db.update_reset_operation(
            operation_id, status="failed", stage="recipe", error="immutable recipe unavailable",
            terminal=True,
        )
        return {"success": False, "error": "immutable recipe unavailable"}
    target = recipe.get("target") or {}
    authorization = target.get("authorization") or {}
    expires_at = source.get("expires_at")
    policy_error = None
    if (recipe.get("runtime_reset") or {}).get("status") != "eligible":
        policy_error = "immutable recipe is no longer reset-eligible"
    elif target and not authorization.get("confirmed"):
        policy_error = "target authorization is not confirmed"
    elif not expires_at or datetime.fromisoformat(expires_at) <= datetime.now():
        policy_error = "engagement deadline expired before reset execution"
    elif resolve_provider_name(recipe.get("effective_provider")) != recipe.get(
        "effective_provider"
    ):
        policy_error = "effective runtime provider no longer matches the recipe"
    if policy_error:
        db.update_reset_operation(
            operation_id, status="failed", stage="policy", error=policy_error, terminal=True
        )
        return {"success": False, "error": policy_error}

    if source.get("status") != LabStatus.DESTROYED:
        result = destroy_lab(source_id)
        if not result.get("success"):
            db.transition_deployment(
                replacement_id, (LabStatus.PENDING,), LabStatus.FAILED, actor="reset-worker"
            )
            db.update_reset_operation(
                operation_id, status="failed", stage="destroying_source",
                error=result.get("error"), terminal=True,
            )
            return result

    db.update_reset_operation(operation_id, stage="deploying_replacement")
    if replacement.get("status") == LabStatus.ACTIVE:
        deploy_result = {"success": True, "resumed": True}
    elif replacement.get("status") == LabStatus.PENDING:
        deploy_result = deploy_lab(
            replacement_id,
            recipe["scenario_name"],
            replacement.get("user_id"),
            variables={},
            provider=recipe["effective_provider"],
            scenario_config=recipe["scenario"],
            setup_prearm=None,
            effective_provider=recipe["effective_provider"],
        )
    else:
        deploy_result = {
            "success": False,
            "error": (
                "replacement cannot be resumed from state "
                f"{replacement.get('status', 'missing')}"
            ),
        }
    if not deploy_result.get("success"):
        db.update_reset_operation(
            operation_id, status="failed", stage="deploying_replacement",
            error=deploy_result.get("error"), terminal=True,
        )
        return deploy_result

    before = _latest_observation(db, source_id)
    after = _latest_observation(db, replacement_id)
    if not before or not after or not lifecycle_manifest.equivalent(before, after):
        result = {
            "equivalent": False,
            "source_observation": before and before.get("observed_state_digest"),
            "replacement_observation": after and after.get("observed_state_digest"),
        }
        db.record_event(replacement_id, "reset_mismatch", result, actor="reset-worker")
        cleanup = destroy_lab(replacement_id)
        if not cleanup.get("success"):
            result["cleanup_error"] = cleanup.get("error")
        db.update_reset_operation(
            operation_id, status="failed", stage="comparison",
            error="replacement starting state did not match source baseline",
            result=result, terminal=True,
        )
        return {"success": False, **result}

    result = {
        "equivalent": True,
        "source_id": source_id,
        "replacement_id": replacement_id,
        "observed_state_digest": after["observed_state_digest"],
    }
    db.record_event(source_id, "reset_replaced_by", result, actor="reset-worker")
    db.record_event(replacement_id, "reset_replacement_of", result, actor="reset-worker")
    db.update_reset_operation(
        operation_id, status="succeeded", stage="complete", result=result, terminal=True
    )
    return {"success": True, **result}


@app.task(name="reap_labs")
def reap_labs():
    """Lifecycle reaper (audit #9), ticked by Celery beat.

    Drives toward destruction any lab that should no longer be live:
    - **expired**: TTL (`expires_at`) elapsed;
    - **stuck**: sitting in a transient state with no live worker (the
      "stuck pending forever" failure — e.g. a worker lost on restart).

    Each reaped lab is transitioned to `destroying` (through the state
    machine, so illegal transitions are skipped, not forced), gets a
    `reaped` audit event recording the reason, and is handed to the normal
    `destroy_lab` task — which is idempotent and runs on the lab's recorded
    provider, so partial infrastructure is cleaned up too.
    """
    db = Database()
    now = datetime.now()
    for arena_id in db.expired_budget_arenas(now):
        db.stop_budget_gate(arena_id, actor="reaper", reason="wall-clock budget expired")
    for scope in db.stopping_budget_scopes():
        if scope == "system":
            for dep in db.list_deployments():
                db.request_cancel_arena_poc_jobs(dep["id"])
        else:
            db.request_cancel_arena_poc_jobs(scope)
    stuck_before = now - timedelta(minutes=config.LAB_STUCK_MINUTES)

    candidates = db.find_reapable(now, stuck_before)
    reaped, skipped = 0, 0
    for lab in candidates:
        lab_id, reason, from_status = lab["id"], lab["reason"], lab["status"]
        try:
            # destroying->destroying is a legal no-op (a stuck destroy just
            # gets retried); pending/deploying/active->destroying are legal.
            if not db.transition_deployment(
                lab_id, (from_status,), LabStatus.DESTROYING, actor="reaper"
            ):
                skipped += 1
                continue
            db.record_event(
                lab_id, "reaped", {"reason": reason, "from": from_status}, actor="reaper"
            )
            destroy_lab.delay(lab_id)
            reaped += 1
            logger.info(f"[{lab_id}] Reaped ({reason}, was {from_status}) -> destroying")
        except IllegalTransition as e:
            # Lab moved to a terminal state between query and action; leave it.
            skipped += 1
            logger.warning(f"[{lab_id}] Reap skipped: {e}")
        except Exception:  # noqa: BLE001 - one bad lab must not abort the sweep
            skipped += 1
            logger.exception(f"[{lab_id}] Reap failed")

    revoked = _revoke_expired_setup_egress(db, now)
    # A reset may have committed before its Celery message was published. Safe
    # duplicate enqueue is enough for pending operations; the task itself is
    # idempotent after terminalization.
    recovered_reset_ids = set(db.recover_stale_reset_operations(stuck_before))
    reset_requeued = 0
    for operation in db.list_reset_operations(active_only=True):
        if operation["status"] == "pending":
            if not (
                db.get_deployment(operation["source_id"])
                and db.get_deployment(operation["replacement_id"])
            ):
                db.update_reset_operation(
                    operation["id"], status="failed", stage="records",
                    error="source or replacement deployment record is unavailable",
                    terminal=True,
                )
                continue
            reset_arena.delay(operation["id"])
            reset_requeued += 1

    poc_stale_before = now - timedelta(seconds=config.POC_STALE_SECONDS)
    recovered_poc_ids = db.recover_stale_poc_jobs(poc_stale_before)
    poc_cleanup_failed = 0
    for job in db.list_poc_cleanup_obligations():
        job_id = job["id"]
        arena = db.get_deployment(job.get("arena_id")) or {}
        try:
            cleanup = Orchestrator(
                provider_name=arena.get("effective_provider") or arena.get("provider")
            ).cleanup_poc_job(job_id)
            db.record_poc_cleanup(
                job_id, success=bool(cleanup.get("success")), error=cleanup.get("error")
            )
            if not cleanup.get("success"):
                poc_cleanup_failed += 1
        except NotImplementedError:
            db.record_poc_cleanup(
                job_id, success=False, error="provider does not support PoC cleanup"
            )
            poc_cleanup_failed += 1
        except Exception as exc:  # noqa: BLE001
            db.record_poc_cleanup(job_id, success=False, error=str(exc)[:2000])
            poc_cleanup_failed += 1
            logger.exception("[%s] stale PoC cleanup failed", job_id)
    poc_requeued = 0
    for job in db.list_active_poc_jobs():
        if job["state"] == "queued":
            if datetime.fromisoformat(job["deadline"]) <= now:
                db.request_cancel_poc_job(job["id"])
            else:
                run_poc_job.delay(job["id"])
                poc_requeued += 1

    poc_budget_reconciled = db.reconcile_poc_budget_actions()

    for scope in db.stopping_budget_scopes():
        db.reconcile_budget_stop(scope)

    if reaped or skipped or revoked:
        logger.info(
            f"Reaper run: {reaped} reaped, {skipped} skipped, "
            f"{revoked} setup-egress revoked"
        )
    return {
        "reaped": reaped,
        "skipped": skipped,
        "setup_egress_revoked": revoked,
        "reset_requeued": reset_requeued,
        "reset_recovered": len(recovered_reset_ids),
        "poc_recovered": len(recovered_poc_ids),
        "poc_cleanup_failed": poc_cleanup_failed,
        "poc_requeued": poc_requeued,
        "poc_budget_reconciled": poc_budget_reconciled,
    }


def _revoke_expired_setup_egress(db, now):
    """Safety net (ADR-0007): close setup egress on any ACTIVE arena whose setup
    session has lapsed but was never finished. Bounds the abandoned-session
    window — the deterministic revokes are finish/expiry-on-next-step — so the
    arena runtime can't stay open to the internet into the engagement."""
    revoked = 0
    for dep in db.list_deployments():
        if dep.get("status") != LabStatus.ACTIVE:
            continue
        try:
            # Setup-lifecycle events only (not the newest-N of everything), so a
            # busy arena's engagement noise can't hide a lapsed-but-open session
            # from the reaper and leave its egress open (H1 — same fix as
            # api._setup_events).
            sess = setup_phase.current_session(
                db.list_events(
                    dep["id"], limit=setup_phase.SETUP_EVENT_WINDOW,
                    types=setup_phase.SETUP_EVENT_TYPES,
                )
            )
            if not sess or not sess.get("setup_egress"):
                continue
            if not setup_phase.is_expired(sess, now):
                continue
            orch = Orchestrator(
                provider_name=dep.get("effective_provider") or dep.get("provider")
            )
            for node in sess.get("nodes") or []:
                try:
                    orch.set_node_egress(dep["id"], node, False)
                except Exception:  # noqa: BLE001 - best-effort, idempotent
                    pass
            db.record_event(
                dep["id"], setup_phase.SETUP_FINISHED,
                {"session_id": sess.get("session_id"), "reason": "expired_reaped"},
                actor="reaper",
            )
            revoked += 1
            logger.info(f"[{dep['id']}] Reaper revoked lapsed setup egress")
        except Exception:  # noqa: BLE001 - one bad arena must not abort the sweep
            logger.exception(f"[{dep.get('id')}] setup-egress reap failed")
    return revoked


@app.task(name="monitor_arenas")
def monitor_arenas():
    """Service-under-test monitor (ROADMAP M2, ADR-0009), ticked by Celery beat.

    For every ACTIVE arena, gather each SUT node's runtime state + log tail from
    its provider, run the crash oracle (`monitor.detect_signals`), and append any
    NEW signal — crash / sanitizer abort / unhandled 5xx / resource exhaustion —
    to the append-only `events` stream as `monitor_signal`. Signals feed the
    defender stance and the M2 scorer: a crash on a target with no known-CVE
    manifest is still scored evidence. Dedup is by the signal `key` against the
    signals already recorded for the arena, so a persistent fault is recorded
    once, not on every tick. Best-effort: one bad arena never aborts the sweep;
    providers that can't introspect a workload (VM/cloud until M8) are skipped.
    """
    db = Database()
    scanned = recorded = 0
    for dep in db.list_deployments():
        if dep.get("status") != LabStatus.ACTIVE:
            continue
        instance_id = dep["id"]
        try:
            orch = Orchestrator(
                provider_name=dep.get("effective_provider") or dep.get("provider")
            )
            result = orch.collect_monitor_signals(instance_id)
        except NotImplementedError:
            continue  # provider can't introspect a running workload yet
        except Exception:  # noqa: BLE001 - one bad arena must not abort the sweep
            logger.exception(f"[{instance_id}] monitor collection failed")
            continue

        if not result.get("success"):
            logger.warning(
                f"[{instance_id}] monitor collection: {result.get('error', 'unknown error')}"
            )
            continue
        scanned += 1

        signals = monitor.detect_signals(result.get("observations"))
        if not signals:
            continue

        # Only record signals not already on the stream (dedup by `key`).
        seen = {
            (e.get("payload") or {}).get("key")
            for e in db.list_events(
                lab_id=instance_id, limit=config.MONITOR_EVENT_WINDOW, types=[MONITOR_EVENT]
            )
        }
        for sig in signals:
            if sig["key"] in seen:
                continue
            db.record_event(instance_id, MONITOR_EVENT, sig, actor="monitor")
            recorded += 1
            logger.info(
                f"[{instance_id}] monitor signal: {sig['kind']} on "
                f"{sig['node']} ({sig['severity']})"
            )

    if scanned or recorded:
        logger.info(f"Monitor run: {scanned} arena(s) scanned, {recorded} new signal(s)")
    return {"scanned": scanned, "recorded": recorded}
