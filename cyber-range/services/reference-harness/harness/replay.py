"""
harness.replay — deterministic replay of a recorded run (ROADMAP M3, ADR-0010).

A recorded run's transcript is a pinned sequence of tool calls; replaying it means
re-deploying an identical arena from the same scenario and re-executing exactly
those calls (a `ScriptedBrain` fed from the transcript), then comparing the fresh
score to the recorded one. A run that can't be reproduced is a bug, not a result —
so replay is the regression primitive M5 builds on.

Reuses the same injectable control plane + tools factory as `runner`, so replay is
unit-testable with fakes and runs against the real gateway in production.
"""
from __future__ import annotations

from harness.brains import ScriptedBrain
from harness.runner import ControlPlane, SingleRunConfig, ToolsFactory, run_single


def plan_from_transcript(transcript: list[dict]) -> list[tuple[str, dict]]:
    """The ordered `(tool, args)` plan recorded in a run's transcript."""
    return [(s["tool"], s.get("args") or {}) for s in transcript or []]


def _score_key(score: dict | None):
    """The deterministic slice of a score used to decide reproduction (value +
    the found/confirmed sets — wall-clock and step timing are allowed to drift)."""
    score = score or {}
    ev = score.get("evidence") or {}
    return (
        score.get("value"),
        tuple(sorted(ev.get("found", []))),
        tuple(sorted(ev.get("confirmed", []))),
        ev.get("confirmed_findings"),
        ev.get("fault_sites"),
    )


async def replay_run(
    *,
    recorded_row: dict,
    control: ControlPlane,
    tools_factory: ToolsFactory,
    config: SingleRunConfig | None = None,
) -> dict:
    """Re-run a recorded row's transcript against a fresh identical arena and check
    the score reproduces. Returns `{reproduced, original_score, replay_score, replay}`."""
    scenario = recorded_row.get("scenario")
    if not scenario:
        scenario = ((recorded_row.get("input") or {}).get("target") or {}).get("scenario")
    if not scenario:
        raise ValueError("recorded row has no scenario to replay")

    plan = plan_from_transcript((recorded_row.get("run") or {}).get("transcript") or [])
    replay = await run_single(
        scenario=scenario, control=control, tools_factory=tools_factory,
        brain_factory=lambda: ScriptedBrain(plan), config=config,
    )

    original = recorded_row.get("score")
    fresh = replay.get("score")
    reproduced = _score_key(original) == _score_key(fresh)
    return {
        "reproduced": reproduced,
        "original_score": (original or {}).get("value"),
        "replay_score": (fresh or {}).get("value"),
        "replay": replay,
    }
