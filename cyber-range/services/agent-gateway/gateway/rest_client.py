"""
Thin HTTP client over the orchestrator REST API.

The gateway proxies the lifecycle endpoints (it never imports the orchestrator),
forwarding the agent's API key so the orchestrator remains the authn/authz and
audit authority. The HTTP layer is injectable (`http=`) so tool logic is
unit-tested with a fake transport — no live server required.
"""
import logging
import urllib.parse
import uuid

logger = logging.getLogger(__name__)

# Cap echoed upstream error bodies so a noisy 5xx can't flood logs/traces.
_MAX_ERROR_BODY = 500


class GatewayRestError(Exception):
    """An upstream REST call failed (non-2xx) or could not be reached."""


class RestClient:
    def __init__(self, base_url: str, timeout: float = 15.0, http=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = http  # injectable; lazily import `requests` otherwise

    @property
    def http(self):
        if self._http is None:
            import requests

            self._http = requests
        return self._http

    def _request(self, method: str, path: str, api_key: str, json: dict | None = None):
        url = f"{self.base_url}{path}"
        try:
            resp = self.http.request(
                method,
                url,
                headers={"X-API-Key": api_key},
                json=json,
                timeout=self.timeout,
            )
        except Exception as e:  # network/transport failure
            raise GatewayRestError(f"{method} {path}: upstream unreachable ({e})") from e

        if resp.status_code >= 400:
            body = (resp.text or "")[:_MAX_ERROR_BODY]
            raise GatewayRestError(f"{method} {path} -> {resp.status_code}: {body}")
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # --- lifecycle endpoints --------------------------------------------------

    def list_scenarios(self, api_key: str) -> dict:
        return self._request("GET", "/scenarios", api_key)

    def deploy(self, api_key: str, scenario: str, instance_id: str, provider: str | None = None) -> dict:
        body = {"scenario": scenario, "instance_id": instance_id}
        if provider:
            body["provider"] = provider
        return self._request("POST", "/deploy", api_key, json=body)

    def status(self, api_key: str, instance_id: str) -> dict:
        return self._request("GET", f"/status/{instance_id}", api_key)

    def budget_status(self, api_key: str, arena_id: str) -> dict:
        return self._request("GET", f"/arenas/{arena_id}/budget", api_key)

    def runtime_capabilities(self, api_key: str, arena_id: str) -> dict:
        return self._request("GET", f"/arenas/{arena_id}/capabilities", api_key)

    def open_forward(self, api_key: str, arena_id: str, foothold: str,
                     target: str, service_id: str, lifetime_seconds: int,
                     idempotency_key: str) -> dict:
        return self._request("POST", f"/arenas/{arena_id}/forwards", api_key,
                             json={"foothold": foothold, "target": target,
                                   "service_id": service_id,
                                   "lifetime_seconds": lifetime_seconds,
                                   "idempotency_key": idempotency_key})

    def forward_status(self, api_key: str, arena_id: str, forward_id: str) -> dict:
        return self._request("GET", f"/arenas/{arena_id}/forwards/{forward_id}", api_key)

    def revoke_forward(self, api_key: str, arena_id: str, forward_id: str) -> dict:
        return self._request("POST", f"/arenas/{arena_id}/forwards/{forward_id}/revoke",
                             api_key)

    def stop_arena(self, api_key: str, arena_id: str, reason: str) -> dict:
        return self._request("POST", f"/arenas/{arena_id}/stop", api_key,
                             json={"reason": reason, "idempotency_key": uuid.uuid4().hex})

    def resume_arena(self, api_key: str, arena_id: str, reason: str) -> dict:
        return self._request("POST", f"/arenas/{arena_id}/resume", api_key,
                             json={"reason": reason, "idempotency_key": uuid.uuid4().hex})

    def emergency_stop(self, api_key: str, reason: str) -> dict:
        return self._request("POST", "/system/emergency-stop", api_key,
                             json={"reason": reason, "idempotency_key": uuid.uuid4().hex})

    def clear_emergency_stop(self, api_key: str, reason: str) -> dict:
        return self._request("POST", "/system/emergency-stop/clear", api_key,
                             json={"reason": reason, "idempotency_key": uuid.uuid4().hex})

    def destroy(self, api_key: str, instance_id: str) -> dict:
        return self._request("DELETE", f"/destroy/{instance_id}", api_key)

    def list_deployments(self, api_key: str) -> dict:
        return self._request("GET", "/deployments", api_key)

    def exec_command(self, api_key: str, arena_id: str, node: str, command: str,
                     timeout: int = 30) -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/exec", api_key,
            json={"node": node, "command": command, "timeout": timeout},
        )

    def transfer_upload(
        self, api_key: str, arena_id: str, path: str, content_b64: str,
        node: str | None = None,
    ) -> dict:
        body = {"path": path, "content_b64": content_b64}
        if node:
            body["node"] = node
        return self._request(
            "POST", f"/arenas/{arena_id}/files/upload", api_key, json=body
        )

    def transfer_download(
        self, api_key: str, arena_id: str, path: str, node: str | None = None,
        offset: int = 0, max_bytes: int = 262144,
    ) -> dict:
        body = {"path": path, "offset": int(offset), "max_bytes": int(max_bytes)}
        if node:
            body["node"] = node
        return self._request(
            "POST", f"/arenas/{arena_id}/files/download", api_key, json=body
        )

    def browser_visit(
        self, api_key: str, arena_id: str, node: str, path: str = "/",
        params: dict[str, str] | None = None, wait_ms: int = 1500,
    ) -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/browser/visit", api_key,
            json={
                "node": node, "path": path, "params": params or {},
                "wait_ms": int(wait_ms),
            },
        )

    def http_request(
        self, api_key: str, arena_id: str, node: str, path: str = "/",
        params: dict[str, str] | None = None, method: str = "GET",
        headers: dict[str, str] | None = None, body: str | None = None,
    ) -> dict:
        payload: dict = {"node": node, "path": path, "method": method}
        if params:
            payload["params"] = params
        if headers:
            payload["headers"] = headers
        if body is not None:
            payload["body"] = body
        return self._request(
            "POST", f"/arenas/{arena_id}/http/request", api_key, json=payload
        )

    def http_transactions(
        self, api_key: str, arena_id: str, limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        query = urllib.parse.urlencode(
            {k: v for k, v in (("limit", limit), ("offset", offset)) if v}
        )
        suffix = f"?{query}" if query else ""
        return self._request(
            "GET", f"/arenas/{arena_id}/http/transactions{suffix}", api_key
        )

    def http_transaction(self, api_key: str, arena_id: str, digest: str) -> dict:
        encoded = urllib.parse.quote(digest, safe="")
        return self._request(
            "GET", f"/arenas/{arena_id}/http/transactions/{encoded}", api_key
        )

    def http_replay(
        self, api_key: str, arena_id: str, digest: str, *,
        node: str | None = None, path: str | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        method: str | None = None, body: str | None = None,
    ) -> dict:
        encoded = urllib.parse.quote(digest, safe="")
        payload: dict = {}
        for key, val in (
            ("node", node), ("path", path), ("params", params),
            ("headers", headers), ("method", method), ("body", body),
        ):
            if val is not None:
                payload[key] = val
        return self._request(
            "POST",
            f"/arenas/{arena_id}/http/transactions/{encoded}/replay",
            api_key, json=payload,
        )

    def submit_poc(
        self, api_key: str, arena_id: str, source: str, *,
        target_node: str | None = None, transfer_files: list[str] | None = None,
        timeout_seconds: int = 30, memory_mb: int = 128,
        cpu_millis: int = 500, pids: int = 32,
        idempotency_key: str,
    ) -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/poc-jobs", api_key,
            json={
                "source": source, "target_node": target_node,
                "transfer_files": transfer_files or [],
                "timeout_seconds": timeout_seconds, "memory_mb": memory_mb,
                "cpu_millis": cpu_millis, "pids": pids,
                "idempotency_key": idempotency_key,
            },
        )

    def poc_job(self, api_key: str, arena_id: str, job_id: str) -> dict:
        return self._request("GET", f"/arenas/{arena_id}/poc-jobs/{job_id}", api_key)

    def cancel_poc(self, api_key: str, arena_id: str, job_id: str) -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/poc-jobs/{job_id}/cancel", api_key, json={}
        )

    def list_events(self, api_key: str, arena_id: str, limit: int = 100) -> dict:
        return self._request(
            "GET", f"/deployments/{arena_id}/events?limit={int(limit)}", api_key
        )

    def mitm_observe(self, api_key: str, arena_id: str, seconds: int = 6,
                     max_packets: int = 200) -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/mitm/observe", api_key,
            json={"seconds": seconds, "max_packets": max_packets},
        )

    def report_finding(self, api_key: str, arena_id: str, title: str,
                       cwe: str | None = None, node: str | None = None,
                       evidence: str | None = None, path: str | None = None,
                       param: str | None = None, payload: str | None = None,
                       oast_token: str | None = None, poc: str | None = None,
                       evidence_artifact_digests: list[str] | None = None,
                       transaction_digests: list[str] | None = None) -> dict:
        body: dict = {"title": title}
        # Only send set fields; path/param/payload/oast_token are the optional
        # verification inputs that let the orchestrator ACTIVELY confirm a finding;
        # `poc` is the reproducible proof a human can run to verify.
        for key, val in (("cwe", cwe), ("node", node), ("evidence", evidence),
                         ("path", path), ("param", param), ("payload", payload),
                         ("oast_token", oast_token), ("poc", poc)):
            if val:
                body[key] = val
        if evidence_artifact_digests:
            body["evidence_artifact_digests"] = evidence_artifact_digests
        if transaction_digests:
            body["transaction_digests"] = transaction_digests
        return self._request("POST", f"/arenas/{arena_id}/findings", api_key, json=body)

    def announce_agent(self, api_key: str, arena_id: str, model: str, provider: str,
                       stance: str | None = None) -> dict:
        body: dict = {"model": model, "provider": provider}
        if stance:
            body["stance"] = stance
        return self._request("POST", f"/arenas/{arena_id}/agent-session", api_key, json=body)

    # --- source change intelligence ------------------------------------------

    def list_workspaces(self, api_key: str, arena_id: str) -> dict:
        return self._request("GET", f"/arenas/{arena_id}/workspaces", api_key)

    def workspace_diff(
        self,
        api_key: str,
        arena_id: str,
        node: str,
        *,
        base: str = "HEAD",
        path: str | None = None,
        context_lines: int = 3,
        start_line: int = 0,
        max_lines: int = 300,
    ) -> dict:
        query = {
            "base": base,
            "context_lines": int(context_lines),
            "start_line": int(start_line),
            "max_lines": int(max_lines),
        }
        if path:
            query["path"] = path
        encoded_node = urllib.parse.quote(node, safe="")
        return self._request(
            "GET",
            f"/arenas/{arena_id}/workspaces/{encoded_node}/diff?"
            f"{urllib.parse.urlencode(query)}",
            api_key,
        )

    def workspace_patch_artifact(
        self, api_key: str, arena_id: str, node: str, *, base: str = "HEAD",
        path: str | None = None, context_lines: int = 3,
        include_untracked_paths: list[str] | None = None,
    ) -> dict:
        body = {
            "base": base,
            "context_lines": int(context_lines),
            "include_untracked_paths": include_untracked_paths or [],
        }
        if path:
            body["path"] = path
        encoded_node = urllib.parse.quote(node, safe="")
        return self._request(
            "POST", f"/arenas/{arena_id}/workspaces/{encoded_node}/patch-artifacts",
            api_key, json=body,
        )

    def session_preflight(self, api_key: str, arena_id: str) -> dict:
        return self._request("GET", f"/arenas/{arena_id}/preflight", api_key)

    # --- configurator stance (SUT setup phase) --------------------------------

    def setup_brief(self, api_key: str, arena_id: str) -> dict:
        return self._request("GET", f"/arenas/{arena_id}/setup/brief", api_key)

    def setup_propose(self, api_key: str, arena_id: str, node: str, command: str,
                      rationale: str = "") -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/setup/propose", api_key,
            json={"node": node, "command": command, "rationale": rationale},
        )

    def setup_proposal_status(self, api_key: str, arena_id: str, step_id: str) -> dict:
        return self._request(
            "GET", f"/arenas/{arena_id}/setup/proposals/{step_id}", api_key
        )

    def setup_run(self, api_key: str, arena_id: str, node: str, command: str,
                  timeout: int = 60) -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/setup/run", api_key,
            json={"node": node, "command": command, "timeout": timeout},
        )

    def setup_upload(self, api_key: str, arena_id: str, node: str, path: str,
                     content_b64: str) -> dict:
        return self._request(
            "POST", f"/arenas/{arena_id}/setup/upload", api_key,
            json={"node": node, "path": path, "content_b64": content_b64},
        )

    def setup_finish(self, api_key: str, arena_id: str) -> dict:
        return self._request("POST", f"/arenas/{arena_id}/setup/finish", api_key)

    # --- operator authoring (P3) ---------------------------------------------

    def generate_scenario(self, api_key: str, prompt: str,
                          provider_class: str | None = None) -> dict:
        body = {"prompt": prompt}
        if provider_class:
            body["provider_class"] = provider_class
        return self._request("POST", "/scenarios/generate", api_key, json=body)

    def import_scenario(self, api_key: str, spec, scenario_id: str | None = None,
                       overwrite: bool = False) -> dict:
        body = {"spec": spec, "overwrite": overwrite}
        if scenario_id:
            body["id"] = scenario_id
        return self._request("POST", "/scenarios", api_key, json=body)
