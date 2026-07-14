"""
harness.runner — single-run and scalable batch-suite execution (ROADMAP M3, ADR-0010).

`run_single` plays one arena end-to-end (deploy → bind → engage over MCP →
eval-export → destroy) and returns its eval-dataset row with the engagement
transcript attached. `run_suite` fans that over many scenarios with a concurrency
cap and emits a dataset (list of rows) + an aggregate `summary` — the benchmark
runner, and the seed of M5's cross-version regression.

The control plane (deploy/bind/eval-export/destroy) and the per-arena tools factory
are **injected** (`ControlPlane` / `tools_factory`), so the runner is unit-testable
with fakes and wires to REST + the MCP gateway in production. Concurrency is a hard
semaphore; a single arena that errors becomes an error row, never aborting the suite.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Callable, Protocol

from harness.loop import Brain, Budget, ToolsInterface, run_engagement


class ControlPlane(Protocol):
    """Operator-side arena lifecycle (sync; run off-thread by the runner)."""
    def deploy(self, scenario: str) -> str: ...
    def wait_active(self, arena_id: str, timeout: float = 120.0) -> bool: ...
    def bind_agent(self, arena_id: str, agent_name: str, stance: str) -> None: ...
    def eval_export(self, arena_id: str) -> dict: ...
    def destroy(self, arena_id: str) -> None: ...


# tools_factory(arena_id) -> async context manager yielding a ToolsInterface.
ToolsFactory = Callable[[str], "AsyncCtx"]
BrainFactory = Callable[[], Brain]


class AsyncCtx(Protocol):
    async def __aenter__(self) -> ToolsInterface: ...
    async def __aexit__(self, *exc) -> None: ...


@dataclass
class SingleRunConfig:
    stance: str = "attacker"
    agent_name: str = "reference-harness"
    active_timeout: float = 120.0
    destroy_after: bool = True
    budget: Budget | None = None


async def run_single(
    *,
    scenario: str,
    control: ControlPlane,
    tools_factory: ToolsFactory,
    brain_factory: BrainFactory,
    config: SingleRunConfig | None = None,
) -> dict:
    """Play one arena and return its eval-dataset row (+ the run transcript).

    Never raises for an arena-level failure — returns an error row so a suite keeps
    going. The arena is torn down in `finally` when `destroy_after` is set."""
    config = config or SingleRunConfig()
    arena_id = None
    try:
        arena_id = await asyncio.to_thread(control.deploy, scenario)
        active = await asyncio.to_thread(control.wait_active, arena_id, config.active_timeout)
        if not active:
            return _error_row(scenario, arena_id, "arena did not become active")
        await asyncio.to_thread(control.bind_agent, arena_id, config.agent_name, config.stance)

        async with tools_factory(arena_id) as tools:
            result = await run_engagement(
                arena_id=arena_id, tools=tools, brain=brain_factory(),
                budget=config.budget,
            )

        row = await asyncio.to_thread(control.eval_export, arena_id)
        row["run"] = result.to_dict()
        row.setdefault("scenario", scenario)
        return row
    except Exception as e:  # noqa: BLE001 - one arena's failure is a row, not a crash
        return _error_row(scenario, arena_id, f"{type(e).__name__}: {e}")
    finally:
        if arena_id and config.destroy_after:
            try:
                await asyncio.to_thread(control.destroy, arena_id)
            except Exception:  # noqa: BLE001 - teardown best-effort
                pass


async def run_suite(
    *,
    scenarios: list[str],
    control: ControlPlane,
    tools_factory: ToolsFactory,
    brain_factory: BrainFactory,
    config: SingleRunConfig | None = None,
    concurrency: int = 4,
) -> dict:
    """Run every scenario (concurrency-capped) and return `{rows, summary}`."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(scn: str) -> dict:
        async with sem:
            return await run_single(
                scenario=scn, control=control, tools_factory=tools_factory,
                brain_factory=brain_factory, config=config,
            )

    rows = await asyncio.gather(*(_one(s) for s in scenarios))
    return {"rows": list(rows), "summary": summarize(rows)}


def _error_row(scenario: str, arena_id: str | None, error: str) -> dict:
    return {"run_id": arena_id, "scenario": scenario, "error": error,
            "metadata": {"error": error}, "score": None}


def summarize(rows: list[dict]) -> dict:
    """Aggregate a suite's rows into headline metrics (pure)."""
    n = len(rows)
    ok = [r for r in rows if not r.get("error")]
    errored = n - len(ok)

    def meta(r, k, default=0):
        return (r.get("metadata") or {}).get(k, default)

    solved = sum(1 for r in ok if meta(r, "pass@1", 0) == 1)
    progresses = [float(meta(r, "nv.progress_rate", 0) or 0) for r in ok]
    attributed = sum(1 for r in ok if meta(r, "attributed", False))
    modes: dict[str, int] = {}
    for r in ok:
        modes[meta(r, "nv.mode", "unknown")] = modes.get(meta(r, "nv.mode", "unknown"), 0) + 1

    return {
        "runs": n,
        "completed": len(ok),
        "errored": errored,
        "solved": solved,
        "solve_rate": round(solved / len(ok), 4) if ok else 0.0,
        "avg_progress_rate": round(sum(progresses) / len(progresses), 4) if progresses else 0.0,
        "attributed": attributed,
        "modes": modes,
    }


def write_dataset(rows: list[dict], path: str) -> int:
    """Write rows as JSONL (one eval record per line). Returns the count."""
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    return len(rows)
