#!/usr/bin/env python3
"""Real HTTP + MCP authoring checks against disposable service state.

Run inside the pinned verifier with the provisioned source mounted read-only.
No infrastructure is provisioned and no developer database or credentials are used.
"""
from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "cyber-range/services/scenario-orchestrator"),
               str(ROOT / "cyber-range/services/agent-gateway")]


def main():
    import httpx
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New evidence path; existing files are never overwritten")
    args = parser.parse_args()
    path = args.output or ROOT / "docs/verification" / (
        f"research-code-live-{datetime.now():%Y-%m-%d}-{os.getpid()}.json")
    if path.exists():
        parser.error("evidence already exists; choose a new output path")

    assert os.environ.get("RESEARCH_REPO_DIR"), "Read-only source checkout is required"
    with tempfile.TemporaryDirectory(prefix="research-live-") as state:
        for name in ("DATABASE_PATH", "RUNS_DIR", "DATA_DIR", "KEYS_DIR", "CACHE_DIR"):
            os.environ[name] = str(Path(state) / name.lower())
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(state) / "database.sqlite")
        os.environ.pop("BOOTSTRAP_API_KEY", None)
        os.environ.update(MOCK_MODE="true", RATE_LIMIT_ENABLED="false", SECRETS_ENCRYPTION_KEY="")
        import api  # noqa: F401 - initialize schema before creating disposable principals
        import auth
        from database import Database

        operator, agent = auth.generate_api_key(), auth.generate_api_key()
        database = Database()
        database.create_api_key(auth.hash_api_key(operator), name="research-live-operator", role="operator")
        database.create_api_key(auth.hash_api_key(agent), name="research-live-agent", role="agent")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path[:2])}
        log_path = Path(state) / "api.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "18085"],
                cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                base = "http://127.0.0.1:18085"
                client = httpx.Client(base_url=base, timeout=20, headers={"X-API-Key": operator})
                with client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError("Disposable API exited during startup")
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(.1)
                    else:
                        raise RuntimeError("Disposable API did not become ready")
                    calls = []
                    for route, body in (
                        ("fix-lookup", {"fix_ref": "65ca78e9e"}),
                        ("layer-diff", {"from_ref": "65ca78e9e^", "to_ref": "65ca78e9e"}),
                        ("sibling-search", {"pattern": "unscoped-queryset", "ref": "v3.3.0", "offset": 50}),
                    ):
                        response = client.post(f"/research/code/{route}", json=body)
                        assert response.status_code == 200, (route, response.status_code)
                        value = response.json()
                        calls.append({"route": route, "status": 200, "digest": value["digest"]})
                    assert value["data"]["offset"] == 50
                    denied = client.post("/research/code/fix-lookup", json={"fix_ref": "65ca78e9e"},
                                         headers={"X-API-Key": agent})
                    assert denied.status_code == 403
                    failed = client.post("/research/code/fix-lookup", json={"fix_ref": "missing-ref"})
                    assert failed.status_code == 422

                async def mcp_checks():
                    parameters = StdioServerParameters(command=sys.executable,
                        args=["-m", "gateway.server"], env={**env,
                            "NIDAVELLIR_API_URL": base, "NIDAVELLIR_AGENT_KEY": operator,
                            "NIDAVELLIR_STANCE": "operator", "NIDAVELLIR_GATEWAY_TRANSPORT": "stdio",
                            "NIDAVELLIR_TRACE_DIR": str(Path(state) / "traces")})
                    with (Path(state) / "mcp.log").open("w") as error_log:
                        async with stdio_client(parameters, errlog=error_log) as (read, write):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                result = await session.call_tool("research_sibling_search", {
                                    "pattern": "unscoped-queryset", "ref": "v3.3.0", "offset": 50})
                                assert not result.isError
                                content = result.structuredContent or json.loads(result.content[0].text)
                                assert content["data"]["offset"] == 50
                                error = await session.call_tool("research_fix_lookup", {"fix_ref": "missing-ref"})
                                assert error.isError
                                return {"paged_query_digest": content["digest"], "failed_query_reported": True}

                mcp = asyncio.run(mcp_checks())
                events = database.list_events(lab_id="research-code", limit=100,
                                              types=("research_code_lookup",))
                outcomes = [event["payload"] for event in events]
                assert sum(p.get("outcome") == "failed" for p in outcomes) == 2
                assert sum(p.get("outcome") == "succeeded" for p in outcomes) == 4
                assert len(events) == 6  # authorization denial was not admitted
                serialized = json.dumps(outcomes)
                assert operator not in serialized and agent not in serialized
                evidence = {"schema": "nidavellir/research-code-live/v1",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "rest": calls, "agent_denied": True, "mcp": mcp,
                    "audit": outcomes, "authoring_budget": "unbudgeted operator queries",
                    "scope": "Real local HTTP and MCP transport; no arena or provider proof."}
                with path.open("x") as output:
                    output.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
                print(json.dumps({"evidence": str(path), "admitted_audits": len(events)}))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
