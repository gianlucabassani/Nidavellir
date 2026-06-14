"""
Thin HTTP client over the orchestrator REST API.

The gateway proxies the lifecycle endpoints (it never imports the orchestrator),
forwarding the agent's API key so the orchestrator remains the authn/authz and
audit authority. The HTTP layer is injectable (`http=`) so tool logic is
unit-tested with a fake transport — no live server required.
"""
import logging

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
