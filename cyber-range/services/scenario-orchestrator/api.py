"""
FastAPI REST Layer - Production Architecture (Redis/Celery)
"""
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
import logging
import json
import uuid
import sys

import scenarios
from auth import Principal, ensure_bootstrap_key, require_principal
from database import Database
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


@app.get("/scenarios")
def list_scenarios(principal: Principal = Depends(require_principal)):
    """Registry of deployable scenarios (id + display metadata)."""
    return {"scenarios": scenarios.list_scenarios()}

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
            except:
                d['outputs'] = {}
        results[d['id']] = d
    return results

@app.post("/deploy")
async def deploy(req: DeployRequest, principal: Principal = Depends(require_principal)):
    """Queue deployment via Celery with Unique UUID"""

    # 1. Generate a Unique ID for the System (Primary Key)
    # (prevents collisions for same instanec name)
    system_id = str(uuid.uuid4())

    # 2. Treat User Input as a Friendly Name
    friendly_name = req.instance_id

    logger.info(
        f"Queuing deploy for {friendly_name} (System ID: {system_id}) "
        f"requested by '{principal.name}' ({principal.role})"
    )

    # 3. Create 'Pending' record in DB
    # id = UUID, user_id = Friendly Name
    db.create_deployment(system_id, friendly_name, req.scenario)

    # 4. Dispatch Async Task using the UUID
    deploy_lab.delay(
        instance_id=system_id, 
        scenario_name=req.scenario, 
        user_id=friendly_name,
        variables={}
    )
    
    return {"status": "accepted", "instance_id": system_id}

@app.delete("/destroy/{instance_id}")
async def destroy(instance_id: str, principal: Principal = Depends(require_principal)):
    """Queue destruction via Celery"""
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")

    logger.info(
        f"Queuing destroy for {instance_id} "
        f"requested by '{principal.name}' ({principal.role})"
    )
    
    db.update_deployment(instance_id, status="destroying")
    destroy_lab.delay(instance_id)
    
    return {"status": "accepted"}

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
        except:
            data["outputs"] = {}
            
    return data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)