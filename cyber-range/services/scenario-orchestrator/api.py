"""
FastAPI REST Layer - Production Architecture (Redis/Celery)
"""
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import logging
import json
import os
import uuid
import sys
from datetime import datetime, timedelta

import catalog
import config
import scenarios
from auth import Principal, ensure_bootstrap_key, require_principal
from database import Database
from providers import available_providers, infra_class_of
from states import IllegalTransition, LabStatus
from tasks import deploy_lab, destroy_lab
from config import validate_config



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

try:
    validate_config()
    logger.info("✅ Configuration validation passed")
except ValueError as e:
    logger.error(f"❌ Configuration error: {e}")
    logger.error("Fix your .env file or environment variables before starting")
    sys.exit(1)

app = FastAPI(title="Cyber Range Orchestrator")
db = Database()
ensure_bootstrap_key(db)

# Rate limiting (SECURITY #7): caps how fast one client can burn worker slots
# and cloud quota. Keyed by remote address until per-user quotas land (Phase 3).
# Tests disable it via RATE_LIMIT_ENABLED=false.
limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

RATE_LIMIT_DEPLOY = os.getenv("RATE_LIMIT_DEPLOY", "10/minute")
RATE_LIMIT_DESTROY = os.getenv("RATE_LIMIT_DESTROY", "30/minute")


@app.get("/health")
def health():
    """Unauthenticated liveness probe (used by the container healthcheck)."""
    return {"status": "ok"}

# Friendly names end up in logs, the UI, and (truncated) in cloud resource
# names — keep them to a safe slug. Scenario ids are additionally checked
# against the registry, which is also the path-traversal boundary.
INSTANCE_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,39}$"


class DeployRequest(BaseModel):
    scenario: str = Field(min_length=1, max_length=64)
    instance_id: str = Field(  # the user's friendly name, not the system UUID
        pattern=INSTANCE_NAME_PATTERN,
        description="Lowercase letters, digits and hyphens; max 40 chars",
    )
    # Optional per-request deployment backend; None -> the install default
    # (RANGE_PROVIDER / MOCK_MODE on the worker).
    provider: str | None = Field(default=None, max_length=32)

    @field_validator("scenario")
    @classmethod
    def scenario_must_be_registered(cls, value: str) -> str:
        if not scenarios.is_valid_scenario_id(value):
            raise ValueError(
                "invalid scenario id (lowercase letters, digits, '-' and '_' only)"
            )
        if value not in scenarios.scenario_ids():
            raise ValueError(f"unknown scenario '{value}' — see GET /scenarios")
        return value

    @field_validator("provider")
    @classmethod
    def provider_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in available_providers():
            raise ValueError(
                f"unknown provider '{value}' — see GET /providers"
            )
        return value


def _check_provider_compatibility(scenario_id: str, provider_name: str | None):
    """Reject vm-scenarios on container backends (and vice versa) up front."""
    if provider_name is None:
        return
    meta = next(s for s in scenarios.list_scenarios() if s["id"] == scenario_id)
    needed = meta["provider_class"]
    offered = infra_class_of(provider_name)
    if needed != "any" and offered not in ("any", needed):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Scenario '{scenario_id}' requires {needed}-class "
                f"infrastructure but provider '{provider_name}' "
                f"provides {offered}"
            ),
        )


class CustomArenaRequest(BaseModel):
    """Build a custom arena from curated catalog picks (manual scenario creator)."""

    instance_id: str = Field(pattern=INSTANCE_NAME_PATTERN)
    attacker: str = Field(min_length=1, max_length=64)
    victims: list[str] = Field(min_length=1, max_length=8)
    # Custom arenas are container topologies → docker-local by default.
    provider: str | None = Field(default="docker-local", max_length=32)

    @field_validator("provider")
    @classmethod
    def provider_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in available_providers():
            raise ValueError(f"unknown provider '{value}' — see GET /providers")
        return value


@app.get("/scenarios")
def list_scenarios(principal: Principal = Depends(require_principal)):
    """Registry of deployable scenarios (id + display metadata)."""
    return {"scenarios": scenarios.list_scenarios()}


@app.get("/catalog")
def get_catalog(kind: str | None = None, principal: Principal = Depends(require_principal)):
    """Curated attacker/victim images for the manual scenario creator."""
    return {"images": catalog.list_catalog(kind)}


@app.post("/arenas/custom")
@limiter.limit(RATE_LIMIT_DEPLOY)
async def deploy_custom_arena(
    request: Request,
    req: CustomArenaRequest,
    principal: Principal = Depends(require_principal),
):
    """Compile catalog picks into a validated v3 topology and queue it.

    The topology is built server-side from the whitelist (no arbitrary image
    strings), validated, then dispatched as an inline scenario — so a custom
    arena never touches the scenario registry/filesystem.
    """
    try:
        spec = catalog.build_custom_scenario(req.instance_id, req.attacker, req.victims)
    except catalog.CatalogError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # Custom arenas are container-class; refuse a non-container backend up front.
    offered = infra_class_of(req.provider) if req.provider else "any"
    if offered not in ("any", "container"):
        raise HTTPException(
            status_code=422,
            detail=f"provider '{req.provider}' provides {offered}-class infra, not container",
        )

    system_id = str(uuid.uuid4())
    label = f"custom:{req.attacker}+{'+'.join(req.victims)}"[:64]
    expires_at = datetime.now() + timedelta(minutes=config.LAB_TTL_MINUTES)
    db.create_deployment(
        system_id, req.instance_id, label,
        provider=req.provider, actor=principal.name, expires_at=expires_at,
    )
    logger.info(
        f"Queuing custom arena '{req.instance_id}' ({system_id}): "
        f"{label} provider={req.provider} by '{principal.name}'"
    )
    deploy_lab.delay(
        instance_id=system_id,
        scenario_name=label,
        user_id=req.instance_id,
        variables={},
        provider=req.provider,
        scenario_config=spec,
    )
    return {"status": "accepted", "instance_id": system_id}


@app.get("/providers")
def list_providers(principal: Principal = Depends(require_principal)):
    """Available deployment backends and the infrastructure class they serve."""
    return {
        "providers": [
            {"name": name, "infra_class": infra_class_of(name)}
            for name in available_providers()
        ]
    }

@app.get("/deployments")
def list_deployments(principal: Principal = Depends(require_principal)):
    """List all labs from SQLite"""
    deployments_list = db.list_deployments()
    results = {}
    for d in deployments_list:
        # SQLite stores JSON as string; parse it back to a dictionary
        if isinstance(d['outputs'], str):
            try:
                d['outputs'] = json.loads(d['outputs'])
            except json.JSONDecodeError:
                logger.warning(f"Corrupt outputs JSON for deployment {d['id']}")
                d['outputs'] = {}
        results[d['id']] = d
    return results

@app.post("/deploy")
@limiter.limit(RATE_LIMIT_DEPLOY)
async def deploy(
    request: Request,
    req: DeployRequest,
    principal: Principal = Depends(require_principal),
):
    """Queue deployment via Celery with Unique UUID"""

    _check_provider_compatibility(req.scenario, req.provider)

    # 1. Generate a Unique ID for the System (Primary Key)
    # (prevents collisions for same instanec name)
    system_id = str(uuid.uuid4())

    # 2. Treat User Input as a Friendly Name
    friendly_name = req.instance_id

    logger.info(
        f"Queuing deploy for {friendly_name} (System ID: {system_id}) "
        f"provider={req.provider or 'default'} "
        f"requested by '{principal.name}' ({principal.role})"
    )

    # 3. Create 'Pending' record in DB
    # id = UUID, user_id = Friendly Name; provider recorded so destroy
    # later runs on the same backend; expires_at gives the reaper a TTL.
    expires_at = datetime.now() + timedelta(minutes=config.LAB_TTL_MINUTES)
    db.create_deployment(
        system_id,
        friendly_name,
        req.scenario,
        provider=req.provider,
        actor=principal.name,
        expires_at=expires_at,
    )

    # 4. Dispatch Async Task using the UUID
    deploy_lab.delay(
        instance_id=system_id,
        scenario_name=req.scenario,
        user_id=friendly_name,
        variables={},
        provider=req.provider,
    )

    return {"status": "accepted", "instance_id": system_id}

@app.delete("/destroy/{instance_id}")
@limiter.limit(RATE_LIMIT_DESTROY)
async def destroy(
    request: Request,
    instance_id: str,
    principal: Principal = Depends(require_principal),
):
    """Queue destruction via Celery"""
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        db.update_deployment(
            instance_id, status=LabStatus.DESTROYING, actor=principal.name
        )
    except IllegalTransition as e:
        # e.g. the lab is already destroyed — nothing to tear down
        raise HTTPException(status_code=409, detail=str(e)) from e

    logger.info(
        f"Queuing destroy for {instance_id} "
        f"requested by '{principal.name}' ({principal.role})"
    )
    destroy_lab.delay(instance_id)

    return {"status": "accepted"}

# Records in these states describe infrastructure that no longer exists (or
# never came up) — only they may be deleted from history. Live labs must go
# through DELETE /destroy first.
DELETABLE_STATES = ("destroyed", "failed", "error_destroying")


@app.delete("/deployments/{instance_id}")
@limiter.limit(RATE_LIMIT_DESTROY)
async def delete_deployment_record(
    request: Request,
    instance_id: str,
    principal: Principal = Depends(require_principal),
):
    """Remove a terminal (destroyed/failed) lab record from history."""
    data = db.get_deployment(instance_id)
    if not data:
        raise HTTPException(status_code=404, detail="Instance not found")
    if data["status"] not in DELETABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete a lab in status '{data['status']}' — "
                f"destroy it first (deletable states: {', '.join(DELETABLE_STATES)})"
            ),
        )

    db.delete_deployment(instance_id, actor=principal.name)
    logger.info(
        f"Deleted deployment record {instance_id} "
        f"requested by '{principal.name}' ({principal.role})"
    )
    return {"status": "deleted"}


@app.delete("/deployments")
@limiter.limit(RATE_LIMIT_DESTROY)
async def purge_deployment_records(
    request: Request,
    principal: Principal = Depends(require_principal),
):
    """Remove ALL terminal (destroyed/failed) lab records from history."""
    deleted = db.purge_deployments(DELETABLE_STATES, actor=principal.name)
    logger.info(
        f"Purged {deleted} archived deployment record(s) "
        f"requested by '{principal.name}' ({principal.role})"
    )
    return {"status": "purged", "deleted": deleted}


@app.get("/status/{instance_id}")
def get_status(instance_id: str, principal: Principal = Depends(require_principal)):
    """Get status from SQLite"""
    data = db.get_deployment(instance_id)
    if not data:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    outputs = data.get("outputs", {})
    if isinstance(outputs, str):
        try:
            data["outputs"] = json.loads(outputs)
        except json.JSONDecodeError:
            logger.warning(f"Corrupt outputs JSON for deployment {instance_id}")
            data["outputs"] = {}

    return data

if __name__ == "__main__":
    import uvicorn
    # Containerized service: must bind all interfaces; exposure is governed
    # by the compose port mapping / firewall, not the bind address.
    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104