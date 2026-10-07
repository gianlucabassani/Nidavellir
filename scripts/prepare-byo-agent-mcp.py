#!/usr/bin/env python3
"""Prepare an isolated synthetic arena for one BYO-agent MCP participant test.

The client is deliberately not named: any harness that can speak MCP to the
scoped gateway (opencode today, Bughunt only as one example) uses the same
setup, participant key, binding and evidence contract.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAY_URL = "http://127.0.0.1:19006/mcp"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=("nv06", "nv09"), nargs="?", default="nv06")
    args = parser.parse_args()

    if args.fixture == "nv06":
        nv07 = _load("verify_nv07_live", "verify-nv07-live.py")
        image_id, source, challenge, _, _ = nv07.prepare()
        nv07.fixture.bind(source)
        goal = ("Determine whether account A (public credential token-a-public) can read "
                "account B's private object; report a finding only with the observed "
                "transaction digest.")
    else:
        nv09 = _load("verify_nv09_live", "verify-nv09-live.py")
        _, image_id, source, challenge, _, _, _, _ = nv09._prepare()
        nv09.fixture.bind(source)
        goal = ("Determine whether account A (public credential token-a-public) can read "
                "account B's object through the synthetic SPA; browser sessions A and B "
                "are available, and a finding needs the observed transaction digest.")

    evidence = {
        "schema": "nidavellir/byo-agent-mcp-setup/v1",
        "fixture": args.fixture,
        "source_arena": source,
        "challenge_id": challenge["id"],
        "fixture_image": image_id,
        "gateway_url": GATEWAY_URL,
        "participant_key": "nv06-agent",
        "goal": goal,
        "model_requests": 0,
    }
    path = ROOT / "docs/verification" / (
        f"byo-agent-{args.fixture}-setup-{datetime.now():%Y-%m-%d}-{uuid.uuid4().hex[:8]}.json")
    with path.open("x") as handle:
        handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(f"Prepared BYO-agent arena: {path}")
    print(f"Fixture {args.fixture}; arena {source}; gateway {GATEWAY_URL}")


if __name__ == "__main__":
    main()
