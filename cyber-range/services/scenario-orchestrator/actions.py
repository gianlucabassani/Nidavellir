"""The single action boundary (OBS-02, review item FR-11).

A target-affecting route declares itself with ``@action(name, ...)`` directly
under its ``@app.post``. The HTTP middleware matches each request against the
app's routes, and for a declared action calls :func:`run`, which does in order:

    policy → stop gate + budget reservation → span → execute → settle → span

Budget and tracing therefore follow the declaration, not a remembered path
suffix. Contracts are unchanged from the previous path-matching middleware
(NV-04): the same routes reserve, a refused reservation answers 429 (budget
exhausted) or 423 (stopped), ``X-Action-Key`` keeps idempotency, ``X-Action-ID``
is returned, and the outcome settles from the response status (<400 spent,
<500 released, otherwise unknown). Routes keep writing their own audit events.
Every call by an authenticated principal produces exactly one span, including
refusals.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

import bindings
import spans

ACTION_ATTR = "__nv_action__"
_ACTION_KEY = re.compile(r"[A-Za-z0-9._:-]{8,128}")
_CAP_HEADERS = ("X-Token-Budget", "X-Cost-Budget")


@dataclass(frozen=True)
class ActionSpec:
    name: str
    capability: str = bindings.CAP_EXEC
    # Agents may never perform it (the route answers 403); no reservation for them.
    operator_only: bool = False
    budgeted: bool = True


def action(name: str, *, capability: str = bindings.CAP_EXEC,
           operator_only: bool = False, budgeted: bool = True):
    """Declare a route as a budgeted, traced arena action."""
    spec = ActionSpec(name, capability, operator_only, budgeted)

    def mark(fn):
        setattr(fn, ACTION_ATTR, spec)
        return fn
    return mark


def declared(app) -> list[tuple[str, str, ActionSpec]]:
    """(method, path template, spec) for every declared action route."""
    out = []
    for route in app.routes:
        spec = getattr(getattr(route, "endpoint", None), ACTION_ATTR, None)
        if spec is not None:
            for method in sorted(getattr(route, "methods", ()) or ()):
                out.append((method, route.path, spec))
    return out


def match(app, scope) -> tuple[ActionSpec, dict] | None:
    """The declared action a request targets, with its path parameters."""
    for route in app.routes:
        spec = getattr(getattr(route, "endpoint", None), ACTION_ATTR, None)
        if spec is None:
            continue
        result, child = route.matches(scope)
        if result == Match.FULL:
            return spec, child.get("path_params", {})
    return None


def _json_or_text(body: bytes):
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace")


def _span_status(code: int, refused: bool) -> str:
    if refused:
        return "budget_refused"
    if code < 400:
        return "ok"
    if code in (401, 403):
        return "denied"
    if code == 423:
        return "denied"  # paused binding or stopped arena answered by the route
    return "error"


def _json(code: int, detail: str) -> Response:
    return Response(content=json.dumps({"detail": detail}), status_code=code,
                    media_type="application/json")


async def run(request: Request, call_next: Callable[[Request], Awaitable[Response]], *,
              spec: ActionSpec, arena_id: str, db,
              authorize: Callable[[str, str, str], dict | None]) -> Response:
    """Run one declared action through policy, budget, span and settlement.

    ``authorize(agent_name, arena_id, capability)`` raises for an agent without a
    usable binding and returns the binding otherwise (FR-04).
    """
    from auth import hash_api_key  # local: auth imports the database at import time

    key = request.headers.get("X-API-Key")
    principal = db.get_api_key(hash_api_key(key)) if key else None
    if principal is None:  # authentication errors stay with the route dependency
        return await call_next(request)
    started = datetime.now(timezone.utc)
    body = await request.body()
    kind = request.url.path.partition(f"/arenas/{arena_id}/")[2]
    actor, role = principal["name"], principal["role"]
    stance = None
    reserve = spec.budgeted
    refused = False
    action_id = None

    arena = db.get_deployment(arena_id)
    if arena is None or arena.get("status") != "active":
        # The route answers 404/409; the reservation gate repeats this check
        # transactionally for an arena that changes state.
        reserve = False
    elif role == "agent":
        if spec.operator_only:
            reserve = False
        else:
            try:
                binding = authorize(actor, arena_id, spec.capability)
                stance = (binding or {}).get("stance")
            except Exception:  # noqa: BLE001 - the route answers the 403/423
                reserve = False

    if reserve and any(request.headers.get(h) for h in _CAP_HEADERS):
        response = _json(422, "token/cost caps cannot be enforced for this driver")
    elif reserve:
        action_key = request.headers.get("X-Action-Key") or str(uuid.uuid4())
        if not _ACTION_KEY.fullmatch(action_key):
            response = _json(422, "invalid X-Action-Key")
        else:
            digest = hashlib.sha256(request.method.encode() + request.url.path.encode()
                                    + body).hexdigest()
            try:
                action_id, deadline = db.reserve_budget_action(
                    arena_id, key=action_key, digest=digest, kind=kind, actor=actor)
            except ValueError as exc:
                detail = str(exc)
                refused = True
                response = _json(429 if "budget exhausted" in detail else 423, detail)
            else:
                request.state.budget_deadline = deadline
                response = await _execute(request, call_next, db, action_id)
    else:
        response = await call_next(request)

    response, output = await _buffer(response)
    if action_id is not None:
        response.headers["X-Action-ID"] = action_id
    spans.record(
        db, name=spec.name, kind="tool", actor=actor,
        actor_kind="agent" if role == "agent" else "human", stance=stance,
        arena_id=arena_id, started_at=started, ended_at=datetime.now(timezone.utc),
        status=_span_status(response.status_code, refused),
        error_class=None if response.status_code < 400 else f"http_{response.status_code}",
        input=_json_or_text(body), output=_json_or_text(output),
        attrs={"http.method": request.method, "http.route": kind,
               "http.status_code": response.status_code,
               "nv.budget_action_id": action_id, "nv.budgeted": action_id is not None,
               "openinference.span.kind": "TOOL", "gen_ai.operation.name": "execute_tool",
               "tool.name": spec.name},
    )
    return response


async def _execute(request, call_next, db, action_id) -> Response:
    try:
        response = await call_next(request)
    except Exception:
        db.settle_budget_action(action_id, outcome="unknown")
        raise
    code = response.status_code
    db.settle_budget_action(action_id, outcome=("spent" if code < 400 else
                                                "released" if code < 500 else "unknown"))
    return response


async def _buffer(response: Response) -> tuple[Response, bytes]:
    """Read a (streaming) response once so the span can digest it, and return
    an equivalent response carrying the same bytes, status and headers."""
    iterator = getattr(response, "body_iterator", None)
    if iterator is None:
        return response, bytes(getattr(response, "body", b"") or b"")
    chunks = [chunk if isinstance(chunk, bytes) else chunk.encode() async for chunk in iterator]
    body = b"".join(chunks)
    buffered = Response(content=body, status_code=response.status_code,
                        headers=dict(response.headers), media_type=response.media_type,
                        background=response.background)
    return buffered, body
