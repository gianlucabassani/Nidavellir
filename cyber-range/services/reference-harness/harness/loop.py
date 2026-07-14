"""
harness.loop — the reference-harness engagement loop (ROADMAP M3, ADR-0010).

A thin, transport- and model-agnostic agentic loop: given a way to call arena
tools (`ToolsInterface`) and something that decides the next move (`Brain`), it
plays an arena — recon → exploit → `report_finding` → stop — bounded by a
`Budget`, and returns a `RunResult` (the transcript + counters that feed the eval
export).

Nidavellir ships **no AI of its own** (the load-bearing scope boundary): this is
thin wiring over the operator's bring-your-own model. The `Brain` is injected, so
the loop is fully unit-testable offline with a scripted brain and a fake tools
interface, and the same loop runs a real Claude agent over the MCP gateway in
production. Both `ToolsInterface` and `Brain` are async so a real model/MCP call
is a first-class await; the clock is injected so deadline logic is deterministic
in tests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# The tool an agent uses to submit a discovered vulnerability — the loop counts
# these and can stop once enough have been reported.
REPORT_FINDING = "report_finding"


@dataclass
class Budget:
    """Hard limits on one engagement. `max_steps` caps tool calls; `max_findings`
    stops once the agent has reported enough; `deadline_seconds` bounds wall-clock
    (None = no wall-clock limit). All are fail-safe: the loop stops at the limit
    rather than running away."""

    max_steps: int = 40
    max_findings: int | None = None
    deadline_seconds: float | None = None


@dataclass
class Action:
    """The brain's decision: call a tool, or stop."""

    kind: str  # "tool" | "stop"
    name: str | None = None
    args: dict = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def tool(cls, name: str, **args) -> "Action":
        return cls(kind="tool", name=name, args=args)

    @classmethod
    def stop(cls, reason: str = "done") -> "Action":
        return cls(kind="stop", reason=reason)


@dataclass
class Step:
    """One executed tool call and its outcome (a transcript entry)."""

    index: int
    ts: float
    tool: str
    args: dict
    ok: bool
    result: Any = None
    error: str | None = None


@dataclass
class EngagementState:
    """What the brain sees when deciding: the arena, the available tools, and the
    transcript so far."""

    arena_id: str
    tools: list[dict]
    history: list[Step]
    steps_used: int
    findings_reported: int


@dataclass
class RunResult:
    arena_id: str
    transcript: list[Step]
    steps_used: int
    findings_reported: int
    stop_reason: str
    elapsed_seconds: float

    def to_dict(self) -> dict:
        return {
            "arena_id": self.arena_id,
            "steps_used": self.steps_used,
            "findings_reported": self.findings_reported,
            "stop_reason": self.stop_reason,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "transcript": [
                {"index": s.index, "tool": s.tool, "args": s.args, "ok": s.ok,
                 "error": s.error}
                for s in self.transcript
            ],
        }


@runtime_checkable
class ToolsInterface(Protocol):
    async def list_tools(self) -> list[dict]: ...
    async def call(self, name: str, args: dict) -> dict: ...


@runtime_checkable
class Brain(Protocol):
    async def decide(self, state: EngagementState) -> Action: ...


async def run_engagement(
    *,
    arena_id: str,
    tools: ToolsInterface,
    brain: Brain,
    budget: Budget | None = None,
    clock=time.monotonic,
) -> RunResult:
    """Drive one engagement to completion and return its transcript + counters.

    Stops on the first of: the brain returns `Action.stop`, the step budget is
    hit, the findings target is reached, the wall-clock deadline elapses, or the
    brain errors (recorded, not raised — a broken brain ends the run cleanly)."""
    budget = budget or Budget()
    start = clock()
    deadline = start + budget.deadline_seconds if budget.deadline_seconds else None

    tool_defs = await tools.list_tools()
    transcript: list[Step] = []
    steps_used = 0
    findings = 0
    stop_reason = "budget_exhausted"

    while steps_used < budget.max_steps:
        if deadline is not None and clock() >= deadline:
            stop_reason = "deadline"
            break

        state = EngagementState(
            arena_id=arena_id, tools=tool_defs, history=transcript,
            steps_used=steps_used, findings_reported=findings,
        )
        try:
            action = await brain.decide(state)
        except Exception as e:  # noqa: BLE001 - a broken brain ends the run, not the process
            stop_reason = f"brain_error:{type(e).__name__}"
            break

        if action.kind == "stop":
            stop_reason = f"agent_stop:{action.reason or 'done'}"
            break
        if action.kind != "tool" or not action.name:
            stop_reason = "invalid_action"
            break

        ok, result, error = True, None, None
        try:
            result = await tools.call(action.name, action.args)
        except Exception as e:  # noqa: BLE001 - a failed tool call is observed, not fatal
            ok, error = False, f"{type(e).__name__}: {e}"

        steps_used += 1
        transcript.append(Step(
            index=steps_used, ts=clock() - start, tool=action.name,
            args=action.args, ok=ok, result=result, error=error,
        ))
        if ok and action.name == REPORT_FINDING:
            findings += 1
            if budget.max_findings is not None and findings >= budget.max_findings:
                stop_reason = "findings_target_reached"
                break

    return RunResult(
        arena_id=arena_id, transcript=transcript, steps_used=steps_used,
        findings_reported=findings, stop_reason=stop_reason,
        elapsed_seconds=clock() - start,
    )
