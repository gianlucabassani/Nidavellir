"""
Nidavellir reference harness (ROADMAP M3, ADR-0010).

A thin, optional bring-your-own-agent loop over the MCP gateway: it plays an arena,
produces a scored eval-dataset row, scales across a suite, and replays
deterministically. Nidavellir ships NO model or key — the reference agent is the
operator's Claude via the Anthropic SDK; the harness is wiring (scope boundary).
"""
from harness.brains import AnthropicBrain, ScriptedBrain
from harness.loop import (
    Action,
    Brain,
    Budget,
    EngagementState,
    RunResult,
    Step,
    ToolsInterface,
    run_engagement,
)
from harness.replay import plan_from_transcript, replay_run
from harness.runner import (
    ControlPlane,
    SingleRunConfig,
    run_single,
    run_suite,
    summarize,
    write_dataset,
)

__all__ = [
    "Action", "Brain", "Budget", "EngagementState", "RunResult", "Step",
    "ToolsInterface", "run_engagement", "AnthropicBrain", "ScriptedBrain",
    "ControlPlane", "SingleRunConfig", "run_single", "run_suite", "summarize",
    "write_dataset", "plan_from_transcript", "replay_run",
]
