"""Read-only operator review of the immutable action/control/effect chain.

Unknown schemas and missing observations remain unresolved. This projection never
executes probes, changes historical verdicts, or grants scoring credit.
"""
from __future__ import annotations

import http_transactions
import validation_evidence

SUPPORTED = {"authorization_effect", "single_use_grant_effect", "http_access_control"}


def _observation(arena: str, digest: str | None, kind: str) -> dict | None:
    if not digest:
        return None
    try:
        item = validation_evidence.get(arena, digest)
    except validation_evidence.ValidationEvidenceError:
        return None
    if (item.get("schema") != "nidavellir/validation-observation/v1"
            or item.get("kind") != kind or not isinstance(item.get("data"), dict)):
        return None
    return item["data"]


def _control(name: str, observed: dict | None, expected: dict, request: dict | None = None) -> dict:
    state = "unresolved"
    if observed is not None and expected and all(value is not None for value in expected.values()):
        # Strict types matter: 1 is not evidence of a boolean assertion.
        state = "passed" if all(type(observed.get(key)) is type(value)
                                and observed.get(key) == value
                                for key, value in expected.items()) else "failed"
    return {"name": name, "state": state, "expected": expected,
            "observed": {key: observed.get(key) for key in expected} if observed is not None else None,
            "request": request}


def build(arena: str, finding: dict) -> dict:
    validation = finding.get("validation") or {}
    method = validation.get("validator_id")
    supported = method in SUPPORTED and validation.get("validator_version") == 1
    context = validation.get("review_context") or {}
    unresolved = []
    actor = None
    action_digest = validation.get("action_digest")
    if action_digest:
        try:
            _, envelope = http_transactions.get(arena, action_digest)
            req = envelope.get("request") or {}
            resp = envelope.get("response") or {}
            actor = {
                "identity": context.get("actor"), "digest": action_digest,
                "request": {key: req.get(key) for key in ("node", "method", "path", "params", "body")},
                "response": {key: resp.get(key) for key in (
                    "status", "reason", "body", "body_bytes", "body_sha256", "truncated")},
                "headers_withheld": True,
            }
        except http_transactions.HttpTransactionError:
            pass
    if actor is None:
        unresolved.append("Linked actor request/response is missing or failed its integrity check.")
    effect = _observation(arena, validation.get("observation_digest"), method) if supported else None
    control = _observation(arena, validation.get("control_digest"), "healthy_control") if supported else None
    controls = []
    if supported and method == "authorization_effect":
        owner = context.get("owner")
        controls.append(_control("Owner can read its own object", control,
                                 {"actor": owner, "owner": owner, "status": 200, "control_ok": True},
                                 {"actor": owner, "method": "GET", "path": f"/protected/{owner}"}
                                 if owner else None))
    elif supported and method == "single_use_grant_effect":
        controls.append(_control("First redemption credits once", control,
                                 {"actor": context.get("actor"), "status": 200,
                                  "prior_redemptions": 0, "after_redemptions": 1, "control_ok": True}))
    elif supported and method == "http_access_control":
        controls.append(_control("Owner observes the protected marker", (control or {}).get("owner"),
                                 {"status": context.get("disclosure_status"), "marker": True},
                                 context.get("owner_request")))
        controls.append(_control("Actor's allowed request succeeds without the protected marker",
                                 (control or {}).get("control"), {"status": 200, "marker": False},
                                 context.get("control_request")))
    else:
        controls.append(_control("Prerequisite controls", None, {}))
        unresolved.append("This validator version has no structured control review adapter.")
    if not context:
        unresolved.append("Actor identities and expected conditions were not retained in this historical record.")
    if effect is None:
        unresolved.append("Effect observation is missing, unreadable or unsupported.")
    if any(item["state"] == "unresolved" for item in controls):
        unresolved.append("Prerequisite evidence is unresolved; it cannot support a refutation.")
    if any(item["state"] == "failed" for item in controls):
        unresolved.append("A prerequisite failed; the result cannot be presented as a refutation.")
    verdict = validation.get("verdict") or "inconclusive"
    can_refute = supported and actor is not None and effect is not None and all(
        item["state"] == "passed" for item in controls)
    if verdict == "refuted" and not can_refute:
        verdict = "inconclusive"
    # Confirmation is also unresolved when its immutable evidence chain is unavailable.
    if verdict == "confirmed" and not can_refute:
        verdict = "inconclusive"
    effect_fields = ("request_id", "actor", "owner", "grant", "status", "unauthorized_disclosure",
                     "duplicate_credited", "prior_redemptions", "after_redemptions", "marker")
    return {
        "schema": "nidavellir/evidence-review/v1", "finding_id": finding.get("finding_id"),
        "verdict": verdict, "recorded_verdict": validation.get("verdict"),
        "reason_code": validation.get("reason_code"), "validator_id": method,
        "validator_version": validation.get("validator_version"),
        "recipe_digest": validation.get("recipe_digest"),
        "target_identity_digest": validation.get("target_identity_digest"),
        "actor": actor, "controls": controls, "can_refute": can_refute,
        "refutation_allowed": method not in SUPPORTED or can_refute,
        "control_digest": validation.get("control_digest"),
        "effect": {"digest": validation.get("observation_digest"),
                   "data": {key: effect[key] for key in effect_fields if key in effect}} if effect is not None else None,
        "unresolved": unresolved,
    }
