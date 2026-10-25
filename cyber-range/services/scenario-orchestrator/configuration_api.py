"""Operator-owned configuration lineage REST adapter.

The supplied host owns authorization, providers and independent finding review.
All fact semantics and redaction live in the lineage and capture modules.
"""
from __future__ import annotations

from typing import Literal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth import Principal, require_principal
import bindings
import configuration_capture as capture
import configuration_lineage as lineage
import crypto
import evidence_review
import http_transactions
import research_code
from lifecycle_manifest import digest


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["deployment", "runtime", "post_setup"] = "deployment"


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str = Field(pattern=r"^[0-9a-f]{12}$")
    after: str = Field(pattern=r"^[0-9a-f]{12}$")


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_arena_id: str = Field(min_length=1, max_length=128)
    snapshot_ids: list[str] = Field(min_length=2, max_length=32)
    research_key: str = Field(min_length=1, max_length=128)
    publish_to: list[str] = Field(default_factory=list, max_length=16)


class HistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refs: list[str] = Field(min_length=1, max_length=32)


def capture_and_save(host, arena_id, recipe, stage="deployment"):
    """Capture only trusted profile facts; fail closed before writing any record."""
    if not recipe or not recipe.get("configuration_profile"):
        return None
    if not crypto.encryption_enabled():
        raise lineage.ConfigurationLineageError("record encryption is required for configuration snapshots")
    if stage == "deployment":
        snapshot = capture.deployment_snapshot(arena_id, recipe)
    else:
        record = host.db.get_deployment(arena_id)
        if record.get("status") != "active":
            raise lineage.ConfigurationLineageError("runtime capture requires an active arena")
        profile = recipe["configuration_profile"]
        selectors = capture.runtime_selectors(profile)
        provider = host.get_provider(recipe["effective_provider"])
        observation = provider.observe_configuration(arena_id, selectors)
        snapshot = capture.runtime_snapshot(arena_id, recipe, observation, stage=stage,
                                            setup_events=host._setup_events(arena_id))
    return host.db.save_configuration_snapshot(snapshot)


def _observations(host, snapshots, research_key):
    """Resolve immutable validation chains and matching probe inputs server-side."""
    observations = []
    for snapshot in snapshots:
        arena = snapshot["arena_id"]
        recipe = host.db.get_lifecycle_recipe(arena) or {}
        for event in host.db.list_events(arena, limit=None, types=("finding",)):
            finding = event.get("payload") or {}
            if (finding.get("research_key") or finding.get("finding_id")) != research_key:
                continue
            validation = finding.get("validation") or {}
            review = evidence_review.build(arena, finding)
            healthy = review.get("can_refute") is True
            # Bind the observation to the recipe, snapshot time and immutable action.
            # Runtime capture is a starting-state capture, before the probe.
            action_digest = validation.get("action_digest")
            probe_digest = None
            try:
                transaction_meta, transaction = http_transactions.get(arena, action_digest)
                request = transaction.get("request") or {}
                headers = {key: value for key, value in (request.get("headers") or {}).items()
                           if not (validation.get("validator_id") == "authorization_effect"
                                   and key.lower() == "x-request-id")}
                probe_digest = digest({key: request.get(key) for key in (
                    "node", "method", "path", "params", "body")} | {"headers": headers})
            except (http_transactions.HttpTransactionError, TypeError):
                healthy = False
            if validation.get("recipe_digest") != recipe.get("recipe_digest"):
                healthy = False
            snapshot_time = snapshot.get("captured_at", "")
            if snapshot["stage"] not in {"deployment", "runtime", "post_setup"}:
                healthy = False
            # A historical snapshot cannot be attached to an unrelated runtime action.
            try:
                captured = datetime.fromisoformat(snapshot_time).replace(tzinfo=timezone.utc)
                acted = datetime.fromisoformat(transaction_meta["created_at"]).replace(tzinfo=timezone.utc)
                if captured > acted:
                    healthy = False
            except (ValueError, KeyError, UnboundLocalError):
                healthy = False
            runtime_facts = [fact for fact in snapshot["facts"] if fact["source_class"] == "runtime"]
            runtime_verified = snapshot["stage"] == "runtime" and bool(runtime_facts) and all(
                fact.get("source_ref", {}).get("pristine") is True
                for fact in runtime_facts)
            if runtime_verified and (host.db.get_deployment(arena) or {}).get("status") == "active":
                try:
                    profile = recipe["configuration_profile"]
                    selectors = capture.runtime_selectors(profile)
                    observed = host.get_provider(recipe["effective_provider"]).observe_configuration(arena, selectors)
                    current = capture.runtime_snapshot(arena, recipe, observed, setup_events=host._setup_events(arena))
                    runtime_verified = current["snapshot_digest"] == snapshot["snapshot_digest"]
                except (ValueError, RuntimeError, NotImplementedError):
                    runtime_verified = False
            else:
                runtime_verified = False
            observations.append({"snapshot_id": snapshot["snapshot_id"],
                "verdict": review.get("verdict", "inconclusive"), "controls_healthy": healthy,
                "validator_id": validation.get("validator_id"),
                "validator_version": validation.get("validator_version"),
                "probe_digest": probe_digest,
                "control_plan_digest": digest(validation.get("review_context") or {}),
                "replay_verified": healthy and runtime_verified and bool(
                    (host.db.get_reset_operation_by_replacement(arena) or {}).get("status") == "succeeded"),
                "evidence_digests": [value for value in (
                    action_digest, validation.get("observation_digest"), validation.get("control_digest")) if value]})
            break
    for index, snapshot in enumerate(snapshots[1:], 1):
        observation = next((item for item in observations if item["snapshot_id"] == snapshot["snapshot_id"]), None)
        if observation is not None:
            observation["controlled_transition"] = capture.controlled_transition(
                host.db.get_lifecycle_recipe(snapshots[index - 1]["arena_id"]),
                host.db.get_lifecycle_recipe(snapshot["arena_id"]))
    return observations


def install(app, host):
    router = APIRouter()

    def arena_record(arena):
        record = host.db.get_deployment(arena)
        if record is None:
            raise HTTPException(404, "Arena not found")
        return record

    def load(snapshot_id):
        snapshot = host.db.get_configuration_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "Configuration snapshot not found")
        return snapshot

    def find_analysis(analysis_id, arena=None):
        events = host.db.list_events(arena, limit=None, types=("configuration_introduction",))
        for event in events:
            payload = event.get("payload") or {}
            if payload.get("analysis_id") == analysis_id:
                return payload
        raise HTTPException(404, "Configuration analysis not found")

    @router.post("/arenas/{arena}/configuration-snapshots", status_code=201)
    def create_snapshot(arena: str, req: SnapshotRequest,
                        principal: Principal = Depends(require_principal)):
        host._require_operator(principal)
        arena_record(arena)
        try:
            snapshot = capture_and_save(host, arena, host.db.get_lifecycle_recipe(arena), req.stage)
            if snapshot is None:
                raise lineage.ConfigurationLineageError("arena has no reviewed configuration profile")
            return {"snapshot": lineage.public_snapshot(snapshot)}
        except NotImplementedError as exc:
            raise HTTPException(422, "provider does not support runtime configuration capture") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/arenas/{arena}/configuration-snapshots")
    def list_snapshots(arena: str, limit: int = Query(100, ge=1, le=100), before: str | None = None,
                       principal: Principal = Depends(require_principal)):
        host._require_operator(principal)
        arena_record(arena)
        try:
            snapshots = host.db.list_configuration_snapshots(arena, limit=limit, before=before)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"snapshots": [lineage.public_snapshot(item) for item in snapshots],
                "next_before": snapshots[-1]["snapshot_id"] if len(snapshots) == limit else None}

    @router.get("/arenas/{arena}/configuration-snapshots/{snapshot_id}")
    def read_snapshot(arena: str, snapshot_id: str,
                      principal: Principal = Depends(require_principal)):
        host._require_operator(principal)
        snapshot = load(snapshot_id)
        if snapshot["arena_id"] != arena:
            raise HTTPException(404, "Configuration snapshot not found")
        return lineage.public_snapshot(snapshot)

    @router.post("/configuration-lineage/compare")
    def compare(req: CompareRequest, principal: Principal = Depends(require_principal)):
        host._require_operator(principal)
        try:
            return lineage.compare_snapshots(load(req.before), load(req.after))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/arenas/{arena}/configuration-history", status_code=201)
    def history(arena: str, req: HistoryRequest, principal: Principal = Depends(require_principal)):
        host._require_operator(principal)
        arena_record(arena)
        recipe = host.db.get_lifecycle_recipe(arena) or {}
        profile = recipe.get("configuration_profile")
        if not profile:
            raise HTTPException(422, "arena has no reviewed configuration profile")
        try:
            result = research_code.configuration_history(research_code.repo_root(), req.refs, profile)
            identity = capture.target_identity(recipe)
            snapshots = []
            for state in result["states"]:
                snapshot = lineage.capture_snapshot(arena_id=arena,
                    target_identity={"kind": "git", "digest": state["ref"],
                                     "parent_digest": state["parent_digest"],
                                     "adjacent_to_previous": state["adjacent_to_previous"],
                                     "lineage": identity["lineage"]},
                    profile=profile, facts=state["facts"], stage="historical_candidate",
                    lineage_id=identity["lineage"])
                snapshots.append(host.db.save_configuration_snapshot(snapshot))
            return {"snapshots": [lineage.public_snapshot(item) for item in snapshots],
                    "counts_complete": result["counts_complete"]}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/configuration-lineage/analyze", status_code=201)
    def analyze(req: AnalyzeRequest, principal: Principal = Depends(require_principal)):
        host._require_operator(principal)
        arena_record(req.subject_arena_id)
        snapshots = [load(item) for item in req.snapshot_ids]
        if snapshots[-1]["arena_id"] != req.subject_arena_id:
            raise HTTPException(422, "subject arena must own the final snapshot")
        if req.publish_to:
            intent = host.db.list_events(req.subject_arena_id, limit=1, types=("engagement_intent",))
            if not intent or intent[0]["payload"].get("purpose") not in {"research", "discovery"}:
                raise HTTPException(422, "agent publication requires a discovery or research engagement")
        try:
            analysis = lineage.analyze_history(snapshots=snapshots,
                observations=_observations(host, snapshots, req.research_key), research_key=req.research_key)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        analysis = {**analysis, "subject_arena_id": req.subject_arena_id,
                    "publish_to": sorted(set(req.publish_to))}
        host.db.record_event(req.subject_arena_id, "configuration_introduction", analysis, actor=principal.name)
        return analysis

    @router.get("/configuration-lineage/analyses/{analysis_id}")
    def read_analysis(analysis_id: str, principal: Principal = Depends(require_principal)):
        host._require_operator(principal)
        return find_analysis(analysis_id)

    @router.get("/arenas/{arena}/configuration-lineage/{analysis_id}")
    def agent_analysis(arena: str, analysis_id: str,
                       principal: Principal = Depends(require_principal)):
        arena_record(arena)
        host._require_binding(principal, arena, bindings.CAP_WORKSPACE)
        analysis = find_analysis(analysis_id, arena)
        if principal.role not in host.OPERATOR_ROLES and principal.name not in analysis["publish_to"]:
            raise HTTPException(403, "analysis has not been published to this agent")
        # Explicit publication is restricted to research; private validator evidence
        # and raw facts never travel through this projection.
        projection = {key: analysis.get(key) for key in (
            "schema", "analysis_id", "analysis_digest", "subject_arena_id", "candidate_keys",
            "confidence", "missing_evidence", "introduction_scope")}
        ordered = analysis["ordered_snapshot_ids"]
        before = load(analysis.get("predecessor") or ordered[-2])
        after = load(analysis.get("earliest_known_vulnerable") or ordered[-1])
        delta = lineage.compare_snapshots(before, after)
        for change in delta["changes"]:
            for side in ("before", "after"):
                value = change.get(side)
                if value is None:
                    continue
                change[side] = {key: value.get(key) for key in (
                    "key", "value_state", "source_class", "security_tags", "complete")}
                if value.get("value_state") == "plain":
                    change[side]["value"] = value.get("value")
                change[side]["source_ref"] = {key: item for key, item in value.get("source_ref", {}).items()
                    if key in {"kind", "node", "path", "ref", "selector", "image"}}
        projection["delta"] = delta
        projection["completeness"] = {"status": "complete" if delta["complete"] else "partial",
            "scope": "reviewed_profile", "before": before["completeness"], "after": after["completeness"]}
        return projection

    app.include_router(router)
