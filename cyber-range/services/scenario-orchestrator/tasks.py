import os
import logging
from datetime import datetime, timedelta

from celery import Celery

import config
from database import Database
from orchestrator import Orchestrator
from states import IllegalTransition, LabStatus

# Broker Configuration
# Connects to Redis running on localhost by default
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

# Initialize Celery app
app = Celery('cyberguard', broker=REDIS_URL, backend=REDIS_URL)

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
def deploy_lab(self, instance_id, scenario_name, user_id, variables=None, provider=None):
    """
    Async Task: Deploys a laboratory environment.
    bind=True allows access to the task instance (e.g., self.request.id).
    `provider` is the per-request provider name (None -> install default).
    """
    db = Database()
    orch = Orchestrator(provider_name=provider)

    logger.info(f"[{instance_id}] Task received. Scenario: {scenario_name}")
    
    # 1. Update DB: Set status to deploying
    db.update_deployment(instance_id, status="deploying", actor="worker")
    
    # 2. Execute Deployment
    result = orch.deploy(scenario_name, instance_id, variables)
    
    # 3. Handle Result
    if result["success"]:
        logger.info(f"[{instance_id}] Deployment successful. Updating DB.")
        db.update_deployment(
            instance_id, status="active", outputs=result["outputs"], actor="worker"
        )
    else:
        logger.error(f"[{instance_id}] Deployment failed. Error: {result['error']}")
        db.update_deployment(
            instance_id, status="failed", error=result["error"], actor="worker"
        )
        
    return result

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

    if reaped or skipped:
        logger.info(f"Reaper run: {reaped} reaped, {skipped} skipped")
    return {"reaped": reaped, "skipped": skipped}