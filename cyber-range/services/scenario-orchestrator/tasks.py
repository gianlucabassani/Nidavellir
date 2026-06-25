import os
import logging
import uuid
from datetime import datetime, timedelta

from celery import Celery

import config
import setup_phase
from database import Database
from orchestrator import Orchestrator
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
}

logger = logging.getLogger(__name__)

@app.task(name="deploy_lab", bind=True)
def deploy_lab(self, instance_id, scenario_name, user_id, variables=None, provider=None,
               scenario_config=None, setup_prearm=None):
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
    orch = Orchestrator(provider_name=provider)

    logger.info(f"[{instance_id}] Task received. Scenario: {scenario_name}")

    # 1. Update DB: Set status to deploying
    db.update_deployment(instance_id, status="deploying", actor="worker")

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
        db.update_deployment(
            instance_id, status="active", outputs=result["outputs"], actor="worker"
        )
        # SUT arenas: apply the setup config captured at creation. Best-effort —
        # a failure here must not fail the (successful) deploy; the operator can
        # still open setup manually.
        if setup_prearm:
            try:
                _open_prearmed_setup(db, provider, instance_id, result["outputs"], setup_prearm)
            except Exception:  # noqa: BLE001 - never fail an active deploy on this
                logger.exception(f"[{instance_id}] pre-armed setup auto-open failed")
    else:
        err = result.get("error", "unknown error")
        logger.error(f"[{instance_id}] Deployment failed ({result.get('phase', '?')}): {err}")
        db.update_deployment(instance_id, status="failed", error=err, actor="worker")
        # Audit trail for the failure — previously invisible in the events stream
        # (only a bare 'failed' status), which is why deploy failures were opaque.
        db.record_event(
            instance_id, "deploy_failed",
            {"provider": provider or "default",
             "phase": result.get("phase", "unknown"),
             "error_kind": result.get("error_kind"),
             "error": str(err)[:2000]},
            actor="worker",
        )

    return result


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

@app.task(name="destroy_lab")
def destroy_lab(instance_id):
    """
    Async Task: Destroys a laboratory environment.

    Destroy must run on the SAME provider the lab was deployed with (a
    docker lab can't be torn down by the openstack driver) — the provider
    name was recorded on the deployment at deploy time.
    """
    db = Database()
    record = db.get_deployment(instance_id) or {}
    orch = Orchestrator(provider_name=record.get("provider"))

    logger.info(f"[{instance_id}] Destroy task received.")
    
    # Update DB status before starting operation
    db.update_deployment(instance_id, status="destroying", actor="worker")
    
    result = orch.destroy(instance_id)
    
    if result["success"]:
        db.update_deployment(instance_id, status="destroyed", actor="worker")
    else:
        db.update_deployment(
            instance_id, status="error_destroying", error=result["error"], actor="worker"
        )

    return result


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
    stuck_before = now - timedelta(minutes=config.LAB_STUCK_MINUTES)

    candidates = db.find_reapable(now, stuck_before)
    reaped, skipped = 0, 0
    for lab in candidates:
        lab_id, reason, from_status = lab["id"], lab["reason"], lab["status"]
        try:
            # destroying->destroying is a legal no-op (a stuck destroy just
            # gets retried); pending/deploying/active->destroying are legal.
            db.update_deployment(lab_id, status=LabStatus.DESTROYING, actor="reaper")
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

    if reaped or skipped or revoked:
        logger.info(
            f"Reaper run: {reaped} reaped, {skipped} skipped, "
            f"{revoked} setup-egress revoked"
        )
    return {"reaped": reaped, "skipped": skipped, "setup_egress_revoked": revoked}


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
            orch = Orchestrator(provider_name=dep.get("provider"))
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