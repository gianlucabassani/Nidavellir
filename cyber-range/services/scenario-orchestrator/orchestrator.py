"""
Orchestrator: thin dispatcher between the task layer and the deployment
providers (ADR-0003).

Responsibilities: load + validate the scenario config, pick the provider,
delegate. Everything backend-specific (OpenTofu workspaces, mock outputs,
future docker/aws drivers) lives in `providers/`.
"""
import logging

from providers import get_provider
from scenarios import load_scenario

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, provider=None, provider_name=None):
        # Provider instance injectable for tests; a name (e.g. the one
        # recorded on the deployment) resolves through the registry; otherwise
        # RANGE_PROVIDER decides. MOCK_MODE=true is a hard override that forces
        # the mock provider regardless of name/RANGE_PROVIDER (get_provider).
        self.provider = provider or get_provider(provider_name)

    def deploy(self, scenario_name: str, instance_id: str, user_vars: dict = None,
               scenario_config: dict = None):
        logger.info(
            f"[{instance_id}] Starting deployment of scenario '{scenario_name}' "
            f"(provider: {self.provider.name})"
        )
        # An inline scenario_config (a custom/generated topology) is used as-is;
        # otherwise the named scenario is loaded from the registry.
        if scenario_config is None:
            scenario_config = self._load_scenario(scenario_name)
        if scenario_config is None:
            return {
                "success": False,
                "error": f"Scenario '{scenario_name}' not found"
            }
        return self.provider.deploy(scenario_config, instance_id, user_vars)

    def destroy(self, instance_id: str):
        logger.info(f"[{instance_id}] Destroy requested (provider: {self.provider.name})")
        return self.provider.destroy(instance_id)

    def exec_in_node(self, instance_id: str, node: str, command: str, timeout: int = 30):
        """Run a command inside an arena node (MCP attacker stance). Delegates
        to the provider, which must run on the SAME backend the arena was
        deployed with (recorded on the deployment)."""
        logger.info(
            f"[{instance_id}] exec on node {node!r} (provider: {self.provider.name})"
        )
        return self.provider.exec_in_node(instance_id, node, command, timeout)

    def set_node_egress(self, instance_id: str, node: str, open: bool):
        """Open/close a victim node's setup-time egress (configurator capability,
        ADR-0007). Delegates to the provider the arena was deployed with."""
        logger.info(
            f"[{instance_id}] setup egress {'open' if open else 'close'} on node "
            f"{node!r} (provider: {self.provider.name})"
        )
        return self.provider.set_node_egress(instance_id, node, open)

    def capture_traffic(self, instance_id: str, seconds: int = 6, max_packets: int = 200):
        """Observe in-flight traffic on the arena's shared segment (MCP MITM
        stance). Delegates to the provider the arena was deployed with."""
        logger.info(
            f"[{instance_id}] MITM capture ({seconds}s/{max_packets}p) "
            f"(provider: {self.provider.name})"
        )
        return self.provider.capture_traffic(
            instance_id, seconds=seconds, max_packets=max_packets
        )

    def collect_monitor_signals(self, instance_id: str):
        """Gather the service-under-test nodes' runtime state + log tails for the
        M2 monitor. Delegates to the provider the arena was deployed with."""
        return self.provider.collect_monitor_signals(instance_id)

    def _load_scenario(self, scenario_name: str) -> dict:
        """Load scenario YAML configuration (delegates to the registry)."""
        return load_scenario(scenario_name)
