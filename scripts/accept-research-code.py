#!/usr/bin/env python3
"""Acceptance for the research code-intel surface: mail collect+derive.

Runs the mail hunt's collect+derive step entirely through the new REST
surface (the human side; MCP wrappers are thin pass-throughs covered by
unit tests with fake transports): fix rows for the mail fixes plus
sibling candidates, with per-call output sizes for the cost comparison.
No mail probes (SMTP sink is the known prerequisite, next pass).
No model calls. Read-only over RESEARCH_REPO_DIR.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cyber-range/services/scenario-orchestrator"))

# Never touch developer state: redirect all runtime state at a throwaway
# dir (mirrors tests/conftest.py) before any application module imports.
_TMP = Path(tempfile.mkdtemp(prefix="nidavellir-accept-"))
os.environ.setdefault("MOCK_MODE", "true")
os.environ["DATABASE_PATH"] = str(_TMP / "deployments.db")
os.environ["RUNS_DIR"] = str(_TMP / "runs")
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["KEYS_DIR"] = str(_TMP / "keys")
os.environ["CACHE_DIR"] = str(_TMP / "cache")
os.environ["SECRETS_ENCRYPTION_KEY"] = ""

MAIL_FIXES = [
    {"advisory_id": "GHSA-7qqc-wrcw-2fj9", "fix_ref": "65ca78e9e"},
    {"advisory_id": "GHSA-96jx-fj7m-qh6x", "fix_ref": "9e9fc6213"},
    {"advisory_id": None, "fix_ref": "c28c532be"},  # beta bulk-mail-delete, no GHSA
]


def main() -> None:
    import auth
    from database import Database
    from fastapi.testclient import TestClient
    import api

    assert os.getenv("RESEARCH_REPO_DIR"), "RESEARCH_REPO_DIR is required"
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="accept-research-code",
                              role="operator")
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    calls = []

    def post(path, body):
        response = client.post(path, json=body)
        assert response.status_code == 200, (path, response.text)
        payload = response.json()
        calls.append({"path": path, "output_lines": len(json.dumps(
            payload, indent=1).splitlines()),
            "truncated": payload["truncation"]["truncated"],
            "digest": payload["digest"][:16]})
        return payload

    rows = [post("/research/code/fix-lookup", fix)["data"] for fix in MAIL_FIXES]
    mail_unscoped = post("/research/code/sibling-search", {
        "pattern": "unscoped-queryset", "ref": "v3.3.0",
        "path_scope": ["src/paperless_mail/"]})
    bulk = post("/research/code/sibling-search", {
        "pattern": "bulk-permission", "ref": "v3.3.0"})
    mail_diff = post("/research/code/layer-diff", {
        "from_ref": "65ca78e9e^", "to_ref": "65ca78e9e",
        "paths": ["src/paperless_mail/views.py"]})
    evidence = {
        "schema": "nidavellir/research-code-acceptance/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo": os.getenv("RESEARCH_REPO_DIR"),
        "fix_rows": [{"advisory_id": r["advisory_id"], "fix_ref": r["fix_ref"][:12],
                      "subject": r["subject"], "check_line": r["check_line"]}
                     for r in rows],
        "sibling_candidates": {
            "mail_unscoped": mail_unscoped["data"]["sites"],
            "bulk_permission": bulk["data"]["sites"][:10],
            "bulk_truncated": bulk["truncation"]["truncated"],
        },
        "mail_fix_diff": mail_diff["data"]["files"],
        "calls": calls,
        "manual_baseline": {
            "note": "observed cost of the manual mail-adjacent collect in the "
                    "variant-hunt round (same three fixes plus sibling greps)",
            "git_invocations": 10,
            "hunk_lines_read": "~600 plus follow-up file reads",
        },
    }
    path = ROOT / "docs/verification" / (
        f"research-code-accept-{datetime.now():%Y-%m-%d}-{os.getpid()}.json")
    with path.open("x") as handle:
        handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    total_lines = sum(c["output_lines"] for c in calls)
    print(f"Acceptance evidence: {path}")
    print(f"{len(calls)} tool calls, {total_lines} output lines total, "
          f"truncated={[c['truncated'] for c in calls]}")
    for row in evidence["fix_rows"]:
        print(f"- {row['advisory_id']}: {row['check_line']}")


if __name__ == "__main__":
    main()
