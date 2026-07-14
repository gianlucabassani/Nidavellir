"""
Reference-harness CLI (ROADMAP M3, ADR-0010).

Run a bring-your-own agent against one or more Nidavellir arenas and emit a scored
eval dataset (JSONL). The AI is the operator's own Claude (`--model`); with no
`--api-key` the harness falls back to a scripted smoke agent (recon → report),
useful for a keyless end-to-end check.

    python -m harness --api-url http://127.0.0.1:8099 \
        --operator-key cg_... --agent-key cg_... \
        --scenario container_web_pentest --model claude-fable-5 \
        --anthropic-key sk-ant-... --out dataset.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from harness.brains import AnthropicBrain, ScriptedBrain
from harness.loop import Budget
from harness.mcp_tools import McpToolsInterface, gateway_env
from harness.rest_control import RestControlPlane
from harness.runner import SingleRunConfig, run_suite, write_dataset

# The keyless smoke plan: minimal recon + a probe report so the whole
# arena→gateway→score path is exercised without a model.
_SMOKE_PLAN = [
    ("get_topology", {}),
    ("list_targets", {}),
    ("run_command", {"command": "id; uname -a"}),
    ("report_finding", {"title": "smoke probe", "cwe": "CWE-79", "node": "victim",
                        "evidence": "reference-harness smoke run"}),
]


def _build_args():
    p = argparse.ArgumentParser(prog="harness")
    p.add_argument("--api-url", default=os.getenv("NIDAVELLIR_API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--operator-key", required=True)
    p.add_argument("--agent-key", required=True)
    p.add_argument("--scenario", action="append", default=[], help="repeatable")
    p.add_argument("--stance", default="attacker")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None, help="BYO Claude model id; omit for scripted smoke")
    p.add_argument("--anthropic-key", default=os.getenv("ANTHROPIC_API_KEY"))
    p.add_argument("--gateway-path", default=os.getenv(
        "NIDAVELLIR_GATEWAY_PYTHONPATH",
        os.path.join(os.path.dirname(__file__), "..", "..", "agent-gateway")))
    p.add_argument("--max-steps", type=int, default=40)
    p.add_argument("--max-findings", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--out", default=None, help="write the dataset JSONL here")
    return p.parse_args()


def main() -> int:
    a = _build_args()
    if not a.scenario:
        print("no --scenario given", file=sys.stderr)
        return 2

    control = RestControlPlane(api_url=a.api_url, operator_key=a.operator_key,
                               provider=a.provider)
    gw_path = os.path.abspath(a.gateway_path)
    env = gateway_env(agent_key=a.agent_key, stance=a.stance, api_url=a.api_url,
                      gateway_pythonpath=gw_path)

    def tools_factory(arena_id: str):
        return McpToolsInterface(command=sys.executable, args=["-m", "gateway.server"],
                                 env=env, arena_id=arena_id)

    if a.model:
        def brain_factory():
            return AnthropicBrain(model=a.model, api_key=a.anthropic_key)
    else:
        def brain_factory():
            return ScriptedBrain(_SMOKE_PLAN)

    cfg = SingleRunConfig(stance=a.stance,
                          budget=Budget(max_steps=a.max_steps, max_findings=a.max_findings))
    out = asyncio.run(run_suite(
        scenarios=a.scenario, control=control, tools_factory=tools_factory,
        brain_factory=brain_factory, config=cfg, concurrency=a.concurrency,
    ))
    print(json.dumps(out["summary"], indent=2))
    if a.out:
        n = write_dataset(out["rows"], a.out)
        print(f"wrote {n} eval rows -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
