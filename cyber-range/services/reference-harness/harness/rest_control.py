"""
harness.rest_control — the production `ControlPlane` over the orchestrator REST API.

Operator-side lifecycle: deploy a scenario, wait for it to go active, bind the
harness agent, pull the eval-export row, tear down. Uses the operator key for the
control plane; the agent key is used only by the MCP tools during the engagement
(separation the orchestrator enforces). HTTP is injectable for tests.
"""
from __future__ import annotations

import time
import uuid

_TERMINAL_BAD = {"failed", "error", "destroyed", "error_destroying"}


class RestControlPlane:
    def __init__(self, *, api_url: str, operator_key: str, provider: str | None = None,
                 http=None, poll_interval: float = 2.0):
        self.api_url = api_url.rstrip("/")
        self.operator_key = operator_key
        self.provider = provider
        self.poll_interval = poll_interval
        self._http = http

    @property
    def http(self):
        if self._http is None:
            import requests  # noqa: PLC0415 - lazy so the package imports without it
            self._http = requests
        return self._http

    def _req(self, method: str, path: str, json: dict | None = None) -> dict:
        resp = self.http.request(
            method, f"{self.api_url}{path}",
            headers={"X-API-Key": self.operator_key}, json=json, timeout=30,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {(resp.text or '')[:300]}")
        return resp.json() if resp.content else {}

    def deploy(self, scenario: str) -> str:
        # The instance_id we send is only a friendly label; the orchestrator
        # assigns its own system id (a UUID) and keys status / bindings /
        # eval-export / destroy on THAT. Return the assigned id so the rest of
        # the lifecycle addresses the arena correctly (fall back to the label
        # for older APIs that echoed nothing).
        friendly = f"rh-{uuid.uuid4().hex[:10]}"
        body = {"scenario": scenario, "instance_id": friendly}
        if self.provider:
            body["provider"] = self.provider
        resp = self._req("POST", "/deploy", body) or {}
        return resp.get("instance_id") or friendly

    def wait_active(self, arena_id: str, timeout: float = 120.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = (self._req("GET", f"/status/{arena_id}") or {}).get("status")
            if status == "active":
                return True
            if status in _TERMINAL_BAD:
                return False
            time.sleep(self.poll_interval)
        return False

    def bind_agent(self, arena_id: str, agent_name: str, stance: str) -> None:
        self._req("POST", f"/arenas/{arena_id}/bindings",
                  {"agent_name": agent_name, "stance": stance})

    def eval_export(self, arena_id: str) -> dict:
        return self._req("GET", f"/arenas/{arena_id}/eval-export")

    def destroy(self, arena_id: str) -> None:
        self._req("DELETE", f"/destroy/{arena_id}")
