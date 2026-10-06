#!/usr/bin/env python3
"""Prepare one isolated NV07-R1 calibration smoke without invoking a model."""
from __future__ import annotations

import importlib.util
import base64
import json
import os
import secrets
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_nv07_live", Path(__file__).with_name("verify-nv07-live.py"))
nv07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv07)


def smoke_connection() -> dict:
    """Read the operator-specified smoke connection without displaying secrets.

    Source (all operator-supplied, never logged or written to evidence):

    - ``NV07_SMOKE_PROVIDER`` / ``NV07_SMOKE_MODEL`` (required)
    - ``NV07_SMOKE_BASE_URL`` (optional; required for ``custom``/``local``)
    - ``NV07_SMOKE_API_KEY`` (optional for keyless providers; empty = none)
    - ``NV07_SMOKE_HEADERS_JSON`` (optional JSON object of static extra
      headers, e.g. ``{"User-Agent": "opencode-x", "x-opencode-session": "…"}``)

    The secret is transferred over loopback into PostgreSQL tmpfs and never
    put in evidence. Raises before touching the isolated stack when required
    inputs are missing or malformed.
    """
    provider = (os.getenv("NV07_SMOKE_PROVIDER") or "").strip().lower()
    model = (os.getenv("NV07_SMOKE_MODEL") or "").strip()
    if not provider or not model:
        raise RuntimeError("NV07_SMOKE_PROVIDER and NV07_SMOKE_MODEL are required")
    base_url = (os.getenv("NV07_SMOKE_BASE_URL") or "").strip() or None
    api_key = os.getenv("NV07_SMOKE_API_KEY") or ""
    raw_headers = (os.getenv("NV07_SMOKE_HEADERS_JSON") or "").strip()
    headers: dict = {}
    if raw_headers:
        try:
            parsed = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise RuntimeError("NV07_SMOKE_HEADERS_JSON is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("NV07_SMOKE_HEADERS_JSON must be a JSON object")
        headers = parsed
    return {"provider": provider, "model": model, "base_url": base_url,
            "api_key": api_key, "extra_headers": headers}


def main() -> None:
    # Read the operator-specified connection before replacing the isolated
    # stack. Secrets never reach evidence or stdout.
    connection = smoke_connection()
    os.environ["NV07_SECRETS_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(
        secrets.token_bytes(32)).decode()
    image_id, source, challenge, _, _ = nv07.prepare()
    payload = {"provider": connection["provider"], "model": connection["model"],
               "api_key": connection["api_key"]}
    if connection["base_url"]:
        payload["base_url"] = connection["base_url"]
    if connection["extra_headers"]:
        payload["extra_headers"] = connection["extra_headers"]
    metadata = nv07.fixture.api("PUT", "/agent/model", payload)
    provider, model, has_headers = (connection["provider"], connection["model"],
                                    bool(connection["extra_headers"]))
    # Drop secrets from memory as soon as the loopback PUT is done.
    connection["api_key"] = ""
    connection["extra_headers"] = {}
    del payload
    if metadata.get("provider") != provider or metadata.get("model") != model:
        raise RuntimeError("isolated model connection metadata did not match")
    if has_headers:
        encrypted = nv07.fixture.run(*nv07.fixture.COMPOSE, "exec", "-T", "postgres",
            "psql", "-U", "nidavellir", "-d", "nidavellir_nv06", "-Atc",
            "SELECT count(*), bool_and(left(encrypted_key,7)='enc:v1:'), "
            "bool_and(encrypted_headers IS NULL OR left(encrypted_headers,7)='enc:v1:') "
            "FROM model_connections").stdout.strip()
        if encrypted != "1|t|t":
            raise RuntimeError("isolated credential was not encrypted at rest")
    else:
        encrypted = nv07.fixture.run(*nv07.fixture.COMPOSE, "exec", "-T", "postgres",
            "psql", "-U", "nidavellir", "-d", "nidavellir_nv06", "-Atc",
            "SELECT count(*), bool_and(left(encrypted_key,7)='enc:v1:') "
            "FROM model_connections").stdout.strip()
        if encrypted != "1|t":
            raise RuntimeError("isolated credential was not encrypted at rest")
    build = nv07.fixture.api("POST", "/agent-builds", {
        "name": f"nv07-r1-{metadata['provider']}-single-smoke", "version": "v1",
        "driver": "model-mcp/v1",
        "goal": ("Assess the synthetic target node for cross-account object authorization. "
                 "Account A's synthetic credential is token-a-public. Send scoped http_request "
                 "calls to node \"target\", e.g. GET /objects/B with header Authorization: "
                 "Bearer token-a-public, and observe the responses. Report a finding with its "
                 "transaction digest only when a response shows account A reading account B's "
                 "object, then stop."),
        "max_model_calls": 12, "max_output_tokens": 512,
    }, expected=(201,))
    assert build["driver"] == "model-mcp/v1" and build["digest"].startswith("sha256:")
    assert nv07.fixture.api("GET", "/agent/model")["status"] == "standby"
    assert nv07.fixture.api("GET", "/evaluations")["evaluations"] == []
    assert nv07.fixture.api("GET", f"/status/{source}")["status"] == "active"
    evidence = {
        "schema": "nidavellir/nv07-r1-smoke-setup/v1",
        "model_requests": 0,
        "source_arena": source,
        "challenge_id": challenge["id"],
        "challenge_label": challenge["label"],
        "build_id": build["id"],
        "build_digest": build["digest"],
        "fixture_image": image_id,
        "connection": {"provider": metadata["provider"], "model": metadata["model"],
                       "status": metadata["status"], "encrypted_at_rest": True,
                       "header_names": metadata.get("header_names", []),
                       "headers_digest": metadata.get("headers_digest")},
        "proposed_request": {"challenge_id": challenge["id"], "build_id": build["id"],
                             "seed": 1, "action_cap": 12, "deadline_seconds": 600},
    }
    path = ROOT / "docs/verification" / (
        f"nv07-r1-setup-{datetime.now():%Y-%m-%d}-{uuid.uuid4().hex[:8]}.json")
    with path.open("x") as handle:
        handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(f"Prepared without model requests: {path}")
    print(f"Source {source}; challenge {challenge['id']}; build {build['id']}")


if __name__ == "__main__":
    main()
