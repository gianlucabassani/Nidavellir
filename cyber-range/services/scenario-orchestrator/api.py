"""
FastAPI REST Layer - Production Architecture (Redis/Celery)
"""
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import logging
import base64
import asyncio
import difflib
import hashlib
import json
import os
import re
import shlex
import subprocess
import uuid
import sys
import urllib.parse
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

import requests

import bindings
import build_planner
import catalog
import config
import dockerfile_synth
import evidence_artifact
import eval_export
import generator
import http_transactions
import helper_jobs
import image_check
import images
import lifecycle_manifest
import model_chat
import model_verify
import netguard
import oci_intake
import poc_execution
import repo_introspect
import research_session
import scenarios
import scoring
import setup_phase
import setup_proposer
import source_bundle
import validators
import validation_evidence
import vulhub_import
from auth import Principal, ensure_bootstrap_key, hash_api_key, require_principal
from database import Database, StopDenied
from orchestrator import Orchestrator
from providers import (
    available_providers,
    default_provider_name,
    get_provider,
    infra_class_of,
    resolve_provider_name,
)
from scenario_spec import ScenarioSpec, normalize_cwe, normalized_nodes, topology_view
from states import IllegalTransition, LabStatus
from tasks import deploy_lab, destroy_lab, reset_arena, run_forward_stream, run_poc_job
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


@app.exception_handler(StopDenied)
async def system_stop_denied_handler(_request: Request, exc: StopDenied):
    return Response(content=json.dumps({"detail": str(exc)}), status_code=423,
                    media_type="application/json")


def _budgeted_path(path: str, method: str) -> str | None:
    """Only target-affecting writes consume an action; control and reads do not."""
    if method != "POST":
        return None
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "arenas":
        return None
    suffix = "/".join(parts[2:])
    if (suffix in {"reset", "destroy", "stop", "resume"}
            or suffix.startswith("bindings/") or suffix == "bindings"
            or suffix.endswith("/cancel")):
        return None
    charged = ("exec", "mitm/observe", "browser/visit", "http/request",
               "files/upload", "files/download", "findings",
               "findings/manual", "setup/step", "setup/upload", "setup/run",
               "setup/propose", "setup/generate-proposals")
    if (suffix in charged
            or (suffix.startswith("http/transactions/") and suffix.endswith("/replay"))
            or (suffix.startswith("setup/proposals/") and suffix.endswith("/approve"))
            or (suffix.startswith("workspaces/") and suffix.endswith("/patch-artifacts"))
            or (suffix.startswith("findings/") and suffix.endswith("/verify"))):
        return parts[1]
    return None


@app.middleware("http")
async def durable_budget_boundary(request: Request, call_next):
    arena_id = _budgeted_path(request.url.path, request.method)
    if arena_id is None:
        if (request.method == "POST" and request.url.path.endswith("/poc-jobs")
                and (request.headers.get("X-Token-Budget")
                     or request.headers.get("X-Cost-Budget"))):
            return Response(content=json.dumps({
                "detail": "token/cost caps cannot be enforced for this driver"
            }), status_code=422, media_type="application/json")
        return await call_next(request)
    from auth import hash_api_key

    key = request.headers.get("X-API-Key")
    principal = db.get_api_key(hash_api_key(key)) if key else None
    if principal is None:  # leave authentication error to the normal dependency
        return await call_next(request)
    arena = db.get_deployment(arena_id)
    if arena is None or arena.get("status") != "active":
        # Preserve the existing route's 404/409 response. The reservation gate
        # repeats this check transactionally for an arena that changes state.
        return await call_next(request)
    if principal["role"] == "agent":
        suffix = request.url.path.partition(f"/arenas/{arena_id}/")[2]
        if suffix == "findings/manual" or suffix.endswith("/verify"):
            return await call_next(request)
        capability = (bindings.CAP_OBSERVE if suffix == "mitm/observe" else
                      bindings.CAP_SETUP if suffix.startswith("setup/") else
                      bindings.CAP_WORKSPACE if suffix.startswith("workspaces/") else
                      bindings.CAP_EXEC)
        try:
            _require_binding(Principal(principal["name"], "agent"), arena_id, capability)
        except HTTPException:
            return await call_next(request)
    if request.headers.get("X-Token-Budget") or request.headers.get("X-Cost-Budget"):
        return Response(
            content=json.dumps({"detail": "token/cost caps cannot be enforced for this driver"}),
            status_code=422, media_type="application/json",
        )
    body = await request.body()
    digest = hashlib.sha256(request.method.encode() + request.url.path.encode() + body).hexdigest()
    action_key = request.headers.get("X-Action-Key") or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", action_key):
        return Response(content='{"detail":"invalid X-Action-Key"}', status_code=422,
                        media_type="application/json")
    try:
        action_id, deadline = db.reserve_budget_action(
            arena_id, key=action_key, digest=digest,
            kind=request.url.path.partition(f"/arenas/{arena_id}/")[2],
            actor=principal["name"],
        )
    except ValueError as exc:
        detail = str(exc)
        code = 429 if "budget exhausted" in detail else 423
        return Response(content=json.dumps({"detail": detail}), status_code=code,
                        media_type="application/json")
    request.state.budget_deadline = deadline
    try:
        response = await call_next(request)
    except Exception:
        db.settle_budget_action(action_id, outcome="unknown")
        raise
    outcome = ("spent" if response.status_code < 400 else
               "released" if response.status_code < 500 else "unknown")
    db.settle_budget_action(action_id, outcome=outcome)
    response.headers["X-Action-ID"] = action_id
    return response

RATE_LIMIT_DEPLOY = os.getenv("RATE_LIMIT_DEPLOY", "10/minute")
RATE_LIMIT_DESTROY = os.getenv("RATE_LIMIT_DESTROY", "30/minute")
# Exec runs in an agent loop → more frequent than deploy/destroy.
RATE_LIMIT_EXEC = os.getenv("RATE_LIMIT_EXEC", "120/minute")
# Cap exec output returned over the API (the provider caps harder at source).
EXEC_OUTPUT_CAP = 16384
# Setup-step output persisted in the `setup_step` event (the configurator console).
# Smaller than EXEC — these accumulate one per step across a setup session.
SETUP_OUTPUT_CAP = 4000


@app.get("/health")
def health():
    """Unauthenticated liveness probe (used by the container healthcheck)."""
    return {"status": "ok"}

# Friendly names end up in logs, the UI, and (truncated) in cloud resource
# names — keep them to a safe slug. Scenario ids are additionally checked
# against the registry, which is also the path-traversal boundary.
INSTANCE_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,39}$"
ENGAGEMENT_PURPOSES = frozenset({"benchmark", "discovery", "calibration", "research"})
ENGAGEMENT_PARTICIPANT_MODES = frozenset({"operator", "agent", "mixed"})


class EngagementIntentRequest(BaseModel):
    """Optional GUI intent shared by every deployment request.

    Compatibility clients may omit it. When present, the API validates and
    records it as immutable audit context; it does not override scenario or
    provider policy.
    """

    engagement_purpose: str | None = Field(default=None, max_length=32)
    participant_mode: str | None = Field(default=None, max_length=16)
    engagement_time_box_seconds: int | None = Field(
        default=None,
        ge=300,
        le=86400,
    )
    token_budget: int | None = Field(default=None, ge=1)
    cost_budget_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def reject_unenforceable_model_budgets(self):
        if self.token_budget is not None or self.cost_budget_usd is not None:
            raise ValueError("token/cost caps cannot be enforced for an external agent driver")
        return self

    @field_validator("engagement_purpose")
    @classmethod
    def engagement_purpose_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in ENGAGEMENT_PURPOSES:
            raise ValueError(
                "engagement_purpose must be benchmark, discovery, calibration, or research"
            )
        return value

    @field_validator("participant_mode")
    @classmethod
    def participant_mode_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in ENGAGEMENT_PARTICIPANT_MODES:
            raise ValueError("participant_mode must be operator, agent, or mixed")
        return value


def _engagement_expires_at(request_model: EngagementIntentRequest) -> datetime:
    if request_model.engagement_time_box_seconds is not None:
        return datetime.now() + timedelta(seconds=request_model.engagement_time_box_seconds)
    return datetime.now() + timedelta(minutes=config.LAB_TTL_MINUTES)


def _record_engagement_intent(
    instance_id: str,
    request_model: EngagementIntentRequest,
    principal: Principal,
    *,
    source: str,
) -> None:
    if request_model.engagement_purpose is None:
        return
    db.record_event(
        instance_id,
        "engagement_intent",
        {
            "schema": "nidavellir.engagement-intent/v1",
            "purpose": request_model.engagement_purpose,
            "source": source,
            "participant_mode": request_model.participant_mode or "unspecified",
            "time_box_seconds": request_model.engagement_time_box_seconds,
            "containment": "provider_enforced",
            "monitoring": "automatic",
            "scoring": "automatic",
        },
        actor=principal.name,
    )


def _record_lifecycle_recipe(
    deployment_id: str,
    *,
    scenario_name: str,
    scenario_config: dict,
    requested_provider: str | None,
    expires_at: datetime,
    target_manifest: dict | None = None,
    setup: dict | None = None,
) -> dict:
    lifecycle = scenario_config.get("lifecycle") or {}
    recipe = lifecycle_manifest.build_recipe(
        scenario=scenario_config,
        scenario_name=scenario_name,
        requested_provider=requested_provider,
        effective_provider=resolve_provider_name(requested_provider),
        target_manifest=target_manifest,
        expires_at=expires_at.isoformat(),
        readiness=lifecycle.get("readiness"),
        seed=lifecycle.get("seed"),
        setup=setup,
    )
    db.save_lifecycle_recipe(deployment_id, recipe)
    db.record_event(
        deployment_id,
        "lifecycle_recipe",
        lifecycle_manifest.public_recipe(recipe),
        actor="api",
    )
    return recipe


class DeployRequest(EngagementIntentRequest):
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


class ResetRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


def _check_provider_compatibility(scenario_id: str, provider_name: str | None):
    """Reject vm-scenarios on container backends (and vice versa) up front.

    An unspecified provider resolves to the active default so the check still
    runs — previously a ``None`` provider skipped validation entirely, letting
    an incompatible deploy queue and then fail asynchronously in the Celery
    OpenTofu/Docker step, which is opaque to the operator."""
    resolved = provider_name or default_provider_name()
    if resolved not in available_providers():
        return  # an unknown provider surfaces a clear error later at get_provider()
    meta = next((s for s in scenarios.list_scenarios() if s["id"] == scenario_id), None)
    if meta is None:
        return  # an unknown scenario id is rejected downstream (404)
    needed = meta["provider_class"]
    offered = infra_class_of(resolved)
    if needed != "any" and offered not in ("any", needed):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Scenario '{scenario_id}' requires {needed}-class "
                f"infrastructure but provider '{resolved}' "
                f"provides {offered}"
            ),
        )


class CustomArenaRequest(EngagementIntentRequest):
    """Build a custom arena from curated catalog picks (manual scenario creator).

    Supports **multiple attack machines** (P1-7): pass ``attackers`` (a list); the
    legacy single ``attacker`` field is still accepted and merged in for
    backward compatibility."""

    instance_id: str = Field(pattern=INSTANCE_NAME_PATTERN)
    attackers: list[str] = Field(default_factory=list, max_length=8)
    attacker: str | None = Field(default=None, max_length=64)
    victims: list[str] = Field(min_length=1, max_length=8)
    # Custom arenas are container topologies → docker-local by default.
    provider: str | None = Field(default="docker-local", max_length=32)

    @model_validator(mode="after")
    def _merge_attackers(self) -> "CustomArenaRequest":
        merged = ([self.attacker] if self.attacker else []) + list(self.attackers)
        seen, out = set(), []
        for a in merged:
            if a and a not in seen:
                seen.add(a)
                out.append(a)
        if not out:
            raise ValueError("pick at least one attacker image")
        self.attackers = out
        return self

    @field_validator("provider")
    @classmethod
    def provider_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in available_providers():
            raise ValueError(f"unknown provider '{value}' — see GET /providers")
        return value


@app.get("/scenarios")
def list_scenarios(principal: Principal = Depends(require_principal)):
    """Registry of deployable scenarios (id + display metadata + source)."""
    return {"scenarios": scenarios.list_scenarios()}


# --- scenario authoring & import (Classic-range track A, P1-7) ---------------
# A scenario can be brought IN as a reusable pack (not just dropped on disk):
# `POST /scenarios` validates a v3 spec and persists it under SCENARIOS_DIR;
# `POST /scenarios/preview` is a no-deploy dry-run (validate + topology) backing
# the WebUI preview; `GET /scenarios/{id}/topology` renders a registered pack.


def _parse_scenario_spec(spec) -> dict:
    """Coerce an imported spec (a JSON object, or a YAML/JSON document string)
    into a dict — 422 on anything else. YAML is a superset of JSON, so one
    parser handles both text forms."""
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, str):
        try:
            parsed = yaml.safe_load(spec)
        except yaml.YAMLError as e:
            raise HTTPException(
                status_code=422, detail=f"could not parse spec: {e}"
            ) from e
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=422, detail="spec must be a YAML/JSON object"
            )
        return parsed
    raise HTTPException(
        status_code=422, detail="spec must be an object or a YAML/JSON string"
    )


def _derive_scenario_id(raw: dict) -> str:
    """A registry id slugified from the spec's name/title."""
    base = str(raw.get("name") or raw.get("title") or "").strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", base).strip("-_")[:64]
    if not slug or not scenarios.is_valid_scenario_id(slug):
        raise HTTPException(
            status_code=422,
            detail="could not derive a scenario id from the spec — pass an explicit 'id'",
        )
    return slug


def _spec_errors(e: ValidationError) -> list[str]:
    """Flatten pydantic validation errors into short human lines."""
    out = []
    for err in e.errors(include_url=False):
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "__root__")
        msg = err.get("msg", "invalid")
        out.append(f"{loc}: {msg}" if loc else msg)
    return out or ["spec failed v3 validation"]


class ScenarioImportRequest(BaseModel):
    """Import a v3 scenario as a reusable pack (P1-7). ``spec`` is the topology as
    a JSON object or a YAML/JSON document string; ``id`` overrides the id derived
    from the spec name."""

    spec: dict | str
    id: str | None = Field(default=None, max_length=64)
    overwrite: bool = False


@app.post("/scenarios")
@limiter.limit(RATE_LIMIT_DEPLOY)
def import_scenario(
    request: Request,
    req: ScenarioImportRequest,
    principal: Principal = Depends(require_principal),
):
    """Validate a v3 scenario spec and persist it as a reusable pack
    (operator-only). Never deploys — the pack then appears in GET /scenarios and
    can be previewed / launched like a built-in."""
    _require_operator(principal)
    raw = _parse_scenario_spec(req.spec)
    scenario_id = (req.id or "").strip().lower() or _derive_scenario_id(raw)
    try:
        summary = scenarios.save_scenario(scenario_id, raw, overwrite=req.overwrite)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_spec_errors(e)) from e
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    logger.info("Imported scenario '%s' by '%s'", scenario_id, principal.name)
    return {"status": "imported", "id": scenario_id, "scenario": summary}


@app.delete("/scenarios/{scenario_id}")
def delete_scenario(
    scenario_id: str,
    principal: Principal = Depends(require_principal),
):
    """Delete an imported scenario pack (operator-only). Built-ins are read-only."""
    _require_operator(principal)
    try:
        removed = scenarios.delete_scenario(scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not removed:
        raise HTTPException(
            status_code=404, detail=f"no imported scenario '{scenario_id}'"
        )
    return {"status": "deleted", "id": scenario_id}


def _missing_container_images(raw: dict) -> list[str]:
    """Resolved docker-local image refs that Docker Hub confidently reports as
    NOT existing (404). Fail-open: an unknown / other-registry / unreachable
    result is never reported (see ``image_check.missing_images``), and this never
    raises — so it is safe both as an advisory (review gate) and as a hard gate
    (deploy block)."""
    try:
        refs = [
            images.resolve(n["image"], "docker-local")
            for n in normalized_nodes(raw) if n.get("image")
        ]
        return image_check.missing_images([r for r in refs if isinstance(r, str)])
    except Exception:  # noqa: BLE001 - advisory only
        return []


def _image_warnings(raw: dict) -> list[str]:
    """Best-effort: warn about container images that Docker Hub confidently
    reports as non-existent (Field-A — a generated/imported spec that names a
    hallucinated image would otherwise fail opaquely at deploy). Unknown / other-
    registry images never warn. Never raises."""
    return [
        f"image '{m}' was not found on Docker Hub — the arena will fail to launch "
        f"unless it exists; use a catalog image or fix the tag"
        for m in _missing_container_images(raw)
    ]


def _assert_container_images_exist(scenario_id: str, provider_name: str | None):
    """Hard gate: block a deploy whose container image(s) Docker Hub confidently
    reports as missing (404). A hallucinated or mistyped image — common in
    prompt-generated specs — would otherwise pull-fail opaquely deep in the worker
    after the deploy is already queued. Runs ONLY for the docker-local provider
    (the only backend that pulls Docker Hub refs); mock/vm resolutions are skipped.
    Fail-open: anything other than a confident 404 (private/other registry,
    network error, rate limit) never blocks — see ``image_check``."""
    if resolve_provider_name(provider_name) != "docker-local":
        return
    raw = scenarios.load_scenario(scenario_id)
    if not raw:
        return  # an unknown scenario id is rejected downstream (404)
    missing = sorted(set(_missing_container_images(raw)))
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "Deploy blocked — image(s) not found on Docker Hub: "
                + ", ".join(missing)
                + ". Fix the tag or use a catalog image (GET /catalog); a "
                "non-existent image cannot launch."
            ),
        )


def _spec_review(raw: dict, *, include_spec: bool = False, check_images: bool = False) -> dict:
    """Validate a candidate v3 spec and build the no-deploy review payload
    (``valid``/``errors``/``warnings``/``suggested_id``/``summary``/``topology``)
    shared by the preview and generate endpoints — the review gate (never
    deploys). With ``include_spec`` the raw spec is echoed back for the
    review→import flow. With ``check_images`` (container-class only), a best-effort
    Docker Hub existence check appends warnings for missing images."""
    base = {"spec": raw} if include_spec else {}
    try:
        spec = ScenarioSpec.from_raw(raw)
    except ValidationError as e:
        return {**base, "valid": False, "errors": _spec_errors(e), "warnings": [], "topology": None}
    suggested = None
    try:
        suggested = _derive_scenario_id(raw)
    except HTTPException:
        pass
    warnings = list(spec.warnings())
    if check_images and spec.requires.provider_class.value in ("container", "any"):
        warnings += _image_warnings(raw)
    return {
        **base,
        "valid": True,
        "errors": [],
        "warnings": warnings,
        "suggested_id": suggested,
        "summary": {
            "name": spec.name,
            "title": spec.title,
            "difficulty": spec.difficulty,
            "provider_class": spec.requires.provider_class.value,
            "nodes": len(spec.nodes),
        },
        "topology": topology_view(spec),
    }


class ScenarioPreviewRequest(BaseModel):
    """A no-deploy dry-run: validate a candidate scenario and return its topology.
    Provide exactly one of ``spec`` (a v3 spec, object or YAML/JSON string) or
    ``picks`` (catalog ids, the custom builder's live preview)."""

    spec: dict | str | None = None
    picks: dict | None = None  # {"attackers": [...], "victims": [...]}


@app.post("/scenarios/preview")
def preview_scenario(
    request: Request,
    req: ScenarioPreviewRequest,
    principal: Principal = Depends(require_principal),
):
    """Validate a candidate scenario (a pasted spec or catalog picks) and return
    ``{valid, errors, warnings, summary, topology}`` WITHOUT deploying — backs the
    WebUI launch/import previews. Operator-only (an authoring action)."""
    _require_operator(principal)
    if req.picks is not None:
        attackers = req.picks.get("attackers") or req.picks.get("attacker") or []
        victims = req.picks.get("victims") or []
        try:
            raw = catalog.build_custom_scenario("preview", attackers, victims)
        except catalog.CatalogError as e:
            return {"valid": False, "errors": [str(e)], "warnings": [], "topology": None}
    elif req.spec is not None:
        raw = _parse_scenario_spec(req.spec)
    else:
        raise HTTPException(status_code=422, detail="provide a 'spec' or 'picks'")

    return _spec_review(raw)


class ScenarioGenerateRequest(BaseModel):
    """Zero-to-prompt generation (P3): a natural-language ``prompt`` the operator's
    connected model turns into a candidate v3 spec. ``provider_class`` optionally
    pins the backend class (container | vm | any)."""

    prompt: str = Field(min_length=1, max_length=4000)
    provider_class: str | None = Field(default=None, max_length=16)


@app.post("/scenarios/generate")
@limiter.limit(RATE_LIMIT_DEPLOY)
def generate_scenario(
    request: Request,
    req: ScenarioGenerateRequest,
    principal: Principal = Depends(require_principal),
):
    """Generate a candidate v3 scenario from a prompt using the OPERATOR'S OWN
    connected model (the model bubble), validate it, and return the spec + its
    topology preview WITHOUT deploying or saving (the review gate — P3-2). The
    operator reviews, then imports via POST /scenarios and launches. Operator-only;
    409 when no model is connected. Scope boundary: the model + key are the
    operator's; Nidavellir never supplies the AI ([[cyberguard-ai-scope-boundary]])."""
    _require_operator(principal)
    cred = db.get_decrypted_model_credential(principal.name)
    if not cred:
        raise HTTPException(
            status_code=409,
            detail="no model connected — configure one via the model bubble first",
        )

    def complete(system, messages):
        reply = model_chat.complete_chat(
            cred["provider"], cred["model"], cred["api_key"], system, messages,
            max_tokens=4096, json_mode=True, base_url=cred.get("base_url"),
        )
        # An upstream failure arrives as model_chat's inline error sentinel rather
        # than a spec — re-surface it as a clean generator error (no co-pilot
        # branding) carrying the provider's own message.
        if reply.lstrip().startswith(model_chat.ERROR_SENTINEL):
            clean = reply.replace(model_chat.ERROR_SENTINEL, "").strip()
            raise generator.GeneratorError(
                f"the model provider could not complete the request: {clean}", raw=reply
            )
        return reply

    try:
        raw = generator.generate_scenario_spec(complete, req.prompt, req.provider_class)
    except generator.GeneratorError as e:
        logger.info("scenario generation for '%s' produced no usable spec", principal.name)
        return {
            "valid": False,
            "errors": [str(e)],
            "warnings": [],
            "topology": None,
            "raw": (e.raw or "")[:6000],
        }
    logger.info("Generated candidate scenario for '%s' (review pending)", principal.name)
    return _spec_review(raw, include_spec=True, check_images=True)


class VulhubImportRequest(BaseModel):
    """Import a Vulhub environment as a v3 pack (P1-5 / track C). Provide either
    ``path`` (a Vulhub env dir, e.g. ``weblogic/CVE-2017-10271`` — fetched from
    GitHub at ``ref``) or ``compose`` (a pasted docker-compose object or YAML
    string, for offline/air-gapped use). ``dry_run`` previews without saving."""

    path: str | None = None
    compose: dict | str | None = None
    ref: str = vulhub_import.DEFAULT_REF
    id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    include_attacker: bool = True
    overwrite: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def _one_source(self) -> "VulhubImportRequest":
        if bool(self.path) == bool(self.compose):
            raise ValueError("provide exactly one of 'path' or 'compose'")
        return self


@app.post("/scenarios/import/vulhub")
@limiter.limit(RATE_LIMIT_DEPLOY)
def import_vulhub(
    request: Request,
    req: VulhubImportRequest,
    principal: Principal = Depends(require_principal),
):
    """Convert a Vulhub Docker Compose environment into a v3 scenario pack
    (operator-only). Deterministic — no model in the loop. ``dry_run`` returns a
    preview (valid/warnings/topology); otherwise the pack is validated and
    persisted to the registry like any imported scenario. Never deploys."""
    _require_operator(principal)
    try:
        if req.path:
            compose, env_path = vulhub_import.fetch_vulhub_compose(
                req.path, ref=req.ref
            )
        else:
            compose = _parse_scenario_spec(req.compose)
            env_path = ""
        raw, warnings = vulhub_import.convert_compose(
            compose,
            name=req.name,
            env_path=env_path,
            ref=req.ref,
            include_attacker=req.include_attacker,
        )
    except vulhub_import.VulhubImportError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except netguard.UnsafeHostError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        spec = ScenarioSpec.from_raw(raw)
    except ValidationError as e:
        # A faithful conversion that still fails v3 validation — report it.
        raise HTTPException(status_code=422, detail=_spec_errors(e)) from e

    if req.dry_run:
        suggested = None
        try:
            suggested = _derive_scenario_id(raw)
        except HTTPException:
            pass
        return {
            "valid": True,
            "errors": [],
            "warnings": warnings + spec.warnings(),
            "suggested_id": req.id or suggested,
            "summary": {
                "name": spec.name,
                "title": spec.title,
                "difficulty": spec.difficulty,
                "provider_class": spec.requires.provider_class.value,
                "nodes": len(spec.nodes),
            },
            "topology": topology_view(spec),
        }

    scenario_id = (req.id or "").strip().lower() or _derive_scenario_id(raw)
    try:
        summary = scenarios.save_scenario(scenario_id, raw, overwrite=req.overwrite)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_spec_errors(e)) from e
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    logger.info(
        "Imported Vulhub scenario '%s' (path=%r) by '%s'",
        scenario_id, req.path, principal.name,
    )
    return {
        "status": "imported",
        "id": scenario_id,
        "scenario": summary,
        "warnings": warnings + spec.warnings(),
    }


@app.get("/scenarios/{scenario_id}/topology")
def scenario_topology(
    scenario_id: str,
    principal: Principal = Depends(require_principal),
):
    """The render-friendly topology graph of a REGISTERED scenario (no ground
    truth). Backs the WebUI pre-deploy preview. 404 if unknown/invalid."""
    spec = scenarios.load_scenario_spec(scenario_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{scenario_id}'")
    return {
        "id": scenario_id,
        "warnings": spec.warnings(),
        "topology": topology_view(spec),
    }


@app.get("/catalog")
def get_catalog(kind: str | None = None, principal: Principal = Depends(require_principal)):
    """Curated attacker/victim images for the manual scenario creator."""
    return {"images": catalog.list_catalog(kind)}


@app.post("/arenas/custom")
@limiter.limit(RATE_LIMIT_DEPLOY)
def deploy_custom_arena(
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
        spec = catalog.build_custom_scenario(req.instance_id, req.attackers, req.victims)
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
    label = f"custom:{'+'.join(req.attackers)}+{'+'.join(req.victims)}"[:64]
    expires_at = _engagement_expires_at(req)
    db.create_deployment(
        system_id, req.instance_id, label,
        provider=req.provider, actor=principal.name, expires_at=expires_at,
        effective_provider=resolve_provider_name(req.provider),
    )
    _record_engagement_intent(system_id, req, principal, source="challenge")
    _record_lifecycle_recipe(
        system_id, scenario_name=label, scenario_config=spec,
        requested_provider=req.provider, expires_at=expires_at,
    )
    _autobind_deployer(principal, system_id)  # D1: the deployer owns its sandbox
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
        effective_provider=resolve_provider_name(req.provider),
    )
    return {"status": "accepted", "instance_id": system_id}


# --- Software-under-test (SUT) arena (the launch wizard, P2-10) --------------
# A separate launch mode from a named scenario / catalog custom arena: point
# Nidavellir at a GitHub repo, it spins up a fresh Ubuntu victim with the repo
# cloned in, and the service is brought up during the setup phase by a human
# (operator-scripted) or a HITL agent (gateway configurator stance). The setup
# config is captured HERE, at creation (review 1.1), and auto-applied when the
# arena reaches `active`. Autonomous is intentionally NOT offered in the wizard.
SUT_SETUP_MODES = (setup_phase.MODE_OPERATOR, setup_phase.MODE_HITL)
_GIT_URL_RE = re.compile(r"^https://[A-Za-z0-9._~%-]+(?::\d+)?/[A-Za-z0-9._~:@!$&'()*+,;=%/-]+$")
_GIT_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class SutArenaRequest(EngagementIntentRequest):
    instance_id: str = Field(pattern=INSTANCE_NAME_PATTERN)
    repo: str = Field(min_length=8, max_length=400)
    ref: str | None = Field(default=None, max_length=120)
    ports: list[int] = Field(default_factory=list, max_length=8)
    include_attacker: bool = Field(default=True)
    setup_mode: str = Field(default=setup_phase.MODE_OPERATOR)
    time_box_seconds: int = Field(
        default=setup_phase.DEFAULT_TIME_BOX_SECONDS, ge=60,
        le=setup_phase.MAX_TIME_BOX_SECONDS,
    )
    command_budget: int = Field(
        default=setup_phase.DEFAULT_COMMAND_BUDGET, ge=1, le=setup_phase.MAX_COMMAND_BUDGET
    )
    setup_egress: bool = Field(default=True)  # SUT setup almost always needs deps
    authorization_basis: str = Field(default="public_oss", max_length=32)
    authorization_confirmed: bool = Field(default=False)
    scope_note: str | None = Field(default=None, max_length=500)
    provider: str | None = Field(default="docker-local", max_length=32)

    @field_validator("repo")
    @classmethod
    def _repo_is_https_git(cls, value: str) -> str:
        value = value.strip()
        if not _GIT_URL_RE.match(value):
            raise ValueError(
                "repo must be an https:// git URL (e.g. https://github.com/org/project)"
            )
        # SSRF guard: reject literal internal/metadata hosts up front (no DNS in
        # the request path — the authoritative resolve happens provider-side
        # before the clone). https:// to 169.254.169.254 is still SSRF.
        try:
            netguard.assert_public_host(value, resolve=False)
        except netguard.UnsafeHostError as e:
            raise ValueError(str(e)) from e
        return value

    @field_validator("ref")
    @classmethod
    def _ref_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if (
            value
            and (
                not _GIT_REF_RE.match(value)
                or value.startswith("-")
                or ".." in value
            )
        ):
            raise ValueError(
                "ref may contain only letters, digits, '.', '_', '/', '-'; "
                "it cannot start with '-' or contain '..'"
            )
        return value or None

    @field_validator("setup_mode")
    @classmethod
    def _mode_in_wizard(cls, value: str) -> str:
        if value not in SUT_SETUP_MODES:
            raise ValueError(
                f"setup_mode must be one of {SUT_SETUP_MODES} "
                "(autonomous is not offered in the SUT wizard)"
            )
        return value

    @field_validator("authorization_basis")
    @classmethod
    def _known_authorization_basis(cls, value: str) -> str:
        if value not in research_session.AUTHORIZATION_BASES:
            raise ValueError(
                "authorization_basis must be one of "
                f"{research_session.AUTHORIZATION_BASES}"
            )
        return value

    @field_validator("ports")
    @classmethod
    def _ports_in_range(cls, value: list[int]) -> list[int]:
        for p in value:
            if not 1 <= p <= 65535:
                raise ValueError(f"port {p} out of range 1-65535")
        return value

    @field_validator("provider")
    @classmethod
    def _provider_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in available_providers():
            raise ValueError(f"unknown provider '{value}' — see GET /providers")
        return value


@app.post("/arenas/sut/preview")
def preview_sut_arena(req: SutArenaRequest, principal: Principal = Depends(require_principal)):
    """No-deploy review for the arena wizard: compile the SUT spec and return its
    topology + warnings (incl. image existence) WITHOUT provisioning, so the
    operator reviews the planned arena before launching. Operator-only."""
    _require_operator(principal)
    try:
        target = repo_introspect.inspect_target(req.repo, req.ref)
        spec = catalog.build_sut_scenario(
            req.instance_id, req.repo, target["resolved_commit"],
            ports=req.ports, include_attacker=req.include_attacker,
        )
    except (catalog.CatalogError, netguard.UnsafeHostError,
            OSError, subprocess.SubprocessError) as e:
        return {"valid": False, "errors": [str(e)], "warnings": [], "topology": None}
    review = _spec_review(spec, check_images=True)
    # Introspect the repo so the operator sees the detected language / build system /
    # declared ports BEFORE launch (M1-1) — the review-gate payoff: a `guessed`
    # port or a missing build system is visible now, not discovered at setup time.
    introspection = repo_introspect.summarize_for_prompt(target)
    review["introspection"] = introspection
    review["target_manifest"] = research_session.git_target_manifest(
        repo=req.repo,
        requested_ref=req.ref,
        resolved_commit=target["resolved_commit"],
        authorization_basis=req.authorization_basis,
        authorization_confirmed=req.authorization_confirmed,
        scope_note=req.scope_note,
        actor=principal.name,
    )
    if not req.authorization_confirmed:
        review.setdefault("warnings", []).append(
            "authorization must be confirmed before launch"
        )
    # M1-2 (ADR-0008): show the planned build tier so the operator knows whether
    # this repo will auto-build to a pinned image or use the configurator fallback.
    plan = build_planner.plan_build(introspection)
    review["build_plan"] = plan.to_dict()
    review["build_plan"]["auto_build"] = plan.executable and config.ALLOW_SOURCE_BUILD
    return review


@app.post("/arenas/sut")
@limiter.limit(RATE_LIMIT_DEPLOY)
def deploy_sut_arena(
    request: Request,
    req: SutArenaRequest,
    principal: Principal = Depends(require_principal),
):
    """Provision a software-under-test arena from a GitHub repo (the wizard).

    A fresh Ubuntu victim gets the repo cloned read-write into ``/opt/sut`` and an
    optional Kali foothold is added for the engagement. The setup config (mode +
    time-box + budget + egress) is recorded NOW as operator consent and the worker
    opens the setup session automatically once the arena is active. Operator-only.
    """
    _require_operator(principal)
    if not req.authorization_confirmed:
        raise HTTPException(
            status_code=422,
            detail=(
                "confirm that you are authorized: you own the target, it is public "
                "OSS, or you have explicit authorization to assess it"
            ),
        )
    # Introspect the repo ONCE (M1-1) and plan the deterministic build tier (M1-2,
    # ADR-0008). Best-effort — introspect never raises. When the repo ships a
    # Dockerfile AND source builds are enabled, the victim auto-builds to a pinned
    # image (no manual configurator step); otherwise the bare-box + configurator
    # flow stays. (Sync handler → Starlette runs the short clone on the threadpool.)
    try:
        target = repo_introspect.inspect_target(req.repo, req.ref)
    except (netguard.UnsafeHostError, OSError, subprocess.SubprocessError) as e:
        raise HTTPException(
            status_code=422, detail=f"target identity could not be resolved: {e}"
        ) from e
    introspection = repo_introspect.summarize_for_prompt(target)
    plan = build_planner.plan_build(introspection)
    auto_build = plan.executable and config.ALLOW_SOURCE_BUILD
    try:
        spec = catalog.build_sut_scenario(
            req.instance_id, req.repo, target["resolved_commit"],
            ports=req.ports, include_attacker=req.include_attacker,
            build_plan=plan if auto_build else None,
        )
    except catalog.CatalogError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    offered = infra_class_of(req.provider) if req.provider else "any"
    if offered not in ("any", "container"):
        raise HTTPException(
            status_code=422,
            detail=f"provider '{req.provider}' provides {offered}-class infra, not container",
        )

    system_id = str(uuid.uuid4())
    label = f"sut:{req.repo}"[:64]
    expires_at = _engagement_expires_at(req)
    db.create_deployment(
        system_id, req.instance_id, label,
        provider=req.provider, actor=principal.name, expires_at=expires_at,
        effective_provider=resolve_provider_name(req.provider),
    )
    _record_engagement_intent(system_id, req, principal, source="target")

    target_manifest = research_session.git_target_manifest(
        repo=req.repo,
        requested_ref=req.ref,
        resolved_commit=target["resolved_commit"],
        authorization_basis=req.authorization_basis,
        authorization_confirmed=True,
        scope_note=req.scope_note,
        actor=principal.name,
    )
    prearm = {
        "mode": req.setup_mode,
        "time_box_seconds": req.time_box_seconds,
        "command_budget": req.command_budget,
        "setup_egress": req.setup_egress,
        "include_attacker": req.include_attacker,
        "auto_build": auto_build,
        "target_manifest": target_manifest,
        "actor": principal.name,
    }
    # Capture the setup config at CREATION (review 1.1 fix): an audit breadcrumb
    # now; the worker applies it (opens the session) when the arena is active. The
    # introspection (M1-1) is stored so proposal drafting reuses it without re-
    # cloning; the build plan (M1-2) records the chosen tier + whether it auto-built.
    db.record_event(
        system_id, "setup_prearm",
        {**prearm, "repo": req.repo, "ref": req.ref,
         "resolved_ref": target["resolved_commit"], "introspection": introspection,
         "build_plan": plan.to_dict(), "auto_build": auto_build},
        actor=principal.name,
    )
    _record_lifecycle_recipe(
        system_id, scenario_name=label, scenario_config=spec,
        requested_provider=req.provider, expires_at=expires_at,
        target_manifest=target_manifest, setup=prearm,
    )
    logger.info(
        f"Queuing SUT arena '{req.instance_id}' ({system_id}): repo={req.repo} "
        f"ref={target['resolved_commit']} mode={req.setup_mode} build={plan.strategy}"
        f"{' (auto)' if auto_build else ''} by '{principal.name}'"
    )
    deploy_lab.delay(
        instance_id=system_id, scenario_name=label, user_id=req.instance_id,
        variables={}, provider=req.provider, scenario_config=spec,
        setup_prearm=prearm,
        effective_provider=resolve_provider_name(req.provider),
    )
    return {
        "status": "accepted",
        "instance_id": system_id,
        "target_manifest": target_manifest,
    }


class OciArenaRequest(EngagementIntentRequest):
    instance_id: str = Field(pattern=INSTANCE_NAME_PATTERN)
    image: str = Field(min_length=1, max_length=500)
    ports: list[int] = Field(default_factory=list, max_length=8)
    include_attacker: bool = Field(default=True)
    platform: str = Field(default="linux/amd64", max_length=32)
    authorization_basis: str = Field(default="public_oss", max_length=32)
    authorization_confirmed: bool = Field(default=False)
    scope_note: str | None = Field(default=None, max_length=500)
    provider: str | None = Field(default="docker-local", max_length=32)

    @field_validator("image")
    @classmethod
    def _valid_oci_reference(cls, value: str) -> str:
        value = value.strip()
        try:
            oci_intake.parse_reference(value)
        except (oci_intake.OciIntakeError, netguard.UnsafeHostError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("ports")
    @classmethod
    def _ports_in_range(cls, value: list[int]) -> list[int]:
        for port in value:
            if not 1 <= port <= 65535:
                raise ValueError(f"port {port} out of range 1-65535")
        return value

    @field_validator("platform")
    @classmethod
    def _supported_platform(cls, value: str) -> str:
        if value not in ("linux/amd64", "linux/arm64"):
            raise ValueError("platform must be linux/amd64 or linux/arm64")
        return value

    @field_validator("authorization_basis")
    @classmethod
    def _known_authorization_basis(cls, value: str) -> str:
        if value not in research_session.AUTHORIZATION_BASES:
            raise ValueError(
                "authorization_basis must be one of "
                f"{research_session.AUTHORIZATION_BASES}"
            )
        return value

    @field_validator("provider")
    @classmethod
    def _provider_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in available_providers():
            raise ValueError(f"unknown provider '{value}' — see GET /providers")
        return value


def _resolve_oci_or_422(image: str) -> dict:
    try:
        return oci_intake.resolve_image(image)
    except (
        oci_intake.OciIntakeError,
        netguard.UnsafeHostError,
        requests.RequestException,
    ) as exc:
        raise HTTPException(
            status_code=422, detail=f"OCI target identity could not be resolved: {exc}"
        ) from exc


@app.post("/arenas/oci/preview")
def preview_oci_arena(
    req: OciArenaRequest,
    principal: Principal = Depends(require_principal),
):
    """Resolve and compile a public OCI target without pulling or executing it."""
    _require_operator(principal)
    try:
        target = oci_intake.resolve_image(req.image)
        spec = catalog.build_oci_scenario(
            req.instance_id,
            target["runtime_ref"],
            ports=req.ports,
            include_attacker=req.include_attacker,
            platform=req.platform,
        )
    except (
        catalog.CatalogError,
        oci_intake.OciIntakeError,
        netguard.UnsafeHostError,
        requests.RequestException,
    ) as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
            "warnings": [],
            "topology": None,
        }

    review = _spec_review(spec, check_images=False)
    review["target_manifest"] = research_session.oci_target_manifest(
        requested_image=req.image,
        runtime_ref=target["runtime_ref"],
        resolved_digest=target["resolved_digest"],
        authorization_basis=req.authorization_basis,
        authorization_confirmed=req.authorization_confirmed,
        scope_note=req.scope_note,
        actor=principal.name,
        platform=req.platform,
    )
    review["introspection"] = {
        "kind": "oci",
        "registry": target["registry"],
        "repository": target["repository"],
        "requested_ref": target["requested_ref"],
        "runtime_ref": target["runtime_ref"],
        "platform": req.platform,
    }
    if not req.authorization_confirmed:
        review.setdefault("warnings", []).append(
            "authorization must be confirmed before launch"
        )
    return review


@app.post("/arenas/oci")
@limiter.limit(RATE_LIMIT_DEPLOY)
def deploy_oci_arena(
    request: Request,
    req: OciArenaRequest,
    principal: Principal = Depends(require_principal),
):
    """Deploy a public OCI image by immutable manifest digest."""
    _require_operator(principal)
    if not req.authorization_confirmed:
        raise HTTPException(
            status_code=422,
            detail=(
                "confirm that you are authorized: you own the target, it is public "
                "software, or you have explicit authorization to assess it"
            ),
        )
    target = _resolve_oci_or_422(req.image)
    try:
        spec = catalog.build_oci_scenario(
            req.instance_id,
            target["runtime_ref"],
            ports=req.ports,
            include_attacker=req.include_attacker,
            platform=req.platform,
        )
    except catalog.CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    offered = infra_class_of(req.provider) if req.provider else "any"
    if offered not in ("any", "container"):
        raise HTTPException(
            status_code=422,
            detail=f"provider '{req.provider}' provides {offered}-class infra, not container",
        )

    system_id = str(uuid.uuid4())
    label = f"oci:{req.image}"[:64]
    expires_at = _engagement_expires_at(req)
    db.create_deployment(
        system_id,
        req.instance_id,
        label,
        provider=req.provider,
        actor=principal.name,
        expires_at=expires_at,
        effective_provider=resolve_provider_name(req.provider),
    )
    _record_engagement_intent(system_id, req, principal, source="target")
    manifest = research_session.oci_target_manifest(
        requested_image=req.image,
        runtime_ref=target["runtime_ref"],
        resolved_digest=target["resolved_digest"],
        authorization_basis=req.authorization_basis,
        authorization_confirmed=True,
        scope_note=req.scope_note,
        actor=principal.name,
        platform=req.platform,
    )
    prearm = {
        "include_attacker": req.include_attacker,
        "auto_build": True,
        "open_setup": False,
        "target_manifest": manifest,
        "actor": principal.name,
    }
    db.record_event(
        system_id,
        "session_prearm",
        {**prearm, "target": target},
        actor=principal.name,
    )
    _record_lifecycle_recipe(
        system_id, scenario_name=label, scenario_config=spec,
        requested_provider=req.provider, expires_at=expires_at,
        target_manifest=manifest, setup=prearm,
    )
    logger.info(
        "Queuing OCI arena %r (%s): image=%s digest=%s by %r",
        req.instance_id,
        system_id,
        req.image,
        target["resolved_digest"],
        principal.name,
    )
    deploy_lab.delay(
        instance_id=system_id,
        scenario_name=label,
        user_id=req.instance_id,
        variables={},
        provider=req.provider,
        scenario_config=spec,
        setup_prearm=prearm,
        effective_provider=resolve_provider_name(req.provider),
    )
    return {
        "status": "accepted",
        "instance_id": system_id,
        "target_manifest": manifest,
    }


@app.post("/targets/source-bundles")
@limiter.limit(RATE_LIMIT_DEPLOY)
def upload_source_bundle(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_principal),
):
    """Validate and persist one bounded tar/tar.gz source artifact."""
    _require_operator(principal)
    filename = file.filename or "source.tar"
    lower_name = filename.lower()
    if not lower_name.endswith((".tar", ".tar.gz", ".tgz")):
        raise HTTPException(
            status_code=422, detail="source bundle must be .tar, .tar.gz, or .tgz"
        )
    try:
        artifact = source_bundle.ingest(file.file, filename)
    except source_bundle.SourceBundleTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except source_bundle.SourceBundleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.record_event(
        f"artifact:{artifact['digest']}",
        "source_bundle_intake",
        {
            key: artifact[key]
            for key in (
                "digest",
                "filename",
                "upload_bytes",
                "expanded_bytes",
                "file_count",
                "member_count",
            )
        },
        actor=principal.name,
    )
    return {"status": "accepted", "artifact": artifact}


class SourceBundleArenaRequest(EngagementIntentRequest):
    instance_id: str = Field(pattern=INSTANCE_NAME_PATTERN)
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    ports: list[int] = Field(default_factory=list, max_length=8)
    include_attacker: bool = Field(default=True)
    setup_mode: str = Field(default=setup_phase.MODE_OPERATOR)
    time_box_seconds: int = Field(
        default=setup_phase.DEFAULT_TIME_BOX_SECONDS,
        ge=60,
        le=setup_phase.MAX_TIME_BOX_SECONDS,
    )
    command_budget: int = Field(
        default=setup_phase.DEFAULT_COMMAND_BUDGET,
        ge=1,
        le=setup_phase.MAX_COMMAND_BUDGET,
    )
    setup_egress: bool = Field(default=True)
    authorization_basis: str = Field(default="owned", max_length=32)
    authorization_confirmed: bool = Field(default=False)
    scope_note: str | None = Field(default=None, max_length=500)
    provider: str | None = Field(default="docker-local", max_length=32)

    @field_validator("ports")
    @classmethod
    def _ports_in_range(cls, value: list[int]) -> list[int]:
        for port in value:
            if not 1 <= port <= 65535:
                raise ValueError(f"port {port} out of range 1-65535")
        return value

    @field_validator("setup_mode")
    @classmethod
    def _mode_in_wizard(cls, value: str) -> str:
        if value not in SUT_SETUP_MODES:
            raise ValueError(f"setup_mode must be one of {SUT_SETUP_MODES}")
        return value

    @field_validator("authorization_basis")
    @classmethod
    def _known_authorization_basis(cls, value: str) -> str:
        if value not in research_session.AUTHORIZATION_BASES:
            raise ValueError(
                "authorization_basis must be one of "
                f"{research_session.AUTHORIZATION_BASES}"
            )
        return value

    @field_validator("provider")
    @classmethod
    def _provider_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in available_providers():
            raise ValueError(f"unknown provider '{value}' — see GET /providers")
        return value


def _bundle_artifact_or_422(digest: str) -> dict:
    try:
        return source_bundle.get_artifact(digest)
    except source_bundle.SourceBundleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/arenas/source-bundle/preview")
def preview_source_bundle_arena(
    req: SourceBundleArenaRequest,
    principal: Principal = Depends(require_principal),
):
    """Compile an already-ingested source bundle without deploying it."""
    _require_operator(principal)
    try:
        artifact = source_bundle.get_artifact(req.artifact_digest)
        spec = catalog.build_source_bundle_scenario(
            req.instance_id,
            artifact["digest"],
            artifact["payload_digest"],
            ports=req.ports,
            include_attacker=req.include_attacker,
        )
    except (source_bundle.SourceBundleError, catalog.CatalogError) as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
            "warnings": [],
            "topology": None,
        }
    review = _spec_review(spec, check_images=True)
    review["target_manifest"] = research_session.source_bundle_target_manifest(
        artifact=artifact,
        authorization_basis=req.authorization_basis,
        authorization_confirmed=req.authorization_confirmed,
        scope_note=req.scope_note,
        actor=principal.name,
    )
    review["introspection"] = {
        "kind": "source_bundle",
        **{
            key: artifact[key]
            for key in (
                "filename",
                "upload_bytes",
                "expanded_bytes",
                "file_count",
                "member_count",
                "stripped_root",
            )
        },
    }
    review["build_plan"] = {
        "strategy": "source_bundle",
        "executable": False,
        "auto_build": False,
        "reason": "validated bundle is configured only inside the disposable target",
    }
    if not req.authorization_confirmed:
        review.setdefault("warnings", []).append(
            "authorization must be confirmed before launch"
        )
    return review


@app.post("/arenas/source-bundle")
@limiter.limit(RATE_LIMIT_DEPLOY)
def deploy_source_bundle_arena(
    request: Request,
    req: SourceBundleArenaRequest,
    principal: Principal = Depends(require_principal),
):
    """Deploy a validated local source bundle into a disposable setup workspace."""
    _require_operator(principal)
    if not req.authorization_confirmed:
        raise HTTPException(
            status_code=422,
            detail=(
                "confirm that you are authorized: you own the source bundle or "
                "have explicit authorization to assess it"
            ),
        )
    artifact = _bundle_artifact_or_422(req.artifact_digest)
    try:
        spec = catalog.build_source_bundle_scenario(
            req.instance_id,
            artifact["digest"],
            artifact["payload_digest"],
            ports=req.ports,
            include_attacker=req.include_attacker,
        )
    except catalog.CatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    offered = infra_class_of(req.provider) if req.provider else "any"
    if offered not in ("any", "container"):
        raise HTTPException(
            status_code=422,
            detail=f"provider '{req.provider}' provides {offered}-class infra, not container",
        )

    system_id = str(uuid.uuid4())
    label = f"bundle:{artifact['filename']}"[:64]
    expires_at = _engagement_expires_at(req)
    db.create_deployment(
        system_id,
        req.instance_id,
        label,
        provider=req.provider,
        actor=principal.name,
        expires_at=expires_at,
        effective_provider=resolve_provider_name(req.provider),
    )
    _record_engagement_intent(system_id, req, principal, source="target")
    manifest = research_session.source_bundle_target_manifest(
        artifact=artifact,
        authorization_basis=req.authorization_basis,
        authorization_confirmed=True,
        scope_note=req.scope_note,
        actor=principal.name,
    )
    prearm = {
        "mode": req.setup_mode,
        "time_box_seconds": req.time_box_seconds,
        "command_budget": req.command_budget,
        "setup_egress": req.setup_egress,
        "include_attacker": req.include_attacker,
        "auto_build": False,
        "open_setup": True,
        "target_manifest": manifest,
        "actor": principal.name,
    }
    db.record_event(
        system_id,
        "setup_prearm",
        {**prearm, "artifact": artifact},
        actor=principal.name,
    )
    _record_lifecycle_recipe(
        system_id, scenario_name=label, scenario_config=spec,
        requested_provider=req.provider, expires_at=expires_at,
        target_manifest=manifest, setup=prearm,
    )
    logger.info(
        "Queuing source-bundle arena %r (%s): artifact=%s by %r",
        req.instance_id,
        system_id,
        artifact["digest"],
        principal.name,
    )
    deploy_lab.delay(
        instance_id=system_id,
        scenario_name=label,
        user_id=req.instance_id,
        variables={},
        provider=req.provider,
        scenario_config=spec,
        setup_prearm=prearm,
        effective_provider=resolve_provider_name(req.provider),
    )
    return {
        "status": "accepted",
        "instance_id": system_id,
        "target_manifest": manifest,
    }


class SynthesizeDockerfileRequest(BaseModel):
    repo: str = Field(min_length=8, max_length=400)
    ref: str | None = Field(default=None, max_length=120)
    max_attempts: int = Field(default=dockerfile_synth.DEFAULT_MAX_ATTEMPTS, ge=1, le=5)

    @field_validator("repo")
    @classmethod
    def _repo_is_https_git(cls, value: str) -> str:
        value = value.strip()
        if not _GIT_URL_RE.match(value):
            raise ValueError("repo must be an https:// git URL")
        try:
            netguard.assert_public_host(value, resolve=False)
        except netguard.UnsafeHostError as e:
            raise ValueError(str(e)) from e
        return value

    @field_validator("ref")
    @classmethod
    def _ref_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value and not _GIT_REF_RE.match(value):
            raise ValueError("ref may contain only letters, digits, '.', '_', '/', '-'")
        return value or None


@app.post("/repos/synthesize-dockerfile")
@limiter.limit(RATE_LIMIT_DEPLOY)
def synthesize_dockerfile(
    request: Request,
    req: SynthesizeDockerfileRequest,
    principal: Principal = Depends(require_principal),
):
    """Synthesize a Dockerfile for a repo that ships none, with a **verified-build
    loop** (M1-3, ADR-0008 tier-3 / Repo2Run): the OPERATOR'S OWN model drafts a
    Dockerfile grounded in the repo introspection; the platform actually **builds
    it**, feeds any build error back to the model to fix, and only returns one that
    **built green**. Never auto-deploys (review gate) — the operator reviews the
    verified Dockerfile, then launches a SUT arena. Operator-only; 409 without a
    connected model; requires source builds enabled (verification runs a real
    build). Scope boundary holds: the model + key are the operator's; Nidavellir
    supplies the verified-build harness, never the AI ([[cyberguard-ai-scope-boundary]])."""
    _require_operator(principal)
    if not config.ALLOW_SOURCE_BUILD:
        raise HTTPException(
            status_code=409,
            detail="Dockerfile synthesis verifies by building — enable source builds "
                   "(NIDAVELLIR_ALLOW_SOURCE_BUILD=true) first",
        )
    cred = db.get_decrypted_model_credential(principal.name)
    if not cred:
        raise HTTPException(
            status_code=409,
            detail="no model connected — configure one via the model bubble first",
        )

    introspection = repo_introspect.summarize_for_prompt(
        repo_introspect.introspect(req.repo, req.ref)
    )
    plan = build_planner.plan_build(introspection)
    if plan.executable:
        # The repo already ships a Dockerfile — synthesis is unnecessary.
        return {
            "ok": True, "synthesized": False, "dockerfile": None,
            "introspection": introspection, "build_plan": plan.to_dict(),
            "note": f"repo already provides a deterministic build ({plan.strategy}); "
                    "no synthesis needed",
        }

    provider = get_provider("docker-local")

    def complete(system, messages):
        reply = model_chat.complete_chat(
            cred["provider"], cred["model"], cred["api_key"], system, messages,
            max_tokens=2048, json_mode=False, base_url=cred.get("base_url"),
        )
        if reply.lstrip().startswith(model_chat.ERROR_SENTINEL):
            clean = reply.replace(model_chat.ERROR_SENTINEL, "").strip()
            raise dockerfile_synth.SynthError(
                f"the model provider could not complete the request: {clean}", raw=reply
            )
        return reply

    def build(dockerfile_text):
        return provider.verify_build_dockerfile(req.repo, req.ref, dockerfile_text)

    result = dockerfile_synth.synthesize_verified_dockerfile(
        complete, build, introspection, max_attempts=req.max_attempts
    )
    logger.info(
        "Dockerfile synthesis for %s by '%s': ok=%s attempts=%d",
        req.repo, principal.name, result["ok"], len(result["attempts"]),
    )
    return {
        "ok": result["ok"],
        "synthesized": True,
        "dockerfile": result["dockerfile"],
        "attempts": result["attempts"],
        "error": result["error"],
        "introspection": introspection,
        "build_plan": plan.to_dict(),
    }


@app.get("/providers")
def list_providers(principal: Principal = Depends(require_principal)):
    """Available deployment backends, the infra class each serves, and the
    active default (so clients can flag scenarios the default can't run)."""
    return {
        "default": default_provider_name(),
        "providers": [
            {"name": name, "infra_class": infra_class_of(name)}
            for name in available_providers()
        ],
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
def deploy(
    request: Request,
    req: DeployRequest,
    principal: Principal = Depends(require_principal),
):
    """Queue deployment via Celery with Unique UUID"""

    _check_provider_compatibility(req.scenario, req.provider)
    _assert_container_images_exist(req.scenario, req.provider)

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
    expires_at = _engagement_expires_at(req)
    scenario_config = scenarios.load_scenario(req.scenario)
    if scenario_config is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{req.scenario}'")
    db.create_deployment(
        system_id,
        friendly_name,
        req.scenario,
        provider=req.provider,
        actor=principal.name,
        expires_at=expires_at,
        effective_provider=resolve_provider_name(req.provider),
    )
    _record_engagement_intent(system_id, req, principal, source="challenge")
    _record_lifecycle_recipe(
        system_id, scenario_name=req.scenario, scenario_config=scenario_config,
        requested_provider=req.provider, expires_at=expires_at,
    )
    _autobind_deployer(principal, system_id)  # D1: the deployer owns its sandbox

    # 4. Dispatch Async Task using the UUID
    deploy_lab.delay(
        instance_id=system_id,
        scenario_name=req.scenario,
        user_id=friendly_name,
        variables={},
        provider=req.provider,
        scenario_config=scenario_config,
        effective_provider=resolve_provider_name(req.provider),
    )

    return {"status": "accepted", "instance_id": system_id}

@app.delete("/destroy/{instance_id}")
@limiter.limit(RATE_LIMIT_DESTROY)
def destroy(
    request: Request,
    instance_id: str,
    principal: Principal = Depends(require_principal),
):
    """Queue destruction via Celery.

    Operators may destroy any arena.  Agent principals may only tear down an
    arena to which they hold an active binding; this keeps the shared lifecycle
    MCP tool from becoming a cross-arena kill primitive.
    """
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    _require_binding(principal, instance_id, bindings.CAP_LIFECYCLE)

    record = db.get_deployment(instance_id) or {}
    try:
        claimed = db.transition_deployment(
            instance_id, (record.get("status"),), LabStatus.DESTROYING,
            actor=principal.name,
        )
    except IllegalTransition as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not claimed:
        raise HTTPException(status_code=409, detail="arena lifecycle changed concurrently")
    db.request_cancel_arena_poc_jobs(instance_id)
    db.revoke_arena_forwards(instance_id, actor=principal.name, reason="arena_destroy")

    logger.info(
        f"Queuing destroy for {instance_id} "
        f"requested by '{principal.name}' ({principal.role})"
    )
    destroy_lab.delay(instance_id)

    return {"status": "accepted"}


@app.get("/arenas/{instance_id}/lifecycle")
def arena_lifecycle(
    instance_id: str,
    principal: Principal = Depends(require_principal),
):
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    recipe = db.get_lifecycle_recipe(instance_id)
    observations = db.list_events(
        instance_id, limit=1, types=("lifecycle_observation",)
    )
    resets = db.list_reset_operations(source_id=instance_id)
    if recipe is None:
        return {
            "recipe": None,
            "classification": {
                "runtime_reset": {"status": "unsupported", "reason": "legacy_record"}
            },
            "observation": None,
            "resets": resets,
        }
    related_reset = resets[0] if resets else db.get_reset_operation_by_replacement(instance_id)
    observed_equivalence = {"status": "unverified", "reason": "no_reset_completed"}
    if related_reset and related_reset["status"] == "succeeded":
        observed_equivalence = {
            "status": "verified", "reason": "observed_starting_state_digest_matched"
        }
    elif related_reset and related_reset["stage"] == "comparison":
        observed_equivalence = {
            "status": "mismatch", "reason": "observed_starting_state_digest_differed"
        }
    public_recipe = lifecycle_manifest.public_recipe(recipe)
    public_recipe["observed_equivalence"] = observed_equivalence
    return {
        "recipe": public_recipe,
        "classification": {
            "build_reproducibility": recipe["build_reproducibility"],
            "runtime_reset": recipe["runtime_reset"],
            "observed_equivalence": observed_equivalence,
        },
        "observation": observations[0]["payload"] if observations else None,
        "resets": resets,
    }


@app.post("/arenas/{instance_id}/reset", status_code=202)
@limiter.limit(RATE_LIMIT_DESTROY)
def reset(
    request: Request,
    instance_id: str,
    req: ResetRequest,
    principal: Principal = Depends(require_principal),
):
    _require_operator(principal)
    if db.budget_status("")["system"]["state"] != "open":
        raise HTTPException(status_code=423, detail="system emergency stop is active")
    source = db.get_deployment(instance_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    if source["status"] not in (LabStatus.ACTIVE, LabStatus.DESTROYED):
        raise HTTPException(
            status_code=409,
            detail=f"reset requires an active or destroyed arena, not {source['status']}",
        )
    recipe = db.get_lifecycle_recipe(instance_id)
    if recipe is None:
        raise HTTPException(status_code=409, detail="legacy arena has no immutable reset recipe")
    if (recipe.get("runtime_reset") or {}).get("status") != "eligible":
        reason = (recipe.get("runtime_reset") or {}).get("reason", "unsupported")
        raise HTTPException(status_code=409, detail=f"arena is not reset-eligible: {reason}")
    if recipe.get("effective_provider") != source.get("effective_provider"):
        raise HTTPException(status_code=409, detail="effective provider no longer matches recipe")
    if resolve_provider_name(recipe.get("effective_provider")) != recipe.get("effective_provider"):
        raise HTTPException(status_code=409, detail="effective provider no longer matches recipe")
    target = recipe.get("target")
    if target and not (target.get("authorization") or {}).get("confirmed"):
        raise HTTPException(status_code=403, detail="target authorization is not confirmed")
    if not source.get("expires_at"):
        raise HTTPException(status_code=409, detail="arena has no durable engagement deadline")
    expires_at = datetime.fromisoformat(source["expires_at"])
    if expires_at <= datetime.now():
        raise HTTPException(status_code=409, detail="engagement deadline has expired")
    key = req.idempotency_key or request.headers.get("Idempotency-Key")
    if not key or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
        raise HTTPException(
            status_code=422,
            detail="an 8-128 character Idempotency-Key is required",
        )

    operation_id = str(uuid.uuid4())
    replacement_id = str(uuid.uuid4())
    try:
        operation, created = db.create_reset_operation(
            operation_id=operation_id,
            source_id=instance_id,
            replacement_id=replacement_id,
            idempotency_key=key,
            recipe_digest=recipe["recipe_digest"],
            deadline=min(expires_at, datetime.now() + timedelta(minutes=10)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created:
        if operation["status"] == "pending":
            reset_arena.delay(operation["id"])
        return {"operation_id": operation["id"], **operation}

    try:
        db.create_deployment(
            replacement_id,
            f"{source.get('user_id') or 'arena'}-reset"[:40],
            recipe["scenario_name"],
            provider=recipe.get("requested_provider"),
            actor=principal.name,
            expires_at=expires_at,
            effective_provider=recipe["effective_provider"],
        )
        db.inherit_budget_scope(instance_id, replacement_id)
        db.save_lifecycle_recipe(replacement_id, recipe)
        link = {
            "operation_id": operation_id,
            "source_id": instance_id,
            "replacement_id": replacement_id,
            "recipe_digest": recipe["recipe_digest"],
        }
        db.record_event(instance_id, "reset_requested", link, actor=principal.name)
        db.record_event(replacement_id, "reset_replacement_created", link, actor=principal.name)
    except Exception as exc:  # noqa: BLE001
        db.update_reset_operation(
            operation_id, status="failed", stage="creating_replacement",
            error=exc, terminal=True,
        )
        raise HTTPException(status_code=500, detail="could not create reset replacement") from exc
    db.revoke_arena_forwards(instance_id, actor=principal.name, reason="arena_reset")
    reset_arena.delay(operation_id)
    return {
        "status": "pending",
        "operation_id": operation_id,
        "source_id": instance_id,
        "replacement_id": replacement_id,
    }


@app.get("/reset-operations/{operation_id}")
def get_reset_operation(
    operation_id: str,
    principal: Principal = Depends(require_principal),
):
    _require_operator(principal)
    operation = db.get_reset_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="reset operation not found")
    return operation

# Records in these states describe infrastructure that no longer exists (or
# never came up) — only they may be deleted from history. Live labs must go
# through DELETE /destroy first.
DELETABLE_STATES = ("destroyed", "failed", "error_destroying")


@app.delete("/deployments/{instance_id}")
@limiter.limit(RATE_LIMIT_DESTROY)
def delete_deployment_record(
    request: Request,
    instance_id: str,
    principal: Principal = Depends(require_principal),
):
    """Remove a terminal (destroyed/failed) lab record from history."""
    _require_operator(principal)
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
def purge_deployment_records(
    request: Request,
    principal: Principal = Depends(require_principal),
):
    """Remove ALL terminal (destroyed/failed) lab records from history."""
    _require_operator(principal)
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


class ExecRequest(BaseModel):
    node: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=4096)
    timeout: int = Field(default=30, ge=1, le=120)


class TransferUploadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content_b64: str = Field(
        min_length=0,
        max_length=((config.TRANSFER_MAX_FILE_BYTES + 2) // 3 * 4) + 8,
    )
    node: str | None = Field(default=None, min_length=1, max_length=64)


class TransferDownloadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    node: str | None = Field(default=None, min_length=1, max_length=64)
    offset: int = Field(default=0, ge=0)
    max_bytes: int = Field(
        default=config.TRANSFER_CHUNK_BYTES,
        ge=1,
        le=config.TRANSFER_CHUNK_BYTES,
    )


class BrowserVisitRequest(BaseModel):
    node: str = Field(min_length=1, max_length=64)
    path: str = Field(default="/", min_length=1, max_length=2048)
    params: dict[str, str] = Field(default_factory=dict)
    wait_ms: int = Field(default=1500, ge=0, le=5000)

    @model_validator(mode="after")
    def _bounded_target(self):
        parsed = urllib.parse.urlsplit(self.path)
        if (
            not self.path.startswith("/")
            or self.path.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or "\x00" in self.path
        ):
            raise ValueError("path must be an arena-relative URL path without a fragment")
        if parsed.query:
            raise ValueError("put query values in params, not path")
        if len(self.params) > 32:
            raise ValueError("params may contain at most 32 entries")
        for key, value in self.params.items():
            if not key or len(key) > 128 or len(value) > 4096:
                raise ValueError("browser parameter names/values exceed configured bounds")
        return self


class HttpRequestRequest(BaseModel):
    node: str = Field(min_length=1, max_length=64)
    path: str = Field(default="/", min_length=1, max_length=2048)
    params: dict[str, str] = Field(default_factory=dict)
    method: str = Field(default="GET", min_length=1, max_length=32)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(
        default=None, max_length=config.HTTP_MAX_REQUEST_BYTES
    )

    @model_validator(mode="after")
    def _bounded_request(self):
        parsed = urllib.parse.urlsplit(self.path)
        if (
            not self.path.startswith("/")
            or self.path.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or "\x00" in self.path
        ):
            raise ValueError("path must be an arena-relative URL path without a fragment")
        if parsed.query:
            raise ValueError("put query values in params, not path")
        if len(self.params) > 32:
            raise ValueError("params may contain at most 32 entries")
        for key, value in self.params.items():
            if not key or len(key) > 128 or len(value) > 4096:
                raise ValueError("http parameter names/values exceed configured bounds")
        if not re.fullmatch(r"[A-Za-z]{1,32}", self.method):
            raise ValueError("method must be 1-32 alphabetic characters")
        self.method = self.method.upper()
        if len(self.headers) > 32:
            raise ValueError("headers may contain at most 32 entries")
        for key, value in self.headers.items():
            if (
                not key
                or "\r" in key
                or "\n" in key
                or "\r" in value
                or "\n" in value
                or len(key) > 128
                or len(value) > 4096
            ):
                raise ValueError("http header names/values exceed configured bounds")
        return self


class PocJobRequest(BaseModel):
    source: str = Field(min_length=1, max_length=config.POC_MAX_SOURCE_BYTES)
    target_node: str | None = Field(default=None, min_length=1, max_length=64)
    transfer_files: list[str] = Field(
        default_factory=list, max_length=config.POC_MAX_TRANSFER_FILES
    )
    timeout_seconds: int = Field(default=30, ge=1, le=config.POC_MAX_TIMEOUT_SECONDS)
    memory_mb: int = Field(default=128, ge=32, le=256)
    cpu_millis: int = Field(default=500, ge=100, le=1000)
    pids: int = Field(default=32, ge=8, le=128)
    workspace_bytes: int = Field(default=8 * 1024 * 1024, ge=1024 * 1024, le=16 * 1024 * 1024)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    token_budget: int | None = Field(default=None, ge=1)
    cost_budget_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def reject_unenforceable_model_budgets(self):
        if self.token_budget is not None or self.cost_budget_usd is not None:
            raise ValueError("token/cost caps cannot be enforced for a confined PoC job")
        return self

    @field_validator("transfer_files")
    @classmethod
    def validate_transfer_files(cls, values):
        normalized = [poc_execution.safe_relative_path(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("selected transfer file paths must be unique")
        return normalized


def _poc_job_or_error(instance_id: str, job_id: str, principal: Principal) -> dict:
    job = db.get_poc_job(job_id)
    if job is None or job["arena_id"] != instance_id:
        raise HTTPException(status_code=404, detail="PoC job not found in this arena")
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    if principal.role == "agent" and job["principal"] != principal.name:
        raise HTTPException(status_code=403, detail="PoC job belongs to another principal")
    return job


@app.post("/arenas/{instance_id}/poc-jobs", status_code=202)
@limiter.limit(RATE_LIMIT_EXEC)
def create_poc_job(
    request: Request,
    instance_id: str,
    req: PocJobRequest,
    principal: Principal = Depends(require_principal),
):
    """Submit immutable Python source for worker-owned confined execution."""
    record = _active_arena_or_error(instance_id)
    binding = _require_binding(principal, instance_id, bindings.CAP_EXEC)
    provider_name = record.get("effective_provider") or record.get("provider")
    if provider_name != "docker-local":
        raise HTTPException(
            status_code=501,
            detail=f"confined PoC execution is unsupported on provider {provider_name!r}",
        )
    key = req.idempotency_key or request.headers.get("Idempotency-Key")
    if not key or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
        raise HTTPException(status_code=422, detail="an 8-128 character Idempotency-Key is required")

    orch = Orchestrator(provider_name=provider_name)
    files = []
    if req.transfer_files:
        foothold = _transfer_foothold(record, None)
        for path in req.transfer_files:
            try:
                content = orch.read_transfer_file(instance_id, foothold, _transfer_path(path))
            except (NotImplementedError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            files.append({"path": path, "content": content})
    try:
        payload, input_digest = poc_execution.canonical_payload(req.source, files)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    target_policy = None
    if req.target_node:
        ip, port, scheme = _http_target(record, req.target_node)
        target_policy = {
            "mode": "fixed_http_relay/v1", "node": req.target_node,
            "ip": ip, "port": port, "scheme": scheme,
            "raw_tcp": "unsupported", "redirects": "not_followed",
        }
    limits = {
        "timeout_seconds": req.timeout_seconds, "memory_mb": req.memory_mb,
        "cpu_millis": req.cpu_millis, "pids": req.pids,
        "workspace_bytes": req.workspace_bytes,
        "stdout_bytes": config.POC_MAX_OUTPUT_BYTES,
        "stderr_bytes": config.POC_MAX_OUTPUT_BYTES,
        "artifact_bytes": config.POC_MAX_ARTIFACT_BYTES,
        "artifact_count": config.POC_MAX_ARTIFACTS,
    }
    expires_at = datetime.fromisoformat(record["expires_at"]) if record.get("expires_at") else None
    deadline = datetime.now() + timedelta(seconds=req.timeout_seconds + 60)
    if expires_at is not None:
        deadline = min(deadline, expires_at)
    try:
        job, created = db.create_poc_job(
            job_id=str(uuid.uuid4()), arena_id=instance_id,
            principal=principal.name, principal_role=principal.role,
            binding_stance=binding.get("stance") if binding else None,
            idempotency_key=key, input_digest=input_digest, payload=payload,
            runner_image=config.POC_RUNNER_IMAGE, target_node=req.target_node,
            target_policy=target_policy, limits=limits, deadline=deadline,
            max_arena_jobs=config.POC_MAX_ARENA_JOBS,
            max_global_jobs=config.POC_MAX_GLOBAL_JOBS,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409, detail=detail) from exc
    if created:
        db.record_event(
            instance_id, "poc_job_submitted",
            {
                "job_id": job["id"], "input_digest": input_digest,
                "target_node": req.target_node, "file_digests": [f["sha256"] for f in payload["files"]],
                "limits": limits,
            }, actor=principal.name,
        )
    if job["state"] == "queued":
        run_poc_job.delay(job["id"])
    return {"created": created, "job": poc_execution.public_job(job)}


@app.get("/arenas/{instance_id}/poc-jobs")
def list_poc_jobs(instance_id: str, principal: Principal = Depends(require_principal)):
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    jobs = db.list_poc_jobs(instance_id)
    if principal.role == "agent":
        jobs = [job for job in jobs if job["principal"] == principal.name]
    return {"jobs": [poc_execution.public_job(job) for job in jobs]}


@app.get("/arenas/{instance_id}/poc-jobs/{job_id}")
def get_poc_job(instance_id: str, job_id: str,
                principal: Principal = Depends(require_principal)):
    return {"job": poc_execution.public_job(
        _poc_job_or_error(instance_id, job_id, principal), include_result=True
    )}


@app.post("/arenas/{instance_id}/poc-jobs/{job_id}/cancel")
@limiter.limit(RATE_LIMIT_EXEC)
def cancel_poc_job(request: Request, instance_id: str, job_id: str,
                   principal: Principal = Depends(require_principal)):
    _poc_job_or_error(instance_id, job_id, principal)
    job = db.request_cancel_poc_job(job_id)
    db.record_event(instance_id, "poc_job_cancel_requested",
                    {"job_id": job_id, "state": job["state"]}, actor=principal.name)
    return {"job": poc_execution.public_job(job)}


def _transfer_foothold(record: dict, requested: str | None) -> str:
    outputs = record.get("outputs") or {}
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except json.JSONDecodeError:
            outputs = {}
    _, footholds = setup_phase.derive_nodes_footholds(outputs)
    if not footholds:
        raise HTTPException(status_code=422, detail="arena has no file-transfer foothold")
    if requested is None:
        if len(footholds) != 1:
            raise HTTPException(
                status_code=422,
                detail=f"arena has multiple footholds; choose one of {sorted(footholds)}",
            )
        return next(iter(footholds))
    if requested not in footholds:
        raise HTTPException(
            status_code=403,
            detail=f"file transfer is foothold-only; choose one of {sorted(footholds)}",
        )
    return requested


def _transfer_path(raw: str) -> str:
    if "\x00" in raw:
        raise HTTPException(status_code=422, detail="invalid transfer path")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or len(path.parts) > 16
        or len(str(path).encode("utf-8")) > 512
    ):
        raise HTTPException(
            status_code=422, detail="transfer path must stay below the transfer root"
        )
    return str(path)


def _browser_target(record: dict, node: str) -> tuple[str, int, str]:
    outputs = record.get("outputs") or {}
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except json.JSONDecodeError:
            outputs = {}
    known = {
        key[len("node_"):-len("_name")]
        for key in outputs
        if key.startswith("node_") and key.endswith("_name")
    }
    if node not in known:
        raise HTTPException(status_code=404, detail=f"Unknown target node '{node}'")
    _, footholds = setup_phase.derive_nodes_footholds(outputs)
    if node in footholds:
        raise HTTPException(status_code=403, detail="headless browser targets must not be footholds")
    target = _victim_internal_target(outputs, node)
    if target is None:
        raise HTTPException(status_code=422, detail="target has no browser-capable web port")
    ip, port = target
    scheme = "https" if port in (443, 8443) else "http"
    return ip, port, scheme


def _http_target(record: dict, node: str) -> tuple[str, int, str]:
    """(ip, port, scheme) for an HTTP research request — same contract as
    `_browser_target`: unknown node -> 404, foothold -> 403, no web port ->
    422. The caller never supplies a URL; only this resolver picks the host."""
    outputs = record.get("outputs") or {}
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except json.JSONDecodeError:
            outputs = {}
    known = {
        key[len("node_"):-len("_name")]
        for key in outputs
        if key.startswith("node_") and key.endswith("_name")
    }
    if node not in known:
        raise HTTPException(status_code=404, detail=f"Unknown target node '{node}'")
    _, footholds = setup_phase.derive_nodes_footholds(outputs)
    if node in footholds:
        raise HTTPException(status_code=403, detail="http request targets must not be footholds")
    target = _victim_internal_target(outputs, node)
    if target is None:
        raise HTTPException(status_code=422, detail="target has no reachable web port")
    ip, port = target
    scheme = "https" if port in (443, 8443) else "http"
    return ip, port, scheme


def _run_arena_http(record: dict, req: HttpRequestRequest, principal=None) -> dict:
    ip, port, scheme = _http_target(record, req.node)
    if resolve_provider_name(record.get("effective_provider") or record.get("provider")) == "docker-local":
        return helper_jobs.execute(record, "http", {
            "node": req.node, "ip": ip, "port": port, "scheme": scheme,
        }, {"path": req.path, "params": req.params, "method": req.method,
            "headers": req.headers, "body": req.body}, principal)
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    return orch.http_request(
        record["id"], req.node, ip, port, scheme, req.path, req.params,
        method=req.method, headers=req.headers, body=req.body,
    )


def _run_arena_browser(
    record: dict, node: str, path: str, params: dict[str, str] | None,
    *, wait_ms: int = 1500, execution_marker: str | None = None,
    principal=None,
) -> dict:
    ip, port, scheme = _browser_target(record, node)
    if resolve_provider_name(record.get("effective_provider") or record.get("provider")) == "docker-local":
        return helper_jobs.execute(record, "browser", {
            "node": node, "ip": ip, "port": port, "scheme": scheme,
        }, {"path": path, "params": params, "wait_ms": wait_ms,
            "execution_marker": execution_marker}, principal)
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    return orch.browser_visit(
        record["id"], node, ip, port, scheme, path, params,
        wait_ms=wait_ms, execution_marker=execution_marker,
    )


@app.post("/arenas/{instance_id}/browser/visit")
@limiter.limit(RATE_LIMIT_EXEC)
def browser_visit(
    request: Request,
    instance_id: str,
    req: BrowserVisitRequest,
    principal: Principal = Depends(require_principal),
):
    """Render one arena target page; arbitrary/external URLs are never accepted."""
    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    try:
        result = _run_arena_browser(
            record, req.node, req.path, req.params, wait_ms=req.wait_ms, principal=principal
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "browser failed"))
    db.record_event(
        instance_id,
        "browser_visit",
        {
            "node": req.node,
            "path": req.path,
            "param_names": sorted(req.params),
            "wait_ms": req.wait_ms,
            "dom_bytes": result.get("dom_bytes"),
            "dom_sha256": result.get("dom_sha256"),
        },
        actor=principal.name,
    )
    return {"node": req.node, **result}


@app.post("/arenas/{instance_id}/http/request")
@limiter.limit(RATE_LIMIT_EXEC)
def arena_http_request(
    request: Request,
    instance_id: str,
    req: HttpRequestRequest,
    principal: Principal = Depends(require_principal),
):
    """Perform one arena-target HTTP transaction; caller URLs are never accepted.

    The response body is returned bounded and hashed; the audit event carries
    metadata and digests only — never request or response bodies."""
    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    return _execute_and_record_http(record, req, principal)


def _execute_and_record_http(
    record: dict, req: HttpRequestRequest, principal: Principal,
    *, replay_of: str | None = None,
) -> dict:
    """Drive one gated HTTP transaction end-to-end: execute against the
    resolved target, persist the content-addressed record, and emit the
    body-free audit event. Shared choke point for drives and replays."""
    instance_id = record["id"]
    try:
        result = _run_arena_http(record, req, principal)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "http request failed"))
    request_view = {
        "node": req.node,
        "method": req.method.upper(),
        "path": req.path,
        "params": req.params,
        "headers": req.headers,
        "body": req.body,
    }
    response_keys = (
        "status", "reason", "http_version", "headers", "header_count",
        "redirect_location", "body", "body_bytes", "body_sha256", "truncated",
    )
    response_view = {key: result[key] for key in response_keys if key in result}
    try:
        transaction = http_transactions.record(
            instance_id,
            request=request_view,
            response=response_view,
            actor=principal.name,
            elapsed_ms=result.get("elapsed_ms"),
            replay_of=replay_of,
        )
    except http_transactions.HttpTransactionError as exc:
        detail = str(exc)
        status = 413 if ("limit" in detail or "capacity" in detail) else 422
        raise HTTPException(status_code=status, detail=detail) from exc
    event_payload = {
        "node": req.node,
        "method": req.method.upper(),
        "path": req.path,
        "param_names": sorted(req.params),
        "header_names": sorted(req.headers),
        "has_body": req.body is not None,
        "status": result.get("status"),
        "reason": result.get("reason"),
        "redirect_location": result.get("redirect_location"),
        "body_bytes": result.get("body_bytes"),
        "body_sha256": result.get("body_sha256"),
        "truncated": result.get("truncated"),
        "elapsed_ms": result.get("elapsed_ms"),
        "transaction_digest": transaction["digest"],
    }
    if replay_of:
        event_payload["replay_of"] = replay_of
    db.record_event(instance_id, "http_request", event_payload, actor=principal.name)
    response = {
        "node": req.node,
        "method": req.method.upper(),
        "path": req.path,
        "transaction_digest": transaction["digest"],
        **result,
    }
    if replay_of:
        response["replay_of"] = replay_of
    return response


def _arena_record_or_404(instance_id: str) -> dict:
    """Fetch a deployment record without requiring it to be active — read-only
    research records (transactions, evidence) stay reviewable after destroy."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    return record


def _http_transaction_or_404(instance_id: str, digest: str):
    try:
        return http_transactions.get(instance_id, digest)
    except http_transactions.HttpTransactionError as exc:
        detail = str(exc)
        if "digest" in detail and "invalid" in detail:
            raise HTTPException(status_code=422, detail=detail) from exc
        raise HTTPException(status_code=404, detail=detail) from exc


@app.get("/arenas/{instance_id}/http/transactions")
@limiter.limit(RATE_LIMIT_EXEC)
def list_arena_http_transactions(
    request: Request,
    instance_id: str,
    limit: int = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_principal),
):
    """List one arena's stored HTTP transactions, newest first (bounded)."""
    _arena_record_or_404(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    return http_transactions.list_transactions(
        instance_id, limit=limit, offset=offset
    )


@app.get("/arenas/{instance_id}/http/transactions/{digest}")
@limiter.limit(RATE_LIMIT_EXEC)
def get_arena_http_transaction(
    request: Request,
    instance_id: str,
    digest: str,
    principal: Principal = Depends(require_principal),
):
    """Retrieve one stored HTTP transaction envelope by digest."""
    _arena_record_or_404(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    manifest, envelope = _http_transaction_or_404(instance_id, digest)
    return {"manifest": manifest, "transaction": envelope}


class HttpReplayRequest(BaseModel):
    """Optional edits over a stored transaction. params/headers MERGE onto the
    stored values (modify one field without restating the rest); node, path,
    method and body REPLACE when provided. The stored record is never mutated —
    a replay always produces a new linked transaction."""

    node: str | None = Field(default=None, min_length=1, max_length=64)
    path: str | None = Field(default=None, min_length=1, max_length=2048)
    params: dict[str, str] | None = Field(default=None)
    headers: dict[str, str] | None = Field(default=None)
    method: str | None = Field(default=None, min_length=1, max_length=32)
    body: str | None = Field(
        default=None, max_length=config.HTTP_MAX_REQUEST_BYTES
    )

    @model_validator(mode="after")
    def _bounded_overrides(self):
        if self.path is not None:
            parsed = urllib.parse.urlsplit(self.path)
            if (
                not self.path.startswith("/")
                or self.path.startswith("//")
                or parsed.scheme
                or parsed.netloc
                or parsed.fragment
                or "\x00" in self.path
            ):
                raise ValueError("path must be an arena-relative URL path without a fragment")
            if parsed.query:
                raise ValueError("put query values in params, not path")
        if self.method is not None and not re.fullmatch(r"[A-Za-z]{1,32}", self.method):
            raise ValueError("method must be 1-32 alphabetic characters")
        if self.params is not None:
            if len(self.params) > 32:
                raise ValueError("params may contain at most 32 entries")
            for key, value in self.params.items():
                if not key or len(key) > 128 or len(value) > 4096:
                    raise ValueError("http parameter names/values exceed configured bounds")
        if self.headers is not None:
            if len(self.headers) > 32:
                raise ValueError("headers may contain at most 32 entries")
            for key, value in self.headers.items():
                if (
                    not key
                    or "\r" in key
                    or "\n" in key
                    or "\r" in value
                    or "\n" in value
                    or len(key) > 128
                    or len(value) > 4096
                ):
                    raise ValueError("http header names/values exceed configured bounds")
        return self


@app.post("/arenas/{instance_id}/http/transactions/{digest}/replay")
@limiter.limit(RATE_LIMIT_EXEC)
def replay_arena_http_transaction(
    request: Request,
    instance_id: str,
    digest: str,
    req: HttpReplayRequest,
    principal: Principal = Depends(require_principal),
):
    """Re-send one stored transaction with optional edits; the original stays
    immutable and the new record links to it via `replay_of`."""
    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    _, stored = _http_transaction_or_404(instance_id, digest)
    sreq = stored.get("request") or {}
    merged = {
        "node": req.node if req.node is not None else sreq.get("node", "victim"),
        "path": req.path if req.path is not None else sreq.get("path", "/"),
        "params": {**(sreq.get("params") or {}), **(req.params or {})},
        "headers": {**(sreq.get("headers") or {}), **(req.headers or {})},
        "method": (req.method or sreq.get("method") or "GET").upper(),
        "body": req.body if req.body is not None else sreq.get("body"),
    }
    try:
        effective = HttpRequestRequest(**merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _execute_and_record_http(record, effective, principal, replay_of=digest)


@app.post("/arenas/{instance_id}/files/upload")
@limiter.limit(RATE_LIMIT_EXEC)
def upload_arena_file(
    request: Request,
    instance_id: str,
    req: TransferUploadRequest,
    principal: Principal = Depends(require_principal),
):
    """Upload one bounded file below the foothold's fixed transfer root."""
    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    node = _transfer_foothold(record, req.node)
    path = _transfer_path(req.path)
    try:
        content = base64.b64decode(req.content_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="content_b64 is not valid base64") from exc
    if len(content) > config.TRANSFER_MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="transfer file exceeds configured limit")
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    try:
        result = orch.write_transfer_file(instance_id, node, path, content)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "upload failed"))
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    db.record_event(
        instance_id,
        "file_upload",
        {"node": node, "path": path, "bytes": len(content), "digest": digest},
        actor=principal.name,
    )
    return {"uploaded": True, "node": node, "digest": digest, **result}


@app.post("/arenas/{instance_id}/files/download")
@limiter.limit(RATE_LIMIT_EXEC)
def download_arena_file(
    request: Request,
    instance_id: str,
    req: TransferDownloadRequest,
    principal: Principal = Depends(require_principal),
):
    """Download one bounded regular foothold file in context-safe chunks."""
    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_EXEC)
    node = _transfer_foothold(record, req.node)
    path = _transfer_path(req.path)
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    try:
        content = orch.read_transfer_file(instance_id, node, path)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if req.offset > len(content):
        raise HTTPException(status_code=416, detail="download offset is past end of file")
    end = min(len(content), req.offset + req.max_bytes)
    chunk = content[req.offset:end]
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    db.record_event(
        instance_id,
        "file_download",
        {
            "node": node, "path": path, "offset": req.offset,
            "returned_bytes": len(chunk), "file_bytes": len(content), "digest": digest,
        },
        actor=principal.name,
    )
    return {
        "node": node,
        "path": path,
        "content_b64": base64.b64encode(chunk).decode("ascii"),
        "offset": req.offset,
        "returned_bytes": len(chunk),
        "file_bytes": len(content),
        "next_offset": end if end < len(content) else None,
        "digest": digest,
    }


@app.post("/arenas/{instance_id}/exec")
@limiter.limit(RATE_LIMIT_EXEC)
def exec_in_arena(
    request: Request,
    instance_id: str,
    req: ExecRequest,
    principal: Principal = Depends(require_principal),
):
    """Run a command inside an arena node (the MCP attacker stance's backend).

    Synchronous — an agent needs the output back in-loop. Provider-enforced
    (docker exec / SSH). Every exec is written to the `events` audit trail,
    which also feeds the future defender stance. Node-scope (foothold-only) is
    enforced by the gateway; this endpoint is the raw infra primitive.
    """
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    if record.get("status") != "active":
        raise HTTPException(
            status_code=409, detail=f"Arena is '{record.get('status')}', not active"
        )

    outputs = record.get("outputs") or {}
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except json.JSONDecodeError:
            outputs = {}

    # D1: an agent may only exec on an arena it is bound to. Checked before node
    # enumeration so an unbound agent can't probe another arena's node names.
    binding = _require_binding(principal, instance_id, bindings.CAP_EXEC)
    # Server-side foothold-scope for the attacker stance (the gateway also screens
    # this client-side; the orchestrator is now authoritative — D1). A None-stance
    # (own-sandbox) binding and operator callers are unrestricted.
    if binding is not None and binding.get("stance") == "attacker":
        _, footholds = setup_phase.derive_nodes_footholds(outputs)
        if footholds and req.node not in footholds:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"the attacker stance may only exec on a foothold node "
                    f"{sorted(footholds)}, not '{req.node}'"
                ),
            )

    known = {
        k[len("node_"):-len("_name")]
        for k in outputs
        if k.startswith("node_") and k.endswith("_name")
    }
    if known and req.node not in known:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown node '{req.node}' (arena nodes: {sorted(known)})",
        )

    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    try:
        deadline = getattr(request.state, "budget_deadline", None)
        timeout = req.timeout
        if deadline is not None:
            remaining = (deadline - datetime.now()).total_seconds()
            if remaining <= 0:
                raise HTTPException(status_code=423, detail="wall-clock budget expired")
            timeout = min(timeout, max(1, int(remaining)))
        result = orch.exec_in_node(instance_id, req.node, req.command, timeout)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e

    if not result.get("success"):
        raise HTTPException(
            status_code=502, detail=f"exec failed: {result.get('error', 'unknown error')}"
        )

    # Audit every command (also the defender stance's future feed).
    db.record_event(
        instance_id, "agent_exec",
        {
            "node": req.node,
            "command": req.command[:512],
            "exit_code": result.get("exit_code"),
            "actor": principal.name,
        },
        actor=principal.name,
    )
    return {
        "node": req.node,
        "exit_code": result.get("exit_code"),
        "stdout": (result.get("stdout") or "")[:EXEC_OUTPUT_CAP],
        "stderr": (result.get("stderr") or "")[:EXEC_OUTPUT_CAP],
    }


class MitmObserveRequest(BaseModel):
    seconds: int = Field(default=6, ge=1, le=60)
    max_packets: int = Field(default=200, ge=1, le=2000)


@app.post("/arenas/{instance_id}/mitm/observe")
@limiter.limit(RATE_LIMIT_EXEC)
def mitm_observe(
    request: Request,
    instance_id: str,
    req: MitmObserveRequest,
    principal: Principal = Depends(require_principal),
):
    """Observe in-flight traffic on the arena's shared segment — the MCP MITM
    stance's backend (in-path observation). Synchronous; bounded by seconds/
    max_packets. D1: an agent must hold an `mitm` binding (CAP_OBSERVE); operators
    bypass. Every capture is audited (`mitm_observe`)."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    if record.get("status") != "active":
        raise HTTPException(
            status_code=409, detail=f"Arena is '{record.get('status')}', not active"
        )
    _require_binding(principal, instance_id, bindings.CAP_OBSERVE)  # D1

    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    try:
        deadline = getattr(request.state, "budget_deadline", None)
        seconds = req.seconds
        if deadline is not None:
            remaining = (deadline - datetime.now()).total_seconds()
            if remaining <= 0:
                raise HTTPException(status_code=423, detail="wall-clock budget expired")
            seconds = min(seconds, max(1, int(remaining)))
        result = orch.capture_traffic(
            instance_id, seconds=seconds, max_packets=req.max_packets
        )
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    if not result.get("success"):
        raise HTTPException(
            status_code=502, detail=f"capture failed: {result.get('error', 'unknown error')}"
        )
    db.record_event(
        instance_id, "mitm_observe",
        {"packets": result.get("packets"), "bridge": result.get("bridge"),
         "seconds": req.seconds, "actor": principal.name},
        actor=principal.name,
    )
    return result


# Audit stream (ADR-0004). Read-only views over the append-only `events` table —
# the operator audit console (WebUI) and the defender stance's detection feed.
EVENTS_MAX_LIMIT = 500


def _redact_findings_for_agent(principal: Principal, events: list[dict]) -> list[dict]:
    """Strip the hidden-manifest match signal (`matched_vuln_id`) from `finding`
    events for non-operator callers. The audit/event stream is readable by the
    defender stance (agent role), but `report_finding` is deliberately neutral so
    the attacker can't enumerate the manifest — leaving `matched_vuln_id` in the
    event feed would hand the agent-under-test exactly that ground truth."""
    if principal.role in OPERATOR_ROLES:
        return events
    # Both the manifest match AND the verification verdict are ground truth: a
    # defender/attacker learning that a finding was `confirmed` would leak whether
    # the exploit worked, defeating the neutral ack. Strip both.
    hidden = ("matched_vuln_id", "validation")
    redacted = []
    for e in events:
        if e.get("type") == "finding_verification":
            # Manual adjudication is operator judgment and can reveal truth.
            continue
        payload = e.get("payload")
        if e.get("type") == "finding" and isinstance(payload, dict) and any(
            k in payload for k in hidden
        ):
            e = {**e, "payload": {k: v for k, v in payload.items() if k not in hidden}}
        redacted.append(e)
    return redacted


@app.get("/events")
def list_events(limit: int = 100, type: str | None = None,
                principal: Principal = Depends(require_principal)):
    """Recent audit events across all arenas (newest first). Optional ``type``
    restricts to one event type — lets a caller pull e.g. `agent_session` without
    it being flooded out of a fixed window by high-volume activity events."""
    limit = max(1, min(limit, EVENTS_MAX_LIMIT))
    types = [type] if type else None
    return {"events": _redact_findings_for_agent(principal, db.list_events(limit=limit, types=types))}


@app.get("/deployments/{instance_id}/events")
def list_arena_events(
    instance_id: str, limit: int = 100, principal: Principal = Depends(require_principal)
):
    """Audit events for a single arena (newest first) — deploy/status/exec/etc."""
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    limit = max(1, min(limit, EVENTS_MAX_LIMIT))
    return {
        "events": _redact_findings_for_agent(
            principal, db.list_events(lab_id=instance_id, limit=limit)
        )
    }


class AgentSessionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=64)
    stance: str | None = Field(default=None, max_length=32)


@app.post("/arenas/{instance_id}/agent-session")
def announce_agent_session(
    instance_id: str,
    req: AgentSessionRequest,
    principal: Principal = Depends(require_principal),
):
    """Record that a bring-your-own agent connected to this arena, with the
    model + provider driving it. The model/provider are self-declared by the
    agent harness (Nidavellir ships no AI) and recorded as an append-only
    `agent_session` event — this powers the operator console's *connected model*
    indicator. Not ground truth; purely an attribution/telemetry signal."""
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    db.record_event(
        instance_id, "agent_session",
        {
            "model": req.model[:128],
            "provider": req.provider[:64],
            "stance": req.stance,
            "actor": principal.name,
        },
        actor=principal.name,
    )
    return {"recorded": True}


# Known-vulnerability manifest & findings (the benchmark model — replaces CTF
# flags). A scenario plants KNOWN vulnerabilities; the agent's goal is to
# DISCOVER them. The manifest is operator-only ground truth; an attacker
# self-reports findings, scored by CWE + node match against the hidden manifest.
OPERATOR_ROLES = ("admin", "operator")


def _require_operator(principal: Principal) -> None:
    """Reveal/score endpoints expose ground truth — agents must not reach them."""
    if principal.role not in OPERATOR_ROLES:
        raise HTTPException(
            status_code=403, detail="operator or admin role required"
        )


# --- Agent ↔ arena bindings (server-enforced key↔arena binding, D1) ----------
# An `agent` key may only DRIVE an arena (exec / report findings / configure the
# victim) it holds an active binding to, and only within the stance the binding
# grants. Operators/admins manage every arena and bypass. State is event-backed
# (bindings.py derives it from agent_binding / agent_binding_revoked events).
# See ROADMAP §2.1 D1 + ADR-0005.

def _arena_binding_events(instance_id: str) -> list[dict]:
    return db.list_events(
        instance_id, limit=bindings.BINDING_EVENT_WINDOW, types=bindings.BINDING_EVENT_TYPES
    )


def _require_binding(principal: Principal, instance_id: str, capability: str) -> dict | None:
    """Gate an agent-driven arena action. Operators/admins bypass (return None);
    an `agent` principal must hold an active binding to `instance_id` whose stance
    permits `capability`, else 403. Returns the binding so the caller can apply
    stance-specific node-scope (e.g. attacker → foothold-only exec)."""
    if principal.role in OPERATOR_ROLES:
        return None
    binding = bindings.binding_for(_arena_binding_events(instance_id), principal.name)
    if binding is None:
        raise HTTPException(
            status_code=403,
            detail=(
                "this agent key is not bound to this arena — an operator must grant "
                "a binding (POST /arenas/{id}/bindings) or the agent must have "
                "deployed the arena itself"
            ),
        )
    if binding.get("paused"):
        # P2-11 kill-switch / pause: reversible operator halt. 423 Locked — the
        # binding still exists (so it's distinct from a 403 revoke) but is frozen
        # until the operator resumes it.
        raise HTTPException(
            status_code=423,
            detail=(
                "this agent's binding is paused by the operator — actions are "
                "halted until it is resumed (POST /arenas/{id}/bindings/{agent}/resume)"
            ),
        )
    if not bindings.stance_permits(binding.get("stance"), capability):
        raise HTTPException(
            status_code=403,
            detail=(
                f"the bound stance {binding.get('stance')!r} may not "
                f"{capability!r} on this arena"
            ),
        )
    return binding


class RuntimeOperation(BaseModel):
    state: str
    reason: str
    recorded: bool
    limits: dict = Field(default_factory=dict)


class RuntimeCapabilities(BaseModel):
    schema_version: str = Field(default="nidavellir.runtime-capabilities.v1", alias="schema")
    arena_id: str
    provider: str
    arena_state: str
    principal_role: str
    binding_stance: str | None
    budget: dict | None
    stop: dict
    footholds: list[str]
    targets: list[dict]
    operations: dict[str, RuntimeOperation]


def _forward_nodes(instance_id: str):
    recipe = db.get_lifecycle_recipe(instance_id)
    if not recipe:
        return []
    return normalized_nodes(recipe.get("scenario") or {})


@app.get("/arenas/{instance_id}/capabilities", response_model=RuntimeCapabilities)
def runtime_capabilities(instance_id: str, principal: Principal = Depends(require_principal)):
    arena = db.get_deployment(instance_id)
    if arena is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    binding = None
    if principal.role == "agent":
        binding = bindings.binding_for(_arena_binding_events(instance_id), principal.name)
        if binding is None:
            raise HTTPException(status_code=403, detail="agent is not bound to this arena")
    provider = arena.get("effective_provider") or arena.get("provider") or "unknown"
    budget = db.budget_status(instance_id)
    policy = budget.get("policy")
    stopped = (not budget.get("system") or budget["system"]["state"] != "open"
               or not budget.get("arena") or budget["arena"]["state"] != "open")
    active = arena["status"] == "active"
    paused = bool(binding and binding.get("paused"))
    nodes = _forward_nodes(instance_id)
    outputs = json.loads(arena.get("outputs") or "{}")

    def permitted(capability):
        return binding is None or bindings.stance_permits(binding.get("stance"), capability)

    def operation(capability, *, provider_required=True, declared=True,
                  runtime_ready=True, limits=None):
        if provider_required and provider != "docker-local":
            state, reason = "unsupported", "provider_not_implemented"
        elif not declared:
            state, reason = "unavailable", "no_declared_service"
        elif not runtime_ready:
            state, reason = "unavailable", "selected_nodes_not_ready"
        elif not permitted(capability):
            state, reason = "unavailable", "stance_denied"
        elif paused:
            state, reason = "unavailable", "binding_paused"
        elif not active:
            state, reason = "supported", "arena_inactive"
        elif stopped:
            state, reason = "unavailable", "stop_active"
        elif not policy:
            state, reason = "unavailable", "legacy_budget_unavailable"
        elif datetime.fromisoformat(policy["deadline"]) <= datetime.now():
            state, reason = "unavailable", "deadline_expired"
        elif policy["remaining"] <= 0:
            state, reason = "unavailable", "action_budget_exhausted"
        else:
            state, reason = "ready", "ok"
        return RuntimeOperation(state=state, reason=reason, recorded=True,
                                limits=limits or {})

    can_forward = permitted(bindings.CAP_FORWARD) and not paused
    footholds = [n["name"] for n in nodes if (n.get("role") == "attacker"
                 or n.get("entrypoint"))] if can_forward else []
    foot_segments = set().union(*(
        set(n.get("segments") or ["_default"]) for n in nodes
        if n["name"] in footholds)) if footholds else set()
    targets = []
    for node in nodes:
        if node["name"] in footholds:
            continue
        targets.append({
            "node": node["name"],
            "ready": outputs.get(f"node_{node['name']}_state") == "running",
            "forward_services": ([s["id"] for s in node.get("forward_services") or []]
                                 if can_forward and foot_segments.intersection(
                                     node.get("segments") or ["_default"]) else []),
        })
    declared = bool(footholds and any(t["forward_services"] for t in targets))
    forward_nodes_ready = (any(outputs.get(f"node_{name}_state") == "running"
                               for name in footholds)
                           and any(t["ready"] and t["forward_services"] for t in targets))
    operations = {
        "exec": operation(bindings.CAP_EXEC, limits={"timeout_seconds": 30}),
        "http": operation(bindings.CAP_EXEC, limits={"relative_path_only": True}),
        "browser": operation(bindings.CAP_EXEC, limits={"selected_target_only": True}),
        "poc": operation(bindings.CAP_EXEC, limits={"network": "selected_http_target"}),
        "files": operation(bindings.CAP_EXEC, limits={"foothold_only": True}),
        "setup": operation(bindings.CAP_SETUP),
        "observe": operation(bindings.CAP_OBSERVE),
        "forward": operation(bindings.CAP_FORWARD, declared=declared,
                             runtime_ready=forward_nodes_ready,
                             limits={"protocol": "tcp", "lease_seconds_max": 300,
                                     "stream_seconds_max": 90, "streams_per_lease": 1,
                                     "bytes_each_direction": 1048576,
                                     "idle_seconds": 15}),
        "recording": RuntimeOperation(state="ready", reason="audit_and_trace",
                                      recorded=True, limits={"bodies_in_audit": False}),
        "token_cost_hard_cap": RuntimeOperation(
            state="unsupported", reason="external_driver_usage_unavailable",
            recorded=False),
    }
    return RuntimeCapabilities(
        arena_id=instance_id, provider=provider, arena_state=arena["status"],
        principal_role=principal.role,
        binding_stance=binding.get("stance") if binding else None,
        budget=policy, stop={"system": budget.get("system"), "arena": budget.get("arena")},
        footholds=footholds, targets=targets, operations=operations,
    )


class ForwardRequest(BaseModel):
    model_config = {"extra": "forbid"}

    foothold: str
    target: str
    service_id: str
    lifetime_seconds: int = Field(default=120, ge=10, le=300)
    idempotency_key: str = Field(min_length=8, max_length=128,
                                 pattern=r"^[A-Za-z0-9._:-]+$")


def _forward_public(row):
    return {key: value for key, value in row.items()
            if key not in {"binding_generation", "stream_id", "principal_role", "segment"}}


def _forward_visible(row, principal):
    if row is None:
        raise HTTPException(status_code=404, detail="Forward not found")
    if principal.role == "agent" and row["principal"] != principal.name:
        raise HTTPException(status_code=404, detail="Forward not found")
    return row


@app.post("/arenas/{instance_id}/forwards")
def open_forward(instance_id: str, req: ForwardRequest, request: Request,
                 principal: Principal = Depends(require_principal)):
    if request.headers.get("X-Token-Budget") or request.headers.get("X-Cost-Budget"):
        raise HTTPException(status_code=422,
                            detail="token/cost caps cannot be enforced for this driver")
    arena = db.get_deployment(instance_id)
    if arena is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    binding = _require_binding(principal, instance_id, bindings.CAP_FORWARD)
    if (arena.get("effective_provider") or arena.get("provider")) != "docker-local":
        raise HTTPException(status_code=422, detail="provider does not support scoped forwards")
    recipe = db.get_lifecycle_recipe(instance_id) or {}
    scenario = recipe.get("scenario") or {}
    if (scenario.get("requires") or {}).get("egress") == "open":
        raise HTTPException(status_code=422, detail="forward requires an egress-locked arena")
    nodes = {node["name"]: node for node in normalized_nodes(scenario)}
    foot, target = nodes.get(req.foothold), nodes.get(req.target)
    if foot is None or target is None or req.foothold == req.target:
        raise HTTPException(status_code=422, detail="invalid declared forward endpoints")
    if foot.get("role") != "attacker" and not foot.get("entrypoint"):
        raise HTTPException(status_code=422, detail="selected node is not a foothold")
    common = set(foot.get("segments") or ["_default"]) & set(
        target.get("segments") or ["_default"])
    if not common:
        raise HTTPException(status_code=422, detail="nodes do not share a declared segment")
    service = next((svc for svc in target.get("forward_services") or []
                    if svc["id"] == req.service_id), None)
    if service is None:
        raise HTTPException(status_code=422, detail="service is not declared on target")
    digest = hashlib.sha256(req.model_dump_json(exclude={"idempotency_key"}).encode()).hexdigest()
    try:
        row = db.create_forward_lease(
            instance_id, principal=principal.name, role=principal.role,
            binding_generation=binding.get("ts") if binding else None,
            key=req.idempotency_key, digest=digest, foothold=req.foothold,
            target=req.target, service_id=req.service_id, segment=sorted(common)[0],
            port=service["port"],
            lifetime_seconds=req.lifetime_seconds)
    except ValueError as exc:
        status_code = (429 if "budget exhausted" in str(exc) else
                       423 if "stop gate" in str(exc) else 409)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _forward_public(row)


@app.get("/arenas/{instance_id}/forwards")
def list_forwards(instance_id: str, principal: Principal = Depends(require_principal)):
    if db.get_deployment(instance_id) is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    if principal.role == "agent":
        _require_binding(principal, instance_id, bindings.CAP_FORWARD)
    return {"forwards": [_forward_public(row) for row in db.list_forward_leases(instance_id)
                         if principal.role != "agent" or row["principal"] == principal.name]}


@app.get("/arenas/{instance_id}/forwards/{forward_id}")
def forward_status(instance_id: str, forward_id: str,
                   principal: Principal = Depends(require_principal)):
    row = _forward_visible(db.get_forward_lease(forward_id), principal)
    if row["arena_id"] != instance_id:
        raise HTTPException(status_code=404, detail="Forward not found")
    return _forward_public(row)


@app.post("/arenas/{instance_id}/forwards/{forward_id}/revoke")
def revoke_forward(instance_id: str, forward_id: str,
                   principal: Principal = Depends(require_principal)):
    row = _forward_visible(db.get_forward_lease(forward_id), principal)
    if row["arena_id"] != instance_id:
        raise HTTPException(status_code=404, detail="Forward not found")
    if principal.role == "agent":
        _require_binding(principal, instance_id, bindings.CAP_FORWARD)
    return _forward_public(db.revoke_forward_lease(forward_id, actor=principal.name))


@app.websocket("/arenas/{instance_id}/forwards/{forward_id}/connect")
async def connect_forward(websocket: WebSocket, instance_id: str, forward_id: str):
    """Authenticated binary stream. Credentials are accepted only in headers."""
    import redis.asyncio as aioredis

    key = websocket.headers.get("X-API-Key")
    record = db.get_api_key(hash_api_key(key)) if key else None
    if record is None:
        await websocket.close(code=4401)
        return
    principal = Principal(record["name"], record["role"])
    row = db.get_forward_lease(forward_id)
    if (row is None or row["arena_id"] != instance_id or row["principal"] != principal.name):
        await websocket.close(code=4404)
        return
    try:
        binding = _require_binding(principal, instance_id, bindings.CAP_FORWARD)
        generation = binding.get("ts") if binding else None
        if generation != row["binding_generation"]:
            raise ValueError("forward binding generation changed")
        action_id, _ = db.reserve_budget_action(
            instance_id, key=str(uuid.uuid4()),
            digest=hashlib.sha256(forward_id.encode()).hexdigest(),
            kind="forward/connect", actor=principal.name)
        try:
            row = db.claim_forward_stream(
                forward_id, principal=principal.name, binding_generation=generation)
        except Exception:
            db.settle_budget_action(action_id, outcome="released")
            raise
        db.settle_budget_action(action_id, outcome="spent")
    except (HTTPException, ValueError):
        await websocket.close(code=4403)
        return
    channel = f"nv:forward:{row['stream_id']}"
    queue_in, queue_out, close_key = channel + ":in", channel + ":out", channel + ":close"
    redis_client = aioredis.from_url(os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))
    await redis_client.expire(queue_in, 120)
    run_forward_stream.delay(forward_id)
    await websocket.accept()

    async def from_client():
        total = 0
        while True:
            chunk = await websocket.receive_bytes()
            if not chunk:
                continue
            total += len(chunk)
            if len(chunk) > 16384 or total > 1048576:
                break
            await redis_client.rpush(queue_in, chunk)
            await redis_client.expire(queue_in, 120)

    async def to_client():
        while True:
            if not db.forward_stream_valid(forward_id):
                break
            if principal.role == "agent":
                current = bindings.binding_for(_arena_binding_events(instance_id), principal.name)
                if (current is None or current.get("paused")
                        or current.get("ts") != row["binding_generation"]):
                    break
            item = await redis_client.blpop(queue_out, timeout=1)
            if item is None:
                updated = db.get_forward_lease(forward_id)
                if updated is None or (datetime.now() - datetime.fromisoformat(
                        updated["updated_at"])).total_seconds() > 10:
                    break
                continue
            frame = item[1]
            if frame == b"C":
                break
            if frame.startswith(b"D"):
                await websocket.send_bytes(frame[1:])

    sender = asyncio.create_task(from_client())
    receiver = asyncio.create_task(to_client())
    try:
        await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
    finally:
        await redis_client.set(close_key, "1", ex=120)
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        await redis_client.aclose()
        try:
            await websocket.close()
        except RuntimeError:
            pass


class StopRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128,
                                 pattern=r"^[A-Za-z0-9._:-]+$")


class BudgetPolicyRequest(BaseModel):
    action_cap: int = Field(ge=1, le=100000)
    deadline: datetime
    reason: str = Field(min_length=1, max_length=500)
    token_cap: int | None = None
    cost_cap: float | None = None


@app.post("/arenas/{instance_id}/budget/policy")
def update_budget_policy(instance_id: str, req: BudgetPolicyRequest,
                         principal: Principal = Depends(require_principal)):
    _require_operator(principal)
    if req.token_cap is not None or req.cost_cap is not None:
        raise HTTPException(
            status_code=422, detail="token/cost caps cannot be enforced for external agents"
        )
    try:
        version = db.revise_budget_policy(
            instance_id, action_cap=req.action_cap,
            deadline=req.deadline.astimezone().replace(tzinfo=None),
            actor=principal.name, reason=req.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"version": version, "status": db.budget_status(instance_id)}


@app.get("/arenas/{instance_id}/budget")
def get_arena_budget(instance_id: str, principal: Principal = Depends(require_principal)):
    if db.get_deployment(instance_id) is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    if principal.role == "agent":
        binding = bindings.binding_for(_arena_binding_events(instance_id), principal.name)
        if binding is None:
            raise HTTPException(status_code=403, detail="agent is not bound to this arena")
    return db.budget_status(instance_id)


@app.post("/arenas/{instance_id}/stop")
def stop_arena(instance_id: str, req: StopRequest,
               principal: Principal = Depends(require_principal)):
    _require_operator(principal)
    if db.get_deployment(instance_id) is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    epoch = db.stop_budget_gate(instance_id, actor=principal.name,
                                reason=req.reason, key=req.idempotency_key)
    db.revoke_arena_forwards(instance_id, actor=principal.name, reason="arena_stop")
    cancelled = db.request_cancel_arena_poc_jobs(instance_id)
    db.reconcile_budget_stop(instance_id)
    return {"epoch": epoch, "cancel_requested": cancelled,
            "status": db.budget_status(instance_id)}


@app.post("/arenas/{instance_id}/resume")
def resume_arena(instance_id: str, req: StopRequest,
                 principal: Principal = Depends(require_principal)):
    _require_operator(principal)
    try:
        epoch = db.resume_budget_gate(instance_id, actor=principal.name,
                                      reason=req.reason, key=req.idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"epoch": epoch, "status": db.budget_status(instance_id)}


@app.get("/system/emergency-stop")
def system_stop_status(principal: Principal = Depends(require_principal)):
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return db.budget_status("")['system']


@app.post("/system/emergency-stop")
def system_emergency_stop(req: StopRequest,
                          principal: Principal = Depends(require_principal)):
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    epoch = db.stop_budget_gate("system", actor=principal.name,
                               reason=req.reason, key=req.idempotency_key)
    for arena in db.list_deployments():
        db.revoke_arena_forwards(arena["id"], actor=principal.name,
                                 reason="system_stop")
    cancelled = sum(db.request_cancel_arena_poc_jobs(dep["id"])
                    for dep in db.list_deployments())
    db.reconcile_budget_stop("system")
    return {"epoch": epoch, "cancel_requested": cancelled,
            "status": db.budget_status("")["system"]}


@app.post("/system/emergency-stop/clear")
def clear_system_emergency_stop(req: StopRequest,
                                principal: Principal = Depends(require_principal)):
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    try:
        epoch = db.resume_budget_gate("system", actor=principal.name,
                                      reason=req.reason, key=req.idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"epoch": epoch, "status": db.budget_status("")["system"]}


def _autobind_deployer(principal: Principal, instance_id: str) -> None:
    """Bind the deploying agent to the arena it just created (its own sandbox),
    with an unrestricted (stance=None) binding. No-op for operators/admins — they
    are never bound. This is the 'claimed at deploy' half of D1."""
    if principal.role in OPERATOR_ROLES:
        return
    db.record_event(
        instance_id, bindings.BINDING_GRANT,
        {"agent_name": principal.name, "stance": None, "auto": True,
         "granted_by": principal.name},
        actor=principal.name,
    )


class BindingRequest(BaseModel):
    agent_name: str = Field(min_length=1, max_length=128)
    # The stance the agent is allowed to take on this arena. None = unrestricted.
    stance: str | None = Field(default=None, max_length=32)

    @field_validator("stance")
    @classmethod
    def _known_stance(cls, value: str | None) -> str | None:
        if value is not None and value not in bindings.STANCES:
            raise ValueError(
                f"unknown stance {value!r}; expected one of {bindings.STANCES} or null"
            )
        return value


@app.post("/arenas/{instance_id}/bindings")
def grant_binding(
    instance_id: str,
    req: BindingRequest,
    principal: Principal = Depends(require_principal),
):
    """Authorize an agent key (by name) to drive this arena in a given stance.
    Operator-only — the operator decides which BYO agent is the system-under-test
    for which arena. Re-granting updates the stance."""
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    db.record_event(
        instance_id, bindings.BINDING_GRANT,
        {"agent_name": req.agent_name, "stance": req.stance, "auto": False,
         "granted_by": principal.name},
        actor=principal.name,
    )
    logger.info(
        f"Bound agent '{req.agent_name}' (stance={req.stance}) to arena "
        f"{instance_id} by '{principal.name}'"
    )
    return {"bound": True, "agent_name": req.agent_name, "stance": req.stance}


@app.get("/arenas/{instance_id}/bindings")
def list_bindings(instance_id: str, principal: Principal = Depends(require_principal)):
    """The arena's active agent bindings. Operator-only."""
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    return {"bindings": bindings.active_bindings(_arena_binding_events(instance_id))}


@app.delete("/arenas/{instance_id}/bindings/{agent_name}")
def revoke_binding(
    instance_id: str, agent_name: str, principal: Principal = Depends(require_principal)
):
    """Revoke an agent's binding to this arena — it can no longer drive it.
    Operator-only. Idempotent (revoking a non-bound agent is a no-op)."""
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    if bindings.binding_for(_arena_binding_events(instance_id), agent_name) is None:
        return {"revoked": False, "detail": "no active binding for that agent"}
    db.record_event(
        instance_id, bindings.BINDING_REVOKE,
        {"agent_name": agent_name, "reason": "operator", "granted_by": principal.name},
        actor=principal.name,
    )
    for lease in db.list_forward_leases(instance_id):
        if lease["principal"] == agent_name:
            db.revoke_forward_lease(lease["id"], actor=principal.name,
                                    reason="binding_revoked")
    logger.info(f"Revoked agent '{agent_name}' binding on arena {instance_id} by '{principal.name}'")
    return {"revoked": True, "agent_name": agent_name}


@app.post("/arenas/{instance_id}/bindings/{agent_name}/pause")
def pause_binding(
    instance_id: str, agent_name: str, principal: Principal = Depends(require_principal)
):
    """Pause (reversibly halt) an agent's binding — a kill-switch that stops the
    agent driving this arena without tearing the binding down. Gated actions
    return 423 while paused; `resume` lifts it. Operator-only, idempotent."""
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    events = _arena_binding_events(instance_id)
    if bindings.binding_for(events, agent_name) is None:
        raise HTTPException(status_code=404, detail="no active binding for that agent")
    if bindings.is_paused(events, agent_name):
        return {"paused": True, "agent_name": agent_name, "detail": "already paused"}
    db.record_event(
        instance_id, bindings.BINDING_PAUSE,
        {"agent_name": agent_name, "granted_by": principal.name},
        actor=principal.name,
    )
    for lease in db.list_forward_leases(instance_id):
        if lease["principal"] == agent_name:
            db.revoke_forward_lease(lease["id"], actor=principal.name,
                                    reason="binding_paused")
    logger.info(f"Paused agent '{agent_name}' binding on arena {instance_id} by '{principal.name}'")
    return {"paused": True, "agent_name": agent_name}


@app.post("/arenas/{instance_id}/bindings/{agent_name}/resume")
def resume_binding(
    instance_id: str, agent_name: str, principal: Principal = Depends(require_principal)
):
    """Resume a paused binding — the agent may drive the arena again. Operator-only,
    idempotent (resuming a non-paused binding is a no-op)."""
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    events = _arena_binding_events(instance_id)
    if bindings.binding_for(events, agent_name) is None:
        raise HTTPException(status_code=404, detail="no active binding for that agent")
    if not bindings.is_paused(events, agent_name):
        return {"paused": False, "agent_name": agent_name, "detail": "not paused"}
    db.record_event(
        instance_id, bindings.BINDING_RESUME,
        {"agent_name": agent_name, "granted_by": principal.name},
        actor=principal.name,
    )
    logger.info(f"Resumed agent '{agent_name}' binding on arena {instance_id} by '{principal.name}'")
    return {"paused": False, "agent_name": agent_name}


# --- BYO model connection (operator's session-bound agent credential) -------
# The operator configures their bring-your-own model (provider + model + API
# key) once, from the console's model bubble. The key is encrypted at rest and
# the connection sits in *standby* ("active but waiting") until a feature needs
# it — the scenario generator (P3) or an arena whose mode uses an agent in a
# stance (P2 / white-box SUT). Nidavellir custodies the key and provides the
# connection plumbing; the model is the operator's (scope boundary holds — the
# platform never launches the agent on its own, and arenas stay AI-optional).
# Operator/admin only; an agent-role key must never manage credentials.
MODEL_PROVIDERS = ("anthropic", "openai", "openrouter", "huggingface", "gemini",
                   "deepseek", "ollama", "local", "custom")
# Keyless: local runtimes / a self-hosted custom endpoint may run without a key.
_KEYLESS_PROVIDERS = ("local", "ollama", "custom")


class ModelConnectionRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(default="", max_length=512)
    # Per-connection OpenAI-compatible base URL (P3-4) — overrides the provider
    # preset + NIDAVELLIR_MODEL_BASE_URL. Required for `custom`/`local`; optional
    # for named OpenAI-compatible providers.
    base_url: str | None = Field(default=None, max_length=512)

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value.lower() not in MODEL_PROVIDERS:
            raise ValueError(
                f"unknown model provider '{value}' "
                f"(known: {', '.join(MODEL_PROVIDERS)})"
            )
        return value.lower()


@app.put("/agent/model")
def set_model_connection(
    req: ModelConnectionRequest,
    principal: Principal = Depends(require_principal),
):
    """Store the operator's bring-your-own model credential, bound to the
    operator. The API key is encrypted at rest, never logged, and never returned
    — only a masked last-4 is surfaced. Resets the connection to *standby*."""
    _require_operator(principal)
    existing = db.get_model_connection(principal.name)
    keep_key = False
    if not req.api_key:
        if existing and existing.get("provider") == req.provider:
            keep_key = True  # update model only; retain the stored key
        elif req.provider not in _KEYLESS_PROVIDERS:
            raise HTTPException(
                status_code=422,
                detail=f"provider '{req.provider}' requires an API key",
            )
    masked = db.upsert_model_connection(
        principal.name, req.provider, req.model, req.api_key,
        base_url=req.base_url, keep_key=keep_key,
    )
    # Only the non-secret provider/model are logged — never the key.
    logger.info(
        f"Model connection configured by '{principal.name}': "
        f"provider={req.provider} model={req.model} (key encrypted at rest)"
    )
    return masked


@app.get("/agent/model")
def read_model_connection(principal: Principal = Depends(require_principal)):
    """The operator's current model connection (masked — never the key), or
    {"configured": false}."""
    _require_operator(principal)
    return db.get_model_connection(principal.name) or {"configured": False}


@app.delete("/agent/model")
def remove_model_connection(principal: Principal = Depends(require_principal)):
    """Forget the operator's stored model credential."""
    _require_operator(principal)
    return {"removed": db.delete_model_connection(principal.name)}


class ModelVerifyRequest(BaseModel):
    # All optional: with provider+api_key, verify the supplied credential
    # (pre-save "test"); with an empty body, verify the operator's stored one.
    provider: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)


@app.post("/agent/model/verify")
def verify_model_connection(
    req: ModelVerifyRequest,
    principal: Principal = Depends(require_principal),
):
    """Best-effort liveness check of a model credential (lists the provider's
    models — no inference, no agent run). With provider+api_key, checks the
    supplied key; otherwise checks the operator's stored credential. Returns
    {verified, detail, checked}; never blocks/stores anything. Operator-only."""
    _require_operator(principal)
    if req.api_key and req.provider:
        provider, model, api_key = req.provider.lower(), req.model or "", req.api_key
        base_url = req.base_url
    else:
        cred = db.get_decrypted_model_credential(principal.name)
        if not cred:
            raise HTTPException(status_code=404, detail="no model connection to verify")
        provider, model, api_key = cred["provider"], cred["model"], cred["api_key"]
        base_url = cred.get("base_url")
    return model_verify.verify_credential(provider, model, api_key, base_url=base_url)


# --- Co-pilot chat (operator's connected model + arena context) -------------
# The console co-pilot: the operator converses with their own connected model;
# Nidavellir injects the current arena's context and streams the reply. Advise-
# only (no tools), operator-only, key decrypted in-process and never logged.

def _build_copilot_context(arena_id: str | None) -> str:
    parts = [
        "You are Nidavellir Co-pilot, a security-testing assistant embedded in an "
        "operator's arena console. Be concise, concrete, and practical. You ADVISE "
        "ONLY — you cannot run commands or change anything; the operator acts through "
        "the console (deploy, run setup steps, approve agent proposals, submit "
        "findings). Help them reason about the target, plan steps, and interpret "
        "results.",
    ]
    if not arena_id:
        parts.append("\nNo specific arena is selected right now.")
        return "\n".join(parts)
    record = db.get_deployment(arena_id)
    if not record:
        parts.append(f"\n(Arena {arena_id} not found.)")
        return "\n".join(parts)

    parts.append(
        f"\nCurrent arena: {arena_id}\n"
        f"- scenario: {record.get('scenario')}\n"
        f"- status: {record.get('status')}  provider: {record.get('provider') or 'default'}"
    )
    nodes, footholds = _nodes_and_footholds(record)
    if nodes:
        outputs = _arena_node_outputs(record)
        desc = []
        for n in sorted(nodes):
            tags = []
            if n in footholds:
                tags.append("foothold")
            url = outputs.get(f"node_{n}_url")
            if url:
                tags.append(url)
            desc.append(f"{n}" + (f" ({', '.join(tags)})" if tags else ""))
        parts.append("- nodes: " + "; ".join(desc))

    sess = setup_phase.current_session(_setup_events(arena_id))
    if sess:
        parts.append(
            f"- setup phase OPEN (mode={sess['mode']}, scope={sess['nodes']}, "
            f"steps_run={sess['steps_run']}/{sess['command_budget']}, "
            f"egress={'on' if sess.get('setup_egress') else 'off'})"
        )

    manifest = scenarios.scenario_manifest(record.get("scenario"))
    if manifest:
        found = {
            (e.get("payload") or {}).get("matched_vuln_id")
            for e in _finding_events(arena_id)
        }
        found.discard(None)
        parts.append(
            f"- benchmark: {len(found)}/{len(manifest)} known vulnerabilities discovered "
            "(operator-only ground truth — don't parrot the answer key to a tester)."
        )

    recent = [
        f"{e.get('type')}({(e.get('payload') or {}).get('node') or ''})"
        for e in db.list_events(arena_id, limit=15)
    ]
    if recent:
        parts.append("- recent activity (newest first): " + ", ".join(recent))
    return "\n".join(parts)


class ChatRequest(BaseModel):
    arena_id: str | None = Field(default=None, max_length=64)
    messages: list[dict] = Field(min_length=1, max_length=40)


@app.post("/agent/chat")
def agent_chat(req: ChatRequest, principal: Principal = Depends(require_principal)):
    """Stream a co-pilot reply from the operator's connected model with the
    arena's context injected. Operator-only; advise-only (no tools)."""
    _require_operator(principal)
    cred = db.get_decrypted_model_credential(principal.name)
    if not cred:
        raise HTTPException(
            status_code=409,
            detail="no model connected — configure one via the model bubble first",
        )
    system = _build_copilot_context(req.arena_id)
    messages = [
        {"role": m.get("role", "user"), "content": str(m.get("content", ""))[:8000]}
        for m in req.messages if m.get("role") in ("user", "assistant")
    ][-30:]
    if not messages:
        raise HTTPException(status_code=422, detail="no user/assistant messages")

    def gen():
        yield from model_chat.stream_chat(
            cred["provider"], cred["model"], cred["api_key"], system, messages,
            base_url=cred.get("base_url"),
        )

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


# --- Configurator setup phase (SUT arenas, ADR-0007 / P2-10 increment 1) -----
# The operator-scripted (AI-optional) path: a human operator brings an arbitrary
# service up on the victim node through a consented, time-boxed, victim-scoped,
# budgeted setup session — every step audited. No gateway/AI and no HITL flow yet
# (increments 2/3). Enforcement lives here (the orchestrator), per the design.

def _arena_node_outputs(record) -> dict:
    outputs = record.get("outputs") or {}
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except json.JSONDecodeError:
            outputs = {}
    return outputs


def _nodes_and_footholds(record) -> tuple[set[str], set[str]]:
    """All node names and the foothold (attacker) node names. A foothold is any
    node the provider exposed a shell command for (matches the gateway). Victim
    scope = everything that is not a foothold."""
    return setup_phase.derive_nodes_footholds(_arena_node_outputs(record))


def _workspace_catalog(record: dict) -> dict[str, dict]:
    """Provider-discovered source workspaces, keyed by target node.

    Paths never come from an HTTP caller.  Writable SUT checkouts live on the
    target node; explicitly white-box checkouts are isolated research copies on
    an attacker foothold. Keeping both candidates lets authorization select the
    least-privileged view for each stance.
    """
    outputs = _arena_node_outputs(record)
    _, footholds = setup_phase.derive_nodes_footholds(outputs)
    foothold = sorted(footholds)[0] if footholds else None
    catalog: dict[str, dict] = {}
    for key, value in outputs.items():
        if not isinstance(value, str) or not value.startswith("/"):
            continue
        if key.startswith("node_") and key.endswith("_sut_source"):
            node = key[len("node_"):-len("_sut_source")]
            catalog.setdefault(node, {})["sut"] = {
                "kind": "sut",
                "node": node,
                "exec_node": node,
                "source_path": value,
                "writable": True,
                "whitebox": bool(outputs.get(f"node_{node}_whitebox")),
            }
        elif key.startswith("node_") and key.endswith("_whitebox_source") and foothold:
            node = key[len("node_"):-len("_whitebox_source")]
            catalog.setdefault(node, {})["whitebox"] = {
                "kind": "whitebox",
                "node": node,
                "exec_node": foothold,
                "source_path": value,
                # Dedicated agent research copy: writable from the foothold but
                # not mounted into or executed by the running target.
                "writable": True,
                "whitebox": True,
            }
    return catalog


def _accessible_workspaces(
    record: dict, principal: Principal, binding: dict | None
) -> list[dict]:
    """Select the workspace representation allowed for this principal.

    Attackers only see the explicitly white-box research copy. Configurators see
    the writable setup checkout. An operator, or an agent's unrestricted personal
    sandbox binding, gets the writable checkout when available and otherwise
    the white-box view.
    """
    stance = binding.get("stance") if binding is not None else None
    operator = principal.role in OPERATOR_ROLES
    result = []
    for node, candidates in sorted(_workspace_catalog(record).items()):
        selected = None
        access = None
        if operator or stance is None:
            selected = candidates.get("sut") or candidates.get("whitebox")
            access = "operator" if operator else "sandbox"
        elif stance == "configurator":
            selected = candidates.get("sut")
            access = "setup"
        elif stance == "attacker":
            selected = candidates.get("whitebox")
            access = "whitebox"
        if selected:
            result.append({**selected, "access": access})
    return result


def _workspace_public_view(workspace: dict) -> dict:
    return {
        "kind": workspace["kind"],
        "node": workspace["node"],
        "source_path": workspace["source_path"],
        "writable": workspace["writable"],
        "whitebox": workspace["whitebox"],
        "access": workspace["access"],
    }


def _authorized_workspace(
    record: dict, principal: Principal, binding: dict | None, workspace_node: str
) -> dict:
    visible = {
        item["node"]: item
        for item in _accessible_workspaces(record, principal, binding)
    }
    workspace = visible.get(workspace_node)
    if workspace is None:
        # Do not reveal whether the node has hidden black-box source.
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@app.get("/arenas/{instance_id}/workspaces")
def list_arena_workspaces(
    instance_id: str,
    principal: Principal = Depends(require_principal),
):
    """List Git workspaces the caller may inspect without exposing black-box source."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    if record.get("status") != "active":
        raise HTTPException(
            status_code=409, detail=f"Arena is '{record.get('status')}', not active"
        )
    binding = _require_binding(principal, instance_id, bindings.CAP_WORKSPACE)
    workspaces = [
        _workspace_public_view(item)
        for item in _accessible_workspaces(record, principal, binding)
    ]
    return {"arena_id": instance_id, "workspaces": workspaces}


@app.get("/arenas/{instance_id}/preflight")
def get_arena_preflight(
    instance_id: str,
    principal: Principal = Depends(require_principal),
):
    """Return the immutable target manifest and latest infrastructure preflight."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    _require_binding(principal, instance_id, bindings.CAP_LIFECYCLE)
    events = db.list_events(
        instance_id, limit=1, types=(research_session.PREFLIGHT_EVENT,)
    )
    if events:
        return {"arena_id": instance_id, **(events[0].get("payload") or {})}

    # Pending/deploying SUT sessions already carry their immutable target in the
    # creation event. Surface it without pretending the infrastructure was checked.
    prearm = db.list_events(
        instance_id, limit=1, types=("session_prearm", "setup_prearm")
    )
    if prearm:
        target = (prearm[0].get("payload") or {}).get("target_manifest")
        return {
            "arena_id": instance_id,
            "status": "pending",
            "phase": "infrastructure",
            "ready": False,
            "next": "wait_for_deployment",
            "target": target,
            "checks": [],
            "failed_checks": [],
            "reset_contract": (target or {}).get("reset"),
        }
    raise HTTPException(
        status_code=404, detail="This arena has no research-session preflight"
    )


@app.get("/arenas/{instance_id}/workspaces/{workspace_node}/diff")
def get_arena_workspace_diff(
    instance_id: str,
    workspace_node: str,
    base: str = Query(default="HEAD", min_length=4, max_length=80),
    path: str | None = Query(default=None, max_length=512),
    context_lines: int = Query(default=3, ge=0, le=20),
    start_line: int = Query(default=0, ge=0),
    max_lines: int = Query(default=300, ge=1, le=500),
    principal: Principal = Depends(require_principal),
):
    """Return one bounded, read-only Git diff page for an authorized workspace."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    if record.get("status") != "active":
        raise HTTPException(
            status_code=409, detail=f"Arena is '{record.get('status')}', not active"
        )
    binding = _require_binding(principal, instance_id, bindings.CAP_WORKSPACE)
    workspace = _authorized_workspace(record, principal, binding, workspace_node)

    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    try:
        result = orch.workspace_diff(
            instance_id,
            workspace["exec_node"],
            workspace["source_path"],
            base=base,
            path=path,
            context_lines=context_lines,
            start_line=start_line,
            max_lines=max_lines,
        )
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    if not result.get("success"):
        raise HTTPException(
            status_code=422,
            detail=f"workspace inspection failed: {result.get('error', 'unknown error')}",
        )

    # Diff contents may contain secrets or exploit material, so audit metadata
    # only. The user/agent gets the content in this response, not in the event log.
    db.record_event(
        instance_id,
        "workspace_diff",
        {
            "node": workspace_node,
            "base": base,
            "path": path,
            "changed_file_count": result.get("changed_file_count", 0),
            "start_line": start_line,
            "returned_lines": result.get("returned_lines", 0),
        },
        actor=principal.name,
    )
    result["workspace"] = _workspace_public_view(workspace)
    return result


class WorkspacePatchRequest(BaseModel):
    base: str = Field(default="HEAD", min_length=4, max_length=80)
    path: str | None = Field(default=None, max_length=512)
    context_lines: int = Field(default=3, ge=0, le=20)
    include_untracked_paths: list[str] = Field(default_factory=list, max_length=10)


def _untracked_patch(path: str, content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"untracked file {path!r} is binary; use filesystem-manifest "
                "evidence when binary target support lands"
            ),
        ) from exc
    body = "".join(
        difflib.unified_diff(
            [], text.splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/{path}"
        )
    )
    return f"diff --git a/{path} b/{path}\nnew file mode 100644\n{body}"


def _complete_workspace_diff(
    orch: Orchestrator, instance_id: str, workspace: dict, req: WorkspacePatchRequest
) -> tuple[dict, str]:
    """Collect every bounded provider page into one capped canonical patch."""
    chunks: list[str] = []
    start = 0
    first = None
    total_bytes = 0
    while True:
        result = orch.workspace_diff(
            instance_id,
            workspace["exec_node"],
            workspace["source_path"],
            base=req.base,
            path=req.path,
            context_lines=req.context_lines,
            start_line=start,
            max_lines=500,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=422,
                detail=f"workspace export failed: {result.get('error', 'unknown error')}",
            )
        first = first or result
        page = result.get("diff") or ""
        if page:
            chunks.append(page)
            total_bytes += len(page.encode("utf-8")) + 1
        if total_bytes > config.EVIDENCE_ARTIFACT_MAX_BYTES:
            raise HTTPException(status_code=413, detail="workspace patch exceeds artifact limit")
        next_start = result.get("next_start_line")
        if next_start is None:
            break
        if not isinstance(next_start, int) or next_start <= start:
            raise HTTPException(status_code=422, detail="provider returned invalid diff pagination")
        start = next_start
    return first or {}, "\n".join(chunks) + ("\n" if chunks else "")


@app.post("/arenas/{instance_id}/workspaces/{workspace_node}/patch-artifacts")
def export_workspace_patch(
    instance_id: str,
    workspace_node: str,
    req: WorkspacePatchRequest,
    principal: Principal = Depends(require_principal),
):
    """Export the exact bounded change view as an arena-scoped SHA-256 artifact."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    if record.get("status") != "active":
        raise HTTPException(
            status_code=409, detail=f"Arena is '{record.get('status')}', not active"
        )
    binding = _require_binding(principal, instance_id, bindings.CAP_WORKSPACE)
    workspace = _authorized_workspace(record, principal, binding, workspace_node)
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    try:
        summary, patch = _complete_workspace_diff(orch, instance_id, workspace, req)
        included_untracked = []
        for selected in req.include_untracked_paths:
            content = orch.workspace_untracked_file(
                instance_id, workspace["exec_node"], workspace["source_path"], selected
            )
            rendered = _untracked_patch(selected, content)
            patch += ("\n" if patch and not patch.endswith("\n\n") else "") + rendered
            included_untracked.append({"path": selected, "bytes": len(content)})
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        metadata = evidence_artifact.store_patch(
            instance_id,
            patch.encode("utf-8"),
            {
                "node": workspace_node,
                "base": req.base,
                "baseline": summary.get("baseline"),
                "path": req.path,
                "context_lines": req.context_lines,
                "changed_file_count": summary.get("changed_file_count", 0),
                "groups": summary.get("groups", {}),
                "included_untracked": included_untracked,
            },
        )
    except evidence_artifact.EvidenceArtifactError as exc:
        status = 413 if "limit" in str(exc) or "capacity" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    db.record_event(
        instance_id,
        "evidence_artifact",
        {
            "digest": metadata["digest"],
            "kind": metadata["kind"],
            "node": workspace_node,
            "bytes": metadata["bytes"],
            "changed_file_count": metadata["changed_file_count"],
        },
        actor=principal.name,
    )
    return {
        "artifact": metadata,
        "patch": patch,
        "download_path": (
            f"/arenas/{instance_id}/evidence-artifacts/{metadata['digest']}"
        ),
    }


@app.get("/arenas/{instance_id}/evidence-artifacts/{digest}")
def download_evidence_artifact(
    instance_id: str,
    digest: str,
    principal: Principal = Depends(require_principal),
):
    """Download a verified evidence body after re-checking arena/workspace scope."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    binding = _require_binding(principal, instance_id, bindings.CAP_WORKSPACE)
    try:
        metadata, content = evidence_artifact.get(instance_id, digest)
    except evidence_artifact.EvidenceArtifactError as exc:
        raise HTTPException(status_code=404, detail="Evidence artifact not found") from exc
    _authorized_workspace(record, principal, binding, metadata.get("node", ""))
    filename = f"{metadata.get('node', 'workspace')}-{digest[-12:]}.patch"
    return Response(
        content=content,
        media_type="text/x-diff",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": f'"{digest}"',
        },
    )


class SetupStartRequest(BaseModel):
    # Victim scope; default = all non-foothold nodes. Foothold/attacker nodes are
    # never configurable (the configurator is victim-scoped by design).
    nodes: list[str] | None = Field(default=None)
    time_box_seconds: int = Field(
        default=setup_phase.DEFAULT_TIME_BOX_SECONDS, ge=60,
        le=setup_phase.MAX_TIME_BOX_SECONDS,
    )
    command_budget: int = Field(
        default=setup_phase.DEFAULT_COMMAND_BUDGET, ge=1, le=setup_phase.MAX_COMMAND_BUDGET
    )
    # Opt-in OPEN setup egress (ADR-0007): real internet on the victim during
    # setup so any dependency can be fetched; revoked before the engagement.
    setup_egress: bool = Field(default=False)
    # How the service is brought up — the consent choice:
    #   operator    — the operator runs steps directly (AI-optional; increment 1)
    #   hitl        — an agent proposes each step, the operator approves (inc. 2)
    #   autonomous  — an agent runs steps directly (inc. 3; double-locked)
    mode: str = Field(default=setup_phase.MODE_OPERATOR)
    # The agent key (by name) that may drive this setup session via the gateway's
    # configurator stance. Naming it here grants that agent a `configurator`
    # binding to the arena for the session (D1 "claimed at setup/start"); it is
    # revoked at setup/finish so the capability is dropped before the engagement.
    agent_name: str | None = Field(default=None, max_length=128)

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        if value not in setup_phase.MODES:
            raise ValueError(f"unknown setup mode '{value}'; expected one of {setup_phase.MODES}")
        return value


def _setup_events(instance_id: str) -> list[dict]:
    # Only setup-lifecycle events, so engagement noise (agent_exec/status/finding)
    # can't push the open session out of the window (the 500-event window bug).
    return db.list_events(
        instance_id, limit=setup_phase.SETUP_EVENT_WINDOW, types=setup_phase.SETUP_EVENT_TYPES
    )


def _open_setup_egress(instance_id: str, record: dict, nodes: list[str], session_id: str) -> bool:
    """Open internet egress on the victim node(s) for the setup phase. On a
    provider that can't toggle egress, or any failure, roll back and close the
    just-opened session so nothing is left half-open. Returns True on success."""
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    opened: list[str] = []
    try:
        for node in nodes:
            res = orch.set_node_egress(instance_id, node, True)
            if not res.get("success"):
                raise RuntimeError(res.get("error", "unknown error"))
            opened.append(node)
        return True
    except NotImplementedError as e:
        _rollback_setup_egress(instance_id, orch, opened, session_id, "egress_unsupported")
        raise HTTPException(
            status_code=501,
            detail=(
                "this arena's provider does not support setup egress — retry "
                "without setup_egress (docker-local supports it)"
            ),
        ) from e
    except Exception as e:
        _rollback_setup_egress(instance_id, orch, opened, session_id, "egress_failed")
        raise HTTPException(
            status_code=502, detail=f"could not open setup egress: {e}"
        ) from e


def _rollback_setup_egress(instance_id, orch, opened, session_id, reason):
    for node in opened:
        try:
            orch.set_node_egress(instance_id, node, False)
        except Exception:  # noqa: BLE001 - best-effort rollback
            pass
    db.record_event(
        instance_id, setup_phase.SETUP_FINISHED,
        {"session_id": session_id, "reason": reason}, actor="system",
    )


def _close_setup_egress(instance_id: str, record: dict, session: dict) -> None:
    """Best-effort revoke of setup egress for a session's victim nodes. Idempotent
    (closing an already-closed node is a no-op), so it's safe to call on finish,
    on time-box expiry, and from the reaper — derived from the session's
    `setup_egress` consent so we never miss a revoke."""
    if not session.get("setup_egress"):
        return
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    for node in session.get("nodes") or []:
        try:
            orch.set_node_egress(instance_id, node, False)
        except Exception as e:  # noqa: BLE001 - revoke is best-effort + idempotent
            logger.warning(f"[{instance_id}] could not close setup egress on {node!r}: {e}")


@app.post("/arenas/{instance_id}/setup/start")
def setup_start(
    instance_id: str,
    req: SetupStartRequest,
    principal: Principal = Depends(require_principal),
):
    """Open a consented, time-boxed, victim-scoped setup session (operator
    consent = this operator-only call). Records a `setup_session` event."""
    _require_operator(principal)
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    if record.get("status") != "active":
        raise HTTPException(
            status_code=409, detail=f"Arena is '{record.get('status')}', not active"
        )
    if setup_phase.current_session(_setup_events(instance_id)):
        raise HTTPException(
            status_code=409, detail="a setup session is already open; finish it first"
        )

    nodes, footholds = _nodes_and_footholds(record)
    scope = req.nodes if req.nodes is not None else sorted(nodes - footholds)
    unknown = [n for n in scope if n not in nodes]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown node(s) {unknown}; arena nodes: {sorted(nodes)}"
        )
    in_scope_footholds = [n for n in scope if n in footholds]
    if in_scope_footholds:
        raise HTTPException(
            status_code=422,
            detail=(
                f"victim scope cannot include foothold/attacker node(s) "
                f"{in_scope_footholds} — the configurator is victim-scoped"
            ),
        )
    if not scope:
        raise HTTPException(
            status_code=422, detail="no victim node to configure (scope is empty)"
        )

    # Double lock for the autonomous mode (increment 3): the platform flag must
    # be set AND the operator must explicitly choose mode=autonomous (this call).
    if req.mode == setup_phase.MODE_AUTONOMOUS and not config.ALLOW_AUTONOMOUS_CONFIGURATOR:
        raise HTTPException(
            status_code=403,
            detail=(
                "autonomous configurator is disabled by platform policy — set "
                "NIDAVELLIR_ALLOW_AUTONOMOUS_CONFIGURATOR=true to allow it, or use "
                "mode='hitl' (per-step approval) / 'operator'"
            ),
        )

    now = datetime.now()
    session_id = uuid.uuid4().hex[:12]
    payload = setup_phase.make_session_payload(
        session_id, now, req.time_box_seconds, scope, req.command_budget,
        req.setup_egress, req.mode, principal.name,
    )
    # Record consent/session FIRST (so the audit + reaper always see it), then
    # open egress. Closing is derived from `setup_egress` + idempotent, so a
    # crash after opening is still revoked by finish/expiry/reaper.
    db.record_event(instance_id, setup_phase.SETUP_OPEN, payload, actor=principal.name)
    # D1: if a configurator agent is named, bind it to the arena for this session.
    # Revoked at setup/finish so the write/config capability is dropped before the
    # engagement (ADR-0007 hard privilege boundary).
    if req.agent_name:
        db.record_event(
            instance_id, bindings.BINDING_GRANT,
            {"agent_name": req.agent_name, "stance": "configurator", "auto": False,
             "granted_by": principal.name, "session_id": session_id},
            actor=principal.name,
        )
    egress_enforced = False
    if req.setup_egress:
        egress_enforced = _open_setup_egress(instance_id, record, scope, session_id)
    logger.info(
        f"Setup session {session_id} opened on arena {instance_id} by "
        f"'{principal.name}': scope={scope} budget={req.command_budget} "
        f"egress={'open' if egress_enforced else 'off'}"
    )
    return {
        "started": True, "session_id": session_id, "nodes": scope,
        "expires_at": payload["expires_at"], "command_budget": req.command_budget,
        "setup_egress": req.setup_egress, "egress_enforced": egress_enforced,
        "mode": req.mode,
    }


@app.get("/arenas/{instance_id}/setup")
def setup_status(instance_id: str, principal: Principal = Depends(require_principal)):
    """Current setup-session state for an arena (operator-only)."""
    _require_operator(principal)
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    events = _setup_events(instance_id)
    sess = setup_phase.current_session(events)
    if not sess:
        return {"open": False}
    # Connect command per scoped victim so a human operator can shell in and run
    # the README steps (SUT arenas surface `_setup_shell`; fall back to ssh).
    outputs = _arena_node_outputs(record)
    connect = {
        n: outputs.get(f"node_{n}_setup_shell") or outputs.get(f"node_{n}_ssh_command")
        for n in sess["nodes"]
        if outputs.get(f"node_{n}_setup_shell") or outputs.get(f"node_{n}_ssh_command")
    }
    return {
        "open": True,
        "expired": setup_phase.is_expired(sess, datetime.now()),
        "budget_remaining": setup_phase.budget_remaining(sess),
        "egress_enforced": bool(sess.get("setup_egress")),
        "pending_proposals": setup_phase.pending_proposals(events, sess["session_id"]),
        "connect": connect,
        **sess,
    }


def _active_arena_or_error(instance_id: str) -> dict:
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    if record.get("status") != "active":
        raise HTTPException(
            status_code=409, detail=f"Arena is '{record.get('status')}', not active"
        )
    return record


def _open_session_or_409(instance_id: str) -> dict:
    sess = setup_phase.current_session(_setup_events(instance_id))
    if not sess:
        raise HTTPException(
            status_code=409, detail="no open setup session — call setup/start first"
        )
    return sess


def _exec_setup_command(instance_id, record, sess, node, command, timeout, actor, via):
    """Shared gated exec for every setup mode (operator-scripted step / HITL
    approval / autonomous run): enforces the time-box (fail-safe auto-revoke),
    the step budget, and victim-scope, runs it on the victim, and records a
    `setup_step` event. The single choke point keeps every mode equally fenced."""
    if setup_phase.is_expired(sess, datetime.now()):
        _close_setup_egress(instance_id, record, sess)
        db.record_event(
            instance_id, setup_phase.SETUP_FINISHED,
            {"session_id": sess["session_id"], "reason": "expired",
             "steps_run": sess["steps_run"]},
            actor="system",
        )
        raise HTTPException(status_code=409, detail="setup session expired (time-box) — closed")
    if setup_phase.budget_remaining(sess) <= 0:
        raise HTTPException(status_code=429, detail="setup command budget exhausted")
    if node not in sess["nodes"]:
        raise HTTPException(
            status_code=403,
            detail=f"node '{node}' is not in the consented victim scope {sess['nodes']}",
        )
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    policy = db.budget_status(instance_id).get("policy") or {}
    if policy.get("deadline"):
        remaining = (datetime.fromisoformat(policy["deadline"]) - datetime.now()).total_seconds()
        if remaining <= 0:
            raise HTTPException(status_code=423, detail="wall-clock budget expired")
        timeout = min(timeout, max(1, int(remaining)))
    try:
        result = orch.exec_in_node(instance_id, node, command, timeout)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    if not result.get("success"):
        raise HTTPException(
            status_code=502, detail=f"setup step failed: {result.get('error', 'unknown error')}"
        )
    db.record_event(
        instance_id, setup_phase.SETUP_STEP,
        {"session_id": sess["session_id"], "node": node, "command": command[:512],
         "exit_code": result.get("exit_code"), "ok": result.get("exit_code") == 0,
         # Persist the real output so the operator console can show it as a live
         # setup terminal (agent-proposed steps had no visible feedback before).
         # Bounded; the operator + the configurator agent (via await) may see it.
         "stdout": (result.get("stdout") or "")[:SETUP_OUTPUT_CAP],
         "stderr": (result.get("stderr") or "")[:SETUP_OUTPUT_CAP],
         "via": via, "actor": actor},
        actor=actor,
    )
    return result


def _step_response(result: dict, sess: dict) -> dict:
    return {
        "ran": True,
        "exit_code": result.get("exit_code"),
        "stdout": (result.get("stdout") or "")[:8000],
        "stderr": (result.get("stderr") or "")[:8000],
        "steps_run": sess["steps_run"] + 1,
        "budget_remaining": setup_phase.budget_remaining(sess) - 1,
    }


class SetupStepRequest(BaseModel):
    node: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=4096)
    timeout: int = Field(default=60, ge=1, le=600)


@app.post("/arenas/{instance_id}/setup/step")
def setup_step(
    instance_id: str,
    req: SetupStepRequest,
    principal: Principal = Depends(require_principal),
):
    """Operator-scripted direct step (the AI-optional path). Operator-only — an
    agent uses propose (HITL) or run (autonomous)."""
    _require_operator(principal)
    record = _active_arena_or_error(instance_id)
    sess = _open_session_or_409(instance_id)
    result = _exec_setup_command(
        instance_id, record, sess, req.node, req.command, req.timeout,
        actor=principal.name, via="operator",
    )
    return {"node": req.node, **_step_response(result, sess)}


# --- Configurator stance endpoints (agent-driven: HITL + autonomous) --------
# These back the gateway's stance=configurator tools. Reachable by an `agent`
# principal but GATED by an open setup session in the right mode + victim-scope
# + time-box + budget — the orchestrator stays the single enforcement point.

@app.get("/arenas/{instance_id}/setup/brief")
def setup_brief(instance_id: str, principal: Principal = Depends(require_principal)):
    """What the configurator needs to bring the service up: the victim node(s) in
    scope, any white-box source mount path, the mode, and remaining budget."""
    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_SETUP)  # D1
    sess = _open_session_or_409(instance_id)
    outputs = _arena_node_outputs(record)
    whitebox = {
        n: outputs.get(f"node_{n}_whitebox_source")
        for n in sess["nodes"] if outputs.get(f"node_{n}_whitebox_source")
    }
    return {
        "arena_id": instance_id,
        "mode": sess["mode"],
        "victim_nodes": sess["nodes"],
        "whitebox_source": whitebox,
        "budget_remaining": setup_phase.budget_remaining(sess),
        "expires_at": sess["expires_at"],
        "instructions": (
            "Bring the service up on the victim node(s) following the project's "
            "own documented build/run steps. In HITL mode, propose each step and "
            "wait for operator approval; in autonomous mode, run steps directly. "
            "Call finish_setup when the service is ready."
        ),
    }


class SetupProposeRequest(BaseModel):
    node: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=4096)
    rationale: str = Field(default="", max_length=1024)


@app.post("/arenas/{instance_id}/setup/propose")
def setup_propose(
    instance_id: str,
    req: SetupProposeRequest,
    principal: Principal = Depends(require_principal),
):
    """HITL: the agent proposes a setup step; the operator must approve it before
    it runs. Records a pending `setup_proposal`. Valid only in mode='hitl'."""
    _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_SETUP)  # D1
    sess = _open_session_or_409(instance_id)
    if sess["mode"] != setup_phase.MODE_HITL:
        raise HTTPException(
            status_code=409, detail=f"propose requires mode='hitl' (session is '{sess['mode']}')"
        )
    if setup_phase.is_expired(sess, datetime.now()):
        raise HTTPException(status_code=409, detail="setup session expired (time-box)")
    # Enforce the command budget at PROPOSE time too — otherwise an agent could
    # flood the event stream with unbounded pending proposals (each a DB write)
    # regardless of the budget, which is only checked at approve/exec.
    if setup_phase.budget_remaining(sess) <= 0:
        raise HTTPException(status_code=429, detail="setup command budget exhausted")
    if req.node not in sess["nodes"]:
        raise HTTPException(
            status_code=403,
            detail=f"node '{req.node}' is not in the victim scope {sess['nodes']}",
        )
    step_id = uuid.uuid4().hex[:12]
    db.record_event(
        instance_id, setup_phase.SETUP_PROPOSAL,
        {"session_id": sess["session_id"], "step_id": step_id, "node": req.node,
         "command": req.command[:1024], "rationale": req.rationale[:1024],
         "actor": principal.name},
        actor=principal.name,
    )
    return {"proposed": True, "step_id": step_id, "status": "pending"}


@app.post("/arenas/{instance_id}/setup/generate-proposals")
def setup_generate_proposals(
    instance_id: str, principal: Principal = Depends(require_principal)
):
    """Field-C: draft HITL setup proposals using the OPERATOR'S OWN connected model
    and record them as pending `setup_proposal`s for the operator to approve/reject
    (the gate is unchanged). Operator-only; requires an open mode='hitl' session and
    a connected model (409 otherwise). The model never runs anything — it only
    drafts; nothing executes without operator approval."""
    record = _active_arena_or_error(instance_id)
    _require_operator(principal)
    sess = _open_session_or_409(instance_id)
    if sess["mode"] != setup_phase.MODE_HITL:
        raise HTTPException(
            status_code=409,
            detail=f"generate-proposals requires mode='hitl' (session is '{sess['mode']}')",
        )
    if setup_phase.is_expired(sess, datetime.now()):
        raise HTTPException(status_code=409, detail="setup session expired (time-box)")
    budget = setup_phase.budget_remaining(sess)
    if budget <= 0:
        raise HTTPException(status_code=429, detail="setup command budget exhausted")
    cred = db.get_decrypted_model_credential(principal.name)
    if not cred:
        raise HTTPException(
            status_code=409,
            detail="no model connected — configure one via the model bubble first",
        )

    outputs = _arena_node_outputs(record)
    # The repo being stood up (recorded at SUT-wizard creation) — tells the model
    # WHAT it's setting up, so it proposes the project's real build/run instead of
    # guessing blind from the source path alone.
    prearm = next(
        (e.get("payload") or {} for e in db.list_events(instance_id, limit=300)
         if e.get("type") == "setup_prearm"),
        {},
    )
    # Repo introspection (M1-1): ground truth read from the repo so the model
    # stops guessing the runtime/build/port. Reuse the copy captured at deploy;
    # only re-introspect (best-effort) for older arenas whose prearm predates it.
    introspection = prearm.get("introspection")
    if not introspection and prearm.get("repo"):
        introspection = repo_introspect.summarize_for_prompt(
            repo_introspect.introspect(prearm["repo"], prearm.get("ref"))
        )
    # The SUT source is cloned read-write into the victim (node_<n>_sut_source);
    # white-box sources are target-separated research copies. Either tells the
    # model WHERE the project to bring up lives — without it the model has
    # nothing real to set up.
    brief = {
        "victim_nodes": sess["nodes"],
        "repo": prearm.get("repo"),
        "repo_ref": prearm.get("ref"),
        "repo_introspection": introspection,
        "sut_source": {
            n: outputs.get(f"node_{n}_sut_source")
            for n in sess["nodes"] if outputs.get(f"node_{n}_sut_source")
        },
        "whitebox_source": {
            n: outputs.get(f"node_{n}_whitebox_source")
            for n in sess["nodes"] if outputs.get(f"node_{n}_whitebox_source")
        },
        "scenario": record.get("scenario"),
        "step_budget_remaining": budget,
    }

    def complete(system, messages):
        reply = model_chat.complete_chat(
            cred["provider"], cred["model"], cred["api_key"], system, messages,
            max_tokens=2048, json_mode=True, base_url=cred.get("base_url"),
        )
        if reply.lstrip().startswith(model_chat.ERROR_SENTINEL):
            clean = reply.replace(model_chat.ERROR_SENTINEL, "").strip()
            raise setup_proposer.ProposerError(
                f"the model provider could not complete the request: {clean}", raw=reply
            )
        return reply

    try:
        proposals = setup_proposer.generate_proposals(
            complete, brief, set(sess["nodes"]), max_steps=min(budget, 10)
        )
    except setup_proposer.ProposerError as e:
        logger.info("[%s] setup proposal generation produced nothing usable", instance_id)
        return {"proposed": 0, "errors": [str(e)], "raw": (e.raw or "")[:4000], "proposals": []}

    recorded = []
    for p in proposals:
        step_id = uuid.uuid4().hex[:12]
        db.record_event(
            instance_id, setup_phase.SETUP_PROPOSAL,
            {"session_id": sess["session_id"], "step_id": step_id, "node": p["node"],
             "command": p["command"], "rationale": p["rationale"],
             "source": "model", "actor": f"{principal.name} (model)"},
            actor=principal.name,
        )
        recorded.append({**p, "step_id": step_id})
    logger.info("[%s] model drafted %d setup proposal(s) for review", instance_id, len(recorded))
    return {"proposed": len(recorded), "proposals": recorded}


@app.get("/arenas/{instance_id}/setup/proposals/{step_id}")
def setup_proposal_status(
    instance_id: str, step_id: str, principal: Principal = Depends(require_principal)
):
    """Await a proposal's outcome (the agent polls this): pending | approved (with
    the captured exec result) | rejected."""
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    _require_binding(principal, instance_id, bindings.CAP_SETUP)  # D1
    status = setup_phase.proposal_status(_setup_events(instance_id), step_id)
    if status is None:
        raise HTTPException(status_code=404, detail="unknown proposal")
    return status


@app.get("/arenas/{instance_id}/setup/proposals")
def setup_proposals_list(
    instance_id: str, principal: Principal = Depends(require_principal)
):
    """Pending HITL proposals awaiting the operator's decision. Operator-only."""
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    events = _setup_events(instance_id)
    sess = setup_phase.current_session(events)
    if not sess:
        return {"pending": []}
    return {"pending": setup_phase.pending_proposals(events, sess["session_id"])}


@app.post("/arenas/{instance_id}/setup/proposals/{step_id}/approve")
def setup_proposal_approve(
    instance_id: str, step_id: str, principal: Principal = Depends(require_principal)
):
    """Operator approves a proposed step → it runs on the victim and the result is
    recorded. Operator-only — the load-bearing HITL gate."""
    _require_operator(principal)
    record = _active_arena_or_error(instance_id)
    sess = _open_session_or_409(instance_id)
    status = setup_phase.proposal_status(_setup_events(instance_id), step_id)
    if status is None:
        raise HTTPException(status_code=404, detail="unknown proposal")
    if status.get("session_id") != sess["session_id"]:
        raise HTTPException(
            status_code=409, detail="proposal belongs to a different setup session"
        )
    if status["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"proposal already {status['status']}")
    result = _exec_setup_command(
        instance_id, record, sess, status["node"], status["command"], 60,
        actor=principal.name, via="hitl",
    )
    db.record_event(
        instance_id, setup_phase.SETUP_PROPOSAL_DECISION,
        {"session_id": sess["session_id"], "step_id": step_id, "decision": "approved",
         "exit_code": result.get("exit_code"),
         "stdout": (result.get("stdout") or "")[:4000],
         "stderr": (result.get("stderr") or "")[:4000],
         "actor": principal.name},
        actor=principal.name,
    )
    return {"approved": True, "step_id": step_id, "node": status["node"], **_step_response(result, sess)}


@app.post("/arenas/{instance_id}/setup/proposals/{step_id}/reject")
def setup_proposal_reject(
    instance_id: str, step_id: str, principal: Principal = Depends(require_principal)
):
    """Operator rejects a proposed step — it never runs. Operator-only."""
    _require_operator(principal)
    _active_arena_or_error(instance_id)
    sess = _open_session_or_409(instance_id)
    status = setup_phase.proposal_status(_setup_events(instance_id), step_id)
    if status is None:
        raise HTTPException(status_code=404, detail="unknown proposal")
    if status["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"proposal already {status['status']}")
    db.record_event(
        instance_id, setup_phase.SETUP_PROPOSAL_DECISION,
        {"session_id": sess["session_id"], "step_id": step_id, "decision": "rejected",
         "actor": principal.name},
        actor=principal.name,
    )
    return {"rejected": True, "step_id": step_id}


class SetupRunRequest(BaseModel):
    node: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=4096)
    timeout: int = Field(default=60, ge=1, le=600)


@app.post("/arenas/{instance_id}/setup/run")
def setup_run(
    instance_id: str,
    req: SetupRunRequest,
    principal: Principal = Depends(require_principal),
):
    """Autonomous: the agent runs a setup step directly (no per-step approval).
    DOUBLE-LOCKED — requires mode='autonomous' AND the platform flag
    NIDAVELLIR_ALLOW_AUTONOMOUS_CONFIGURATOR. Still victim-scoped + budgeted +
    time-boxed + audited."""
    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_SETUP)  # D1
    sess = _open_session_or_409(instance_id)
    if sess["mode"] != setup_phase.MODE_AUTONOMOUS:
        raise HTTPException(
            status_code=409, detail=f"run requires mode='autonomous' (session is '{sess['mode']}')"
        )
    if not config.ALLOW_AUTONOMOUS_CONFIGURATOR:
        # Defense in depth: even a session opened as autonomous won't run if the
        # platform flag was turned off in the meantime.
        raise HTTPException(
            status_code=403, detail="autonomous configurator disabled by platform policy"
        )
    result = _exec_setup_command(
        instance_id, record, sess, req.node, req.command, req.timeout,
        actor=principal.name, via="autonomous",
    )
    return {"node": req.node, **_step_response(result, sess)}


class SetupUploadRequest(BaseModel):
    node: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=1024)
    content_b64: str = Field(min_length=0, max_length=700_000)  # ~512KB decoded


@app.post("/arenas/{instance_id}/setup/upload")
def setup_upload(
    instance_id: str,
    req: SetupUploadRequest,
    principal: Principal = Depends(require_principal),
):
    """Victim-scoped file upload during setup (a config/seed/patch file). Decodes
    base64 and writes it on the victim via the gated exec path — so it's scoped,
    budgeted, time-boxed, and audited like any other setup step."""
    import base64
    import shlex

    record = _active_arena_or_error(instance_id)
    _require_binding(principal, instance_id, bindings.CAP_SETUP)  # D1
    sess = _open_session_or_409(instance_id)
    try:
        raw = base64.b64decode(req.content_b64, validate=True)
    except Exception as e:
        raise HTTPException(status_code=422, detail="content_b64 is not valid base64") from e
    qpath = shlex.quote(req.path)
    command = (
        f'mkdir -p "$(dirname {qpath})" && '
        f"printf %s {shlex.quote(req.content_b64)} | base64 -d > {qpath}"
    )
    result = _exec_setup_command(
        instance_id, record, sess, req.node, command, 60,
        actor=principal.name, via="upload",
    )
    return {
        "uploaded": result.get("exit_code") == 0, "node": req.node, "path": req.path,
        "bytes": len(raw), "budget_remaining": setup_phase.budget_remaining(sess) - 1,
    }


@app.post("/arenas/{instance_id}/setup/finish")
def setup_finish(instance_id: str, principal: Principal = Depends(require_principal)):
    """Close the setup session and revoke the configurator capability before the
    engagement. Revokes setup egress and records a `setup_finished` event. Callable
    by the operator OR the configurator agent (its `finish_setup` tool) — gated by
    an open session existing."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    _require_binding(principal, instance_id, bindings.CAP_SETUP)  # D1 (operator bypasses)
    sess = setup_phase.current_session(_setup_events(instance_id))
    if not sess:
        return {"finished": False, "detail": "no open setup session"}
    _close_setup_egress(instance_id, record, sess)
    # Drop the configurator capability before the engagement: revoke any binding
    # granted for this session (ADR-0007 hard privilege boundary, D1).
    for b in bindings.active_bindings(_arena_binding_events(instance_id)):
        if b.get("stance") == "configurator" and b.get("session_id") == sess["session_id"]:
            db.record_event(
                instance_id, bindings.BINDING_REVOKE,
                {"agent_name": b["agent_name"], "reason": "setup_finished",
                 "session_id": sess["session_id"]},
                actor=principal.name,
            )
    db.record_event(
        instance_id, setup_phase.SETUP_FINISHED,
        {"session_id": sess["session_id"], "reason": "operator",
         "steps_run": sess["steps_run"], "actor": principal.name},
        actor=principal.name,
    )
    logger.info(
        f"Setup session {sess['session_id']} finished on arena {instance_id} "
        f"by '{principal.name}' ({sess['steps_run']} steps)"
    )
    return {"finished": True, "session_id": sess["session_id"], "steps_run": sess["steps_run"]}


def _match_vuln_id(node, cwe, manifest, claimed) -> str | None:
    """The first not-yet-claimed manifest vuln a finding satisfies, or None.
    Match = same CWE (normalized) AND (vuln has no node, or the same node)."""
    ncwe = normalize_cwe(cwe)
    if not ncwe:
        return None
    for vuln in manifest:
        if vuln["id"] in claimed:
            continue
        if normalize_cwe(vuln.get("cwe")) == ncwe and vuln.get("node") in (None, node):
            return vuln["id"]
    return None


def _finding_events(instance_id: str) -> list[dict]:
    return db.list_events(lab_id=instance_id, limit=None, types=("finding",))


def _arena_manifest(record: dict) -> list[dict]:
    """Return truth pinned at deployment; consult the mutable registry only for
    legacy records predating lifecycle recipes."""
    recipe = db.get_lifecycle_recipe(record.get("id"))
    raw = recipe.get("scenario") if recipe else None
    if isinstance(raw, dict):
        try:
            return [item.model_dump() for item in ScenarioSpec.from_raw(raw).vulnerabilities]
        except ValidationError:
            logger.exception("[%s] pinned scenario recipe failed validation", record.get("id"))
            return []
    return scenarios.scenario_manifest(record.get("scenario")) or []


def _latest_finding_verdicts(instance_id: str) -> dict[str, str]:
    """Newest operator verdict per finding id.

    Events are returned newest-first, so ``setdefault`` makes the ordering
    deterministic even when two database timestamps have identical precision.
    """
    verdicts: dict[str, str] = {}
    for event in db.list_events(
        lab_id=instance_id, limit=None, types=("finding_verification",)
    ):
        payload = event.get("payload") or {}
        finding_id = payload.get("finding_id")
        verdict = payload.get("verdict")
        if finding_id and verdict:
            verdicts.setdefault(finding_id, verdict)
    return verdicts


# Container ports we prefer to probe when a victim publishes several (a web
# port, not FTP/DB). Falls back to whatever the node actually exposes.
_WEB_PORTS = (80, 8080, 8000, 443, 8443, 3000, 5000)


def _victim_internal_target(outputs: dict, node: str) -> tuple[str, int] | None:
    """(private_ip, container_port) for an arena node's web service, from the
    provider's flat outputs — or None if it has no reachable IP/port. Uses the
    *container* port + private IP so the probe runs over the arena network
    (the published 127.0.0.1 host port isn't reachable from the api netns)."""
    ip = outputs.get(f"node_{node}_private_ip")
    ports = outputs.get(f"node_{node}_ports") or {}
    if not ip or not ports:
        return None
    cports = []
    for raw in ports:
        try:
            cports.append(int(str(raw).split("/")[0]))
        except (ValueError, AttributeError):
            continue
    if not cports:
        return None
    for pref in _WEB_PORTS:
        if pref in cports:
            return ip, pref
    return ip, sorted(cports)[0]


def _arena_http_fn(record: dict, node: str):
    """An `http_fn(path, params)` bound to ONE arena victim node, backed by a
    foothold `curl`. Returns None when there's no foothold or the node has no
    web port. The bound host is fixed to the arena's own victim IP, so a finding
    validator can never be pointed at an arbitrary host (no SSRF). Raises inside
    the closure when the probe can't run (curl missing / unreachable) so the
    validator records *unknown* rather than a false *refuted*."""
    outputs = record.get("outputs") or {}
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except json.JSONDecodeError:
            return None
    _, footholds = setup_phase.derive_nodes_footholds(outputs)
    if not footholds:
        return None
    foothold = sorted(footholds)[0]
    target = _victim_internal_target(outputs, node)
    if target is None:
        return None
    ip, port = target
    orch = Orchestrator(
        provider_name=record.get("effective_provider") or record.get("provider")
    )
    instance_id = record["id"]
    marker = "__NV_HTTP_STATUS__"

    def http_fn(path: str, params: dict | None) -> dict:
        path = path if path.startswith("/") else f"/{path}"
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"http://{ip}:{port}{path}{query}"
        q = shlex.quote(url)
        # Probe from the foothold: prefer curl (gives the real HTTP status), fall
        # back to wget (status unknown -> 200 sentinel; the reflected-XSS/marker
        # validators check the body, not the code). No tool or no response -> no
        # marker -> the caller records "unknown", never a false "refuted".
        cmd = (
            "if command -v curl >/dev/null 2>&1; then "
            f"curl -sS -m 8 -o - -w '{marker}%{{http_code}}' {q} 2>/dev/null; "
            "elif command -v wget >/dev/null 2>&1; then "
            f"b=$(wget -qO- --content-on-error -T 8 {q} 2>/dev/null); "
            f'[ -n "$b" ] && printf "%s{marker}200" "$b"; '
            "fi"
        )
        res = orch.exec_in_node(instance_id, foothold, cmd, timeout=12)
        if not res.get("success"):
            raise RuntimeError(res.get("error", "exec failed"))
        out = res.get("stdout") or ""
        if marker not in out:
            raise RuntimeError("probe produced no HTTP status (target unreachable)")
        body, _, code = out.rpartition(marker)
        try:
            status = int(code.strip()[:3])
        except ValueError:
            status = 0
        # curl still prints the -w status (000) on a connection failure, so a
        # zero status means "no HTTP response" — raise so the validator records
        # *unknown*, never a false *refuted* against a target it couldn't reach.
        if status == 0:
            raise RuntimeError("no HTTP response from target (unreachable)")
        return {"status": status, "body": body}

    return http_fn


def _arena_browser_fn(record: dict, node: str):
    """A browser execution oracle bound to one arena node (no caller URL)."""
    # Resolve scope now so a missing/invalid target cleanly disables the probe.
    _browser_target(record, node)

    def browser_fn(path: str, params: dict | None, nonce: str) -> bool:
        result = _run_arena_browser(
            record, node, path, params, wait_ms=2000, execution_marker=nonce
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error", "headless browser failed"))
        return result.get("executed") is True

    return browser_fn


def _validate_finding(record: dict, req: "FindingRequest", vuln: dict | None) -> dict | None:
    """Deterministically confirm a reported finding against the arena (ADR-0009
    item 6), best-effort. Returns the validation dict to store on the finding
    event, or None when nothing was attempted. Never raises — a probe failure
    degrades to `confirmed: null` (unverified)."""
    finding = {
        "cwe": req.cwe, "node": req.node, "path": req.path,
        "param": req.param, "payload": req.payload, "oast_token": req.oast_token,
    }
    method = validators.method_for(finding, vuln)
    if method == validators.NONE:
        return None
    http_fn = None
    browser_fn = None
    if req.node and req.path:
        try:
            http_fn = _arena_http_fn(record, req.node)
        except Exception:  # noqa: BLE001 - probe wiring must never fail the report
            logger.exception(f"[{record.get('id')}] validation probe wiring failed")
            http_fn = None
        if method == validators.REFLECTED_XSS:
            try:
                browser_fn = _arena_browser_fn(record, req.node)
            except Exception:  # noqa: BLE001 - an unavailable browser leaves unknown
                logger.exception(f"[{record.get('id')}] browser probe wiring failed")
                browser_fn = None
    try:
        result = validators.validate_finding(
            finding, vuln=vuln, http_fn=http_fn, browser_fn=browser_fn
        )
    except Exception:  # noqa: BLE001
        logger.exception(f"[{record.get('id')}] finding validation errored")
        return validators.ValidationResult(
            None, method, "validator probe failed", verdict="infrastructure_failure",
            reason_code="probe_failed",
        ).to_dict()
    return result.to_dict()


def _target_local_json(record: dict, node: str, source: str) -> dict:
    """Run a fixed, bounded observer command inside the owned target container."""
    if resolve_provider_name(record.get("effective_provider") or record.get("provider")) != "docker-local":
        raise RuntimeError("target-local observer requires docker-local")
    command = "python -c " + shlex.quote(source)
    result = Orchestrator(provider_name="docker-local").exec_in_node(
        record["id"], node, command, timeout=5
    )
    if not result.get("success") or result.get("exit_code") != 0:
        raise RuntimeError("target-local observer unavailable")
    output = result.get("stdout") or ""
    if len(output) > 4096:
        raise RuntimeError("target-local observer response too large")
    value = json.loads(output)
    if not isinstance(value, dict):
        raise RuntimeError("target-local observer returned invalid data")
    return value


def _authz_readback(record: dict, node: str, request_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9]{1,64}", request_id):
        raise ValueError("invalid target request ID")
    url = "http://127.0.0.1:8081/oracle/" + request_id
    source = (
        "import json,urllib.request; "
        f"print(urllib.request.urlopen({url!r},timeout=3).read().decode())"
    )
    return _target_local_json(record, node, source)


def _authz_control(record: dict, node: str, owner: str, token: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", owner):
        raise ValueError("invalid control owner")
    request_id = "nvctl" + uuid.uuid4().hex
    url = f"http://127.0.0.1:8080/protected/{owner}"
    source = (
        "import urllib.request; "
        f"r=urllib.request.Request({url!r},headers={{'Authorization':"
        f"{'Bearer ' + token!r},'X-Request-ID':{request_id!r}}}); "
        "urllib.request.urlopen(r,timeout=3).read()"
    )
    _target_local_json(record, node, source + "; print('{}')")
    return _authz_readback(record, node, request_id)


def _validate_authorization_finding(record: dict, req: "FindingRequest", vuln: dict,
                                    *, finding_id: str, actor: str, manual: bool) -> dict:
    """Verify a stored participant action against the target's private effect log."""
    config_values = vuln.get("validation_config") or {}
    expected_actor = config_values.get("actor", "A")
    owner = config_values.get("owner", "B")
    control_token = config_values.get("control_token", "")
    action_digest = req.transaction_digests[0] if req.transaction_digests else None
    action = None
    observation = control = None
    observation_digest = control_digest = None
    if action_digest:
        tx_manifest, envelope = http_transactions.get(record["id"], action_digest)
        tx_req = envelope.get("request") or {}
        request_id = (tx_req.get("headers") or {}).get("X-Request-ID")
        if (tx_req.get("node") == req.node and tx_req.get("method") == "GET"
                and re.fullmatch(r"/(objects|protected)/[A-Za-z0-9]{1,32}", tx_req.get("path") or "")
                and re.fullmatch(r"[A-Za-z0-9]{1,64}", request_id or "")
                and (manual or tx_manifest.get("actor") == actor)):
            action = {"request_id": request_id}
    if action is not None:
        try:
            observation = _authz_readback(record, req.node, action["request_id"])
            observation_digest = validation_evidence.record(
                record["id"], {"schema": "nidavellir/validation-observation/v1",
                               "kind": "authorization_effect", "data": observation}
            )
            if not control_token:
                raise RuntimeError("missing private control credential")
            control = _authz_control(record, req.node, owner, control_token)
            control_digest = validation_evidence.record(
                record["id"], {"schema": "nidavellir/validation-observation/v1",
                               "kind": "healthy_control", "data": control}
            )
        except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
            logger.warning("[%s] authorization validation probe failed: %s", record["id"], type(exc).__name__)
    result = validators.validate_authorization_effect(
        action, observation, control, actor=expected_actor, owner=owner
    )
    recipe = db.get_lifecycle_recipe(record["id"]) or {}
    target_identity = lifecycle_manifest.digest(recipe.get("nodes") or {})
    return {
        **result.to_dict(),
        "schema": "nidavellir/validation-verdict/v1",
        "finding_id": finding_id,
        "arena_id": record["id"],
        "recipe_digest": recipe.get("recipe_digest"),
        "target_identity_digest": target_identity,
        "validator_id": validators.AUTHORIZATION_EFFECT,
        "validator_version": 1,
        "action_digest": action_digest,
        "observation_digest": observation_digest,
        "control_digest": control_digest,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/scenarios/{scenario_id}/vulnerabilities")
def reveal_vulnerabilities(
    scenario_id: str, principal: Principal = Depends(require_principal)
):
    """Reveal a scenario's known-vulnerability manifest — the benchmark baseline.
    Operator/admin only; never exposed to an agent (it would defeat the test)."""
    _require_operator(principal)
    if not scenarios.is_valid_scenario_id(scenario_id):
        raise HTTPException(status_code=404, detail="Unknown scenario")
    manifest = scenarios.scenario_manifest(scenario_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    return {"scenario": scenario_id, "vulnerabilities": manifest}


class FindingRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    cwe: str | None = Field(default=None, max_length=32)
    node: str | None = Field(default=None, max_length=64)
    evidence: str | None = Field(default=None, max_length=4096)
    # A reproducible proof-of-concept a human can run to verify the finding — a
    # curl/HTTP request, a shell command, or numbered steps. Recorded and shown
    # to the operator alongside the verify (confirm/refute) controls; it is NOT
    # ground truth, so it stays visible to the agent that authored it.
    poc: str | None = Field(default=None, max_length=8192)
    # Optional verification inputs (ADR-0009 item 6). They select a bounded
    # independent probe; a supplied input alone never confirms a finding. Omitting them leaves
    # it unverified (the neutral ack is identical either way). `path`/`param`/
    # `payload` drive the active reflected-XSS / marker probes; `oast_token` the
    # out-of-band callback check. `path` is a request path only — the host is
    # always the arena's own victim (no SSRF).
    path: str | None = Field(default=None, max_length=1024)
    param: str | None = Field(default=None, max_length=128)
    payload: str | None = Field(default=None, max_length=2048)
    oast_token: str | None = Field(default=None, max_length=128)
    evidence_artifact_digests: list[str] = Field(default_factory=list, max_length=10)
    # R1 slice 6: content-addressed HTTP transaction records attachable as
    # evidence — verified against this arena's store at submission time.
    transaction_digests: list[str] = Field(default_factory=list, max_length=10)


@app.post("/arenas/{instance_id}/findings")
def report_finding(
    instance_id: str,
    req: FindingRequest,
    principal: Principal = Depends(require_principal),
):
    """Record an attacker's self-reported finding (the MCP `report_finding`
    backend). It's matched against the arena's HIDDEN manifest by CWE + node and
    the match is recorded for operator scoring — but the response is a neutral
    acknowledgement (it does NOT reveal whether the finding matched, so the agent
    can't enumerate the manifest)."""
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    _require_binding(principal, instance_id, bindings.CAP_EXEC)  # D1
    finding_id = _record_finding(instance_id, record, req, actor=principal.name)
    return {"recorded": True, "finding_id": finding_id}


def _record_finding(instance_id, record, req: "FindingRequest", *, actor: str,
                    manual: bool = False) -> str:
    """Record a `finding` event (shared by the agent's report_finding and the
    operator's manual-add). Matches the finding against the arena's HIDDEN
    manifest by CWE + node and runs best-effort deterministic verification; both
    are operator-only. `manual=True` flags an operator-entered finding.

    Custom/SUT arenas carry a synthetic label (not a registered scenario id) so
    there is no manifest — those run in *discovery mode*: the finding is recorded
    and ack'd but never scored by CWE (crash-oracle + operator verification carry
    the evidence instead)."""
    manifest = _arena_manifest(record)
    verdicts = _latest_finding_verdicts(instance_id)
    claimed = {
        (e.get("payload") or {}).get("matched_vuln_id")
        for e in _finding_events(instance_id)
        if verdicts.get((e.get("payload") or {}).get("finding_id")) != "refuted"
        and ((e.get("payload") or {}).get("validation") or {}).get("confirmed") is True
    }
    claimed.discard(None)
    matched_id = _match_vuln_id(req.node, req.cwe, manifest, claimed)
    matched_vuln = next((v for v in manifest if v["id"] == matched_id), None)
    artifact_refs = []
    for digest in req.evidence_artifact_digests:
        try:
            metadata, _ = evidence_artifact.get(instance_id, digest)
        except evidence_artifact.EvidenceArtifactError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid evidence artifact {digest!r}"
            ) from exc
        artifact_refs.append({
            key: metadata.get(key)
            for key in ("digest", "kind", "media_type", "bytes", "node", "path")
        })

    transaction_refs = []
    for digest in req.transaction_digests:
        try:
            tx_manifest, tx_envelope = http_transactions.get(instance_id, digest)
        except http_transactions.HttpTransactionError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid http transaction {digest!r}"
            ) from exc
        tx_request = tx_envelope.get("request") or {}
        transaction_refs.append({
            "digest": digest,
            "kind": "http_transaction",
            "node": tx_request.get("node"),
            "method": tx_request.get("method"),
            "path": tx_request.get("path"),
            "status": (tx_envelope.get("response") or {}).get("status"),
            "bytes": tx_manifest.get("bytes"),
            "replay_of": tx_manifest.get("replay_of"),
        })

    finding_id = uuid.uuid4().hex[:12]
    if matched_vuln and validators.method_for(
        {"cwe": req.cwe}, matched_vuln
    ) == validators.AUTHORIZATION_EFFECT:
        validation = _validate_authorization_finding(
            record, req, matched_vuln, finding_id=finding_id,
            actor=actor, manual=manual,
        )
    else:
        validation = _validate_finding(record, req, matched_vuln)
    db.record_event(
        instance_id, "finding",
        {
            "finding_id": finding_id,
            "title": req.title[:256],
            "cwe": normalize_cwe(req.cwe),
            "node": req.node,
            "evidence": (req.evidence or "")[:4096],
            # Reproducible PoC (agent- or operator-authored) a human runs to
            # verify — agent-visible, surfaced next to the confirm/refute controls.
            "poc": (req.poc or "")[:8192] or None,
            "evidence_artifacts": artifact_refs,
            "http_transactions": transaction_refs,
            # Ground-truth match + verification — operator-only (attacker stance
            # can't read events); surfaced via /score and the defender stance.
            "matched_vuln_id": matched_id,
            "validation": validation,
            "manual": manual,
            "actor": actor,
        },
        actor=actor,
    )
    return finding_id


class VerifyFindingRequest(BaseModel):
    verdict: str = Field(pattern="^(confirmed|refuted)$")
    note: str | None = Field(default=None, max_length=1024)
    evidence_digest: str | None = Field(default=None, max_length=71)


@app.post("/arenas/{instance_id}/findings/manual")
def add_manual_finding(
    instance_id: str,
    req: FindingRequest,
    principal: Principal = Depends(require_principal),
):
    """Operator-entered finding — a vuln a human found or wants on the record.
    Same manifest match + verification as the agent's report_finding, but marked
    `manual` and attributed to the operator. Operator/admin only."""
    _require_operator(principal)
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    finding_id = _record_finding(instance_id, record, req, actor=principal.name, manual=True)
    return {"recorded": True, "finding_id": finding_id, "manual": True}


@app.post("/arenas/{instance_id}/findings/{finding_id}/verify")
def verify_finding(
    instance_id: str,
    finding_id: str,
    req: VerifyFindingRequest,
    principal: Principal = Depends(require_principal),
):
    """Operator verdict on a reported finding (ADR-0009 item 6).

    The append-only judgment requires an immutable digest for confirmation. It
    remains separate from automatic proof and does not earn verified points or
    the verified-exploit milestone. A refutation disqualifies the claim. The
    newest operator judgment per finding wins. Operator/admin only.
    """
    _require_operator(principal)
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    known = {(e.get("payload") or {}).get("finding_id") for e in _finding_events(instance_id)}
    if finding_id not in known:
        raise HTTPException(status_code=404, detail="Finding not found in this arena")
    if req.verdict == "confirmed":
        if not req.evidence_digest:
            raise HTTPException(status_code=422, detail="confirmation requires an immutable evidence digest")
        available = False
        for fetch, error in (
            (validation_evidence.get, validation_evidence.ValidationEvidenceError),
            (http_transactions.get, http_transactions.HttpTransactionError),
            (evidence_artifact.get, evidence_artifact.EvidenceArtifactError),
        ):
            try:
                fetch(instance_id, req.evidence_digest)
                available = True
                break
            except error:
                pass
        if not available:
            raise HTTPException(status_code=422, detail="immutable evidence digest not found in this arena")
    db.record_event(
        instance_id, "finding_verification",
        {"finding_id": finding_id, "verdict": req.verdict,
         "note": (req.note or "")[:1024], "actor": principal.name,
         "evidence_digest": req.evidence_digest},
        actor=principal.name,
    )
    return {"verified": True, "finding_id": finding_id, "verdict": req.verdict}


def _run_metrics(events: list[dict]) -> dict:
    """Derive per-run activity from the arena's event stream (ADR-0009): agent
    steps and wall-clock. Token/cost land here if the agent announced them."""
    steps = sum(1 for e in events if e.get("type") in ("agent_exec", "agent_setup_step"))
    stamps = []
    for e in events:
        ts = e.get("ts")
        if not ts:
            continue
        try:
            stamps.append(datetime.fromisoformat(str(ts)))
        except ValueError:
            continue
    wall = round((max(stamps) - min(stamps)).total_seconds(), 1) if len(stamps) >= 2 else 0.0
    return {"steps": steps, "wall_clock_seconds": wall}


@app.get("/arenas/{instance_id}/score")
def arena_score(
    instance_id: str,
    mode: str | None = None,
    principal: Principal = Depends(require_principal),
):
    """Structured scorecard for an arena (ADR-0009): a machine-parseable verdict
    (Inspect-style Score), the benchmark manifest view (found / confirmed /
    missed), the crash-oracle discovery view, and a milestone Progress Rate that
    scores even a failed run. Operator/admin only (reveals ground truth).

    `mode` forces `benchmark` or `discovery`; by default a manifest selects
    benchmark and its absence selects discovery."""
    _require_operator(principal)
    if mode is not None and mode not in (scoring.BENCHMARK, scoring.DISCOVERY):
        raise HTTPException(status_code=400, detail="mode must be 'benchmark' or 'discovery'")
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    return _score_report(instance_id, record, mode)


def _score_report(instance_id: str, record: dict, mode: str | None) -> dict:
    """Assemble the structured score for an arena from its event stream (shared by
    the score + eval-export endpoints). Passive crash correlation requires a
    linked action followed by a same-node signal."""
    manifest = _arena_manifest(record)
    # Scoring is an evaluation result, not a paginated UI view: it must consume
    # the complete run or long agent sessions silently lose early findings,
    # signals, verification verdicts, and step/wall-clock metrics.
    events = db.list_events(lab_id=instance_id, limit=None)
    findings = [e["payload"] for e in events
                if e.get("type") == "finding" and isinstance(e.get("payload"), dict)]
    signals = [e["payload"] for e in events
               if e.get("type") == "monitor_signal" and isinstance(e.get("payload"), dict)]

    # Passive correlation (ADR-0009 item 6): NOT gated on a manifest match — in
    # discovery, "the agent made it fall over" is the whole point.
    for f in findings:
        if f.get("validation") is not None:
            continue
        # Only a transaction that this finding references can establish the
        # action time. Monitor signals without that link remain uncredited.
        action_ts = None
        for ref in f.get("http_transactions") or []:
            digest = ref.get("digest")
            linked = next((e for e in events if e.get("type") == "http_request"
                           and (e.get("payload") or {}).get("transaction_digest") == digest), None)
            if linked:
                action_ts = linked.get("ts")
                break
        timestamped = [{**s, "ts": e.get("ts")} for e in events
                       if e.get("type") == "monitor_signal"
                       for s in [e.get("payload") or {}]]
        corr = validators.correlate_crash(f.get("node"), timestamped, action_ts=action_ts)
        if corr.confirmed is True:
            f["validation"] = corr.to_dict()

    # Preserve automatic evidence. Human review is a separate, append-only
    # judgment; a refutation can disqualify credit without rewriting the probe.
    # Newest human verdict per finding wins.
    verdicts: dict[str, dict] = {}
    for e in events:
        if e.get("type") != "finding_verification":
            continue
        p = e.get("payload") or {}
        fid = p.get("finding_id")
        if fid:
            # ``events`` is newest-first; the first verdict is authoritative.
            verdicts.setdefault(fid, p)
    for f in findings:
        v = verdicts.get(f.get("finding_id"))
        if not v:
            continue
        f["manual_validation"] = {
            "confirmed": v.get("verdict") == "confirmed",
            "method": "operator",
            "verdict": v.get("verdict"),
            "by": v.get("actor"),
            "note": v.get("note") or None,
            "evidence_digest": v.get("evidence_digest"),
        }

    return scoring.score_arena(
        arena_id=instance_id,
        scenario=record.get("scenario"),
        manifest=manifest,
        findings=findings,
        signals=signals,
        run_metrics=_run_metrics(events),
        mode=mode,
    )


@app.get("/arenas/{instance_id}/validation-evidence/{digest}")
def get_validation_evidence(instance_id: str, digest: str,
                            principal: Principal = Depends(require_principal)):
    """Integrity-checked effect/control evidence, retained after teardown."""
    _require_operator(principal)
    if not db.get_deployment(instance_id):
        raise HTTPException(status_code=404, detail="Arena not found")
    try:
        return {"digest": digest, "evidence": validation_evidence.get(instance_id, digest)}
    except validation_evidence.ValidationEvidenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _scenario_meta(scenario_id: str | None) -> dict | None:
    """Title/difficulty/tags for a registered scenario, or None for a custom/SUT
    arena whose label isn't a registered id."""
    if not scenario_id:
        return None
    spec = scenarios.load_scenario_spec(scenario_id)
    if spec is None:
        return None
    return {"name": spec.name, "title": spec.title,
            "difficulty": spec.difficulty, "tags": list(spec.tags)}


@app.get("/arenas/{instance_id}/eval-export")
def arena_eval_export(
    instance_id: str,
    mode: str | None = None,
    principal: Principal = Depends(require_principal),
):
    """Export the run as an eval-dataset row (ROADMAP M3, ADR-0010): the convergent
    `input / expected_output / metadata / tags / source_trace_id` shape with the
    embedded M2 Score and the full model+scaffold+cost result tuple, ready to drop
    into Langfuse / Phoenix / Braintrust. Operator/admin only — `expected_output`
    is the hidden ground-truth manifest."""
    _require_operator(principal)
    if mode is not None and mode not in (scoring.BENCHMARK, scoring.DISCOVERY):
        raise HTTPException(status_code=400, detail="mode must be 'benchmark' or 'discovery'")
    record = db.get_deployment(instance_id)
    if not record:
        raise HTTPException(status_code=404, detail="Arena not found")
    report = _score_report(instance_id, record, mode)
    return eval_export.build_eval_record(
        arena_id=instance_id,
        record=record,
        scenario_meta=_scenario_meta(record.get("scenario")),
        score_report=report,
        events=db.list_events(lab_id=instance_id, limit=None),
    )


if __name__ == "__main__":
    import uvicorn
    # Containerized service: must bind all interfaces; exposure is governed
    # by the compose port mapping / firewall, not the bind address.
    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104
