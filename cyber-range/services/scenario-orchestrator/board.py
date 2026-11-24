"""OBS-06: the cross-arena "what are my agents doing" board.

One operator snapshot: every live arena with its agents, last action, recent
error rate, budget and trial, plus an attention inbox of things that need a
human (failed arenas, verdicts, budget exhaustion, stops, finished trials).
Idle detection is left to the client clock: each arena carries the time of its
last action and the threshold, so no update is needed just because time passed.
"""
from __future__ import annotations

import os

import bindings
from states import LabStatus

IDLE_MINUTES = int(os.getenv("NIDAVELLIR_BOARD_IDLE_MINUTES", "10"))
RECENT_SPANS = 50
INBOX_LIMIT = 40
_LIVE = {LabStatus.PENDING, LabStatus.DEPLOYING, LabStatus.ACTIVE, LabStatus.ERROR_DESTROYING}
_FAILED = {LabStatus.FAILED, LabStatus.ERROR_DESTROYING}
_INBOX_EVENTS = ("deploy_failed", "status", "finding", "finding_verification",
                 "arena_stop", "system_stop")
_FINISHED_TRIALS = {"completed", "infrastructure_failure", "protocol_failure", "failed",
                    "cancelled"}


def _arena_row(db, record: dict, binding_events: list[dict], trial: dict | None) -> dict:
    arena_id = record["id"]
    recent = db.recent_spans(arena_id, RECENT_SPANS)
    agent_actions = [s for s in recent if s["kind"] in ("tool", "agent", "model")]
    last = agent_actions[0] if agent_actions else None
    failed = sum(1 for s in agent_actions if s["status"] != "ok")
    budget = db.budget_status(arena_id)
    policy = (budget or {}).get("policy") or {}
    gate = (budget or {}).get("arena") or {}
    active = bindings.active_bindings(binding_events)
    return {
        "id": arena_id,
        "name": record.get("user_id") or arena_id,
        "scenario": record.get("scenario"),
        "state": record.get("status"),
        "expires_at": record.get("expires_at"),
        "created_at": record.get("created_at"),
        "agents": [{"name": b.get("agent_name"), "stance": b.get("stance"),
                    "paused": bool(b.get("paused"))} for b in active],
        "last_action": ({"name": last["name"], "actor": last["actor"],
                         "status": last["status"], "at": last["ended_at"] or last["started_at"]}
                        if last else None),
        "recent_actions": len(agent_actions),
        "error_rate": round(failed / len(agent_actions), 3) if agent_actions else None,
        "budget": {"remaining": policy.get("remaining"), "cap": policy.get("action_cap"),
                   "stopped": gate.get("state") == "stopped"},
        "trial": ({"id": trial["id"], "evaluation_id": trial["evaluation_id"],
                   "state": trial["state"], "seed": trial["seed"]} if trial else None),
    }


def _inbox(db, names: dict[str, str], trials: list[dict]) -> list[dict]:
    items = []
    for event in db.recent_events_of(_INBOX_EVENTS, limit=200):
        payload = event.get("payload") or {}
        kind, text = None, None
        if event["type"] == "deploy_failed":
            kind, text = "arena_failed", f"Deploy failed: {str(payload.get('error') or '')[:160]}"
        elif event["type"] == "status" and payload.get("to") in _FAILED:
            kind, text = "arena_failed", f"Arena entered {payload.get('to')}"
        elif event["type"] == "finding_verification":
            kind, text = "verdict", f"Finding {payload.get('verdict') or 'reviewed'} by {event['actor']}"
        elif event["type"] == "finding" and (payload.get("validation") or {}).get("verdict"):
            verdict = payload["validation"]["verdict"]
            kind, text = "verdict", f"Validator: {verdict} — {str(payload.get('title') or '')[:120]}"
        elif event["type"] in ("arena_stop", "system_stop"):
            kind = "stop"
            text = ("System stop engaged" if event["type"] == "system_stop"
                    else f"Research stopped: {str(payload.get('reason') or '')[:160]}")
        if kind:
            items.append({"key": f"event:{event['id']}", "kind": kind, "text": text,
                          "at": event["ts"], "arena_id": event["lab_id"],
                          "arena_name": names.get(event["lab_id"])})
    seen = set()
    for span in db.recent_refusals():
        if span["arena_id"] in seen:
            continue  # one exhaustion notice per arena
        seen.add(span["arena_id"])
        items.append({"key": f"span:{span['id']}", "kind": "budget_exhausted",
                      "text": f"Budget refused {span['name']} for {span['actor']}",
                      "at": span["started_at"], "arena_id": span["arena_id"],
                      "arena_name": names.get(span["arena_id"])})
    for trial in trials:
        if trial["state"] in _FINISHED_TRIALS:
            items.append({"key": f"trial:{trial['id']}:{trial['state']}", "kind": "trial_finished",
                          "text": f"Trial seed {trial['seed']} {trial['state'].replace('_', ' ')}",
                          "at": trial["updated_at"], "arena_id": trial["arena_id"],
                          "arena_name": names.get(trial["arena_id"] or ""),
                          "evaluation_id": trial["evaluation_id"]})
    items.sort(key=lambda item: item["at"] or "", reverse=True)
    return items[:INBOX_LIMIT]


def build(db, binding_events_for, now: str) -> dict:
    records = db.list_deployments()
    names = {r["id"]: (r.get("user_id") or r["id"]) for r in records}
    trials = db.eval_trials_for_board()
    trial_by_arena = {t["arena_id"]: t for t in trials if t["arena_id"]}
    arenas = [_arena_row(db, r, binding_events_for(r["id"]), trial_by_arena.get(r["id"]))
              for r in records if r.get("status") in _LIVE]
    return {"observed_at": now, "idle_minutes": IDLE_MINUTES, "arenas": arenas,
            "inbox": _inbox(db, names, trials)}
