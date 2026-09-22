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

    def set_node_egress(self, instance_id: str, node: str, open: bool) -> dict:
        """Open or close a node's internet egress during the SUT setup phase
        (the configurator capability, ADR-0007 / P2-10). Opening lets the node
        fetch arbitrary dependencies while a service is brought up; it MUST be
        closed again before the engagement so the arena runtime stays
        egress-locked. Result contract:
            {"success": True, "egress": "open"|"closed"} | {"success": False, "error": ...}
        Not every backend can toggle egress; the default refuses cleanly."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support setup-time egress yet"
        )

    def capture_traffic(self, instance_id: str, *, seconds: int = 6,
                        max_packets: int = 200) -> dict:
        """Observe in-flight traffic on the arena's shared segment(s) — the MCP
        MITM stance's backend (in-path observation). Bounded by ``seconds`` /
        ``max_packets``. Result contract:
            {"success": True, "flows": [{src,dst,proto,sport,dport,...}], "packets": int, ...}
          | {"success": False, "error": "..."}
        Not every backend can tap a segment; the default refuses cleanly."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support traffic capture yet"
        )

    def collect_monitor_signals(self, instance_id: str) -> dict:
        """Gather raw runtime observations for the service-under-test nodes of an
        arena — the backend for the M2 monitor (the crash / sanitizer-abort /
        unhandled-5xx / resource-exhaustion oracle, ADR-0009). Read-only and
        best-effort: it never raises for a single bad node. The pure
        ``monitor.detect_signals`` turns these observations into scored evidence.
        Result contract:
            {"success": True, "observations": [
                {name, role, state, exit_code, oom_killed, restart_count, log_tail}
            ]}
          | {"success": False, "error": "..."}
        Backends that can't introspect a running workload (VM/cloud until M8)
        refuse cleanly rather than pretending."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support monitor signals yet"
        )

    def workspace_diff(
        self,
        instance_id: str,
        node: str,
        source_path: str,
        *,
        base: str = "HEAD",
        path: str | None = None,
        context_lines: int = 3,
        start_line: int = 0,
        max_lines: int = 300,
    ) -> dict:
        """Return a bounded, read-only source-workspace change view.

        Providers may implement this wherever the workspace physically lives
        (container volume, VM disk, remote worker). The API supplies only paths
        discovered from provider outputs; callers cannot choose an arbitrary
        host path. Implementations must disable repository-controlled diff
        drivers/hooks and bound output before returning it.
        """
        raise NotImplementedError(
            f"the {self.name!r} provider does not support workspace diffs yet"
        )

    def workspace_untracked_file(
        self, instance_id: str, node: str, source_path: str, path: str
    ) -> bytes:
        """Return one explicitly selected, bounded untracked regular file.

        This is intentionally separate from ``workspace_diff``: merely listing
        changes must never follow an untracked symlink or open its contents.
        Providers must verify that the selected path is currently untracked and
        a regular file before returning bytes.
        """
        raise NotImplementedError(
            f"the {self.name!r} provider does not support untracked evidence yet"
        )

    def write_transfer_file(
        self, instance_id: str, node: str, path: str, content: bytes
    ) -> dict:
        """Write one bounded file below the provider-owned foothold transfer root."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support file upload yet"
        )

    def read_transfer_file(
        self, instance_id: str, node: str, path: str
    ) -> bytes:
        """Read one bounded regular file below the foothold transfer root."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support file download yet"
        )

    def browser_visit(
        self,
        instance_id: str,
        node: str,
        target_ip: str,
        port: int,
        scheme: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        wait_ms: int = 1500,
        execution_marker: str | None = None,
    ) -> dict:
        """Render one arena-bound target page in a disposable browser.

        The control plane derives ``target_ip``/``port`` from provider outputs;
        callers never supply an arbitrary URL. Providers must attach the runner
        only to the selected target's arena network and bound time/resources and
        returned content.
        """
        raise NotImplementedError(
            f"the {self.name!r} provider does not support headless browsing yet"
        )

    def http_request(
        self,
        instance_id: str,
        node: str,
        target_ip: str,
        port: int,
        scheme: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict:
        """Perform one arena-target HTTP transaction with a disposable runner.

        The control plane derives ``target_ip``/``port`` from provider outputs;
        callers supply only a node plus a relative path — never an arbitrary
        URL. Providers must attach the runner only to the selected target's
        arena network, never follow redirects off the resolved target, bound
        time and returned content, and report the whole-body digest. A non-2xx
        status is still a successful observation: ``success`` reports transport
        failure, not an HTTP verdict.
        Result contract:
            {"success": True, "status": int, "headers": {...}, "body": str,
             "body_bytes": int, "body_sha256": "sha256:...", "truncated": bool,
             "redirect_location": str | None, ...}
          | {"success": False, "error": "..."}
        """
        raise NotImplementedError(
            f"the {self.name!r} provider does not support arena HTTP requests yet"
        )

    def run_poc(
        self, instance_id: str, job_id: str, payload: dict,
        target_policy: dict | None, limits: dict, cancel_check=None,
    ) -> dict:
        """Run one disposable, confined PoC helper owned by a worker.

        Providers must return process outcome separately from cleanup outcome.
        The default is deliberately unsupported: no cloud/VM backend may claim
        Docker-local confinement by falling through to a generic shell.
        """
        raise NotImplementedError(
            f"the {self.name!r} provider does not support confined PoC execution"
        )

    def cleanup_poc_job(self, job_id: str) -> dict:
        """Reclaim a stale/interrupted provider-owned PoC helper by stable label."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support PoC cleanup"
        )

    def observe_lifecycle(self, instance_id: str) -> dict:
        """Return stable runtime identities for reset equivalence."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support lifecycle observation"
        )

    def check_readiness(self, instance_id: str, outputs: dict, policy: dict) -> dict:
        """Execute a bounded, arena-scoped application readiness observation."""
        raise NotImplementedError(
            f"the {self.name!r} provider does not support application readiness"
        )
