#!/usr/bin/env python3
"""Prepare an isolated synthetic arena for a Claude Code MCP participant test."""
from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_nv07_live", Path(__file__).with_name("verify-nv07-live.py"))
nv07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv07)


def main() -> None:
    image_id, source, challenge, _, _ = nv07.prepare()
    nv07.fixture.bind(source)
    evidence = {"schema": "nidavellir/nv07-claude-mcp-setup/v1",
                "source_arena": source, "challenge_id": challenge["id"],
                "fixture_image": image_id, "model_requests": 0}
    path = ROOT / "docs/verification" / (
        f"nv07-claude-mcp-setup-{datetime.now():%Y-%m-%d}-{uuid.uuid4().hex[:8]}.json")
    with path.open("x") as handle:
        handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(f"Prepared Claude MCP arena: {path}")
    print(f"Arena: {source}")


if __name__ == "__main__":
    main()
