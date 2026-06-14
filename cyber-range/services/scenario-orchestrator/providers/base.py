"""
RangeProvider — the deployment-backend driver interface (ADR-0003).

A provider turns a loaded scenario config into running lab infrastructure
and back. Everything above this interface (API, Celery tasks, Orchestrator)
is provider-agnostic; everything below it (OpenTofu, docker SDK, cloud
credentials) is the provider's business.

Result contract (kept dict-shaped for compatibility with tasks.py):
    deploy  -> {"success": True, "outputs": {...}}
            |  {"success": False, "error": "..."}
    destroy -> {"success": True} | {"success": False, "error": "..."}

Outputs are FLAT {name: value} mappings — no terraform {value,type}
envelopes (see Orchestrator._get_outputs history, audit #6).
"""
from abc import ABC, abstractmethod


class RangeProvider(ABC):
    """A backend capable of deploying/destroying lab instances."""

    #: registry key, e.g. "mock", "openstack", "docker-local", "aws"
    name: str = "abstract"

    #: what kind of infrastructure this backend provides: "vm", "container",
    #: or "any" (simulation). Matched against a scenario's
    #: `requires.provider_class` when a caller picks a provider explicitly.
    infra_class: str = "any"

    @abstractmethod
    def deploy(
        self,
        scenario_config: dict,
        instance_id: str,
        user_vars: dict | None = None,
    ) -> dict:
        """Provision the scenario as instance `instance_id`."""

    @abstractmethod
    def destroy(self, instance_id: str) -> dict:
        """Tear down the instance. Must be idempotent: destroying an
        unknown/already-gone instance is success, not an error."""

    def exec_in_node(
        self,
        instance_id: str,
        node: str,
        command: str,
        timeout: int = 30,
    ) -> dict:
        """Run a shell command inside an arena node and capture its output.

        Backs the MCP attacker stance's `run_command` (and, later, objective
        verification). Result contract:
            {"success": True, "exit_code": int, "stdout": str, "stderr": str}
          | {"success": False, "error": "..."}
        Not every backend supports exec (VM providers need SSH wiring first);
        the default refuses cleanly rather than pretending."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support exec_in_node yet"
        )
