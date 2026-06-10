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
    def __init__(self, provider=None):
        # Injectable for tests; otherwise resolved from RANGE_PROVIDER /
        # MOCK_MODE (see providers.get_provider).
        self.provider = provider or get_provider()

    def deploy(self, scenario_name: str, instance_id: str, user_vars: dict = None):
        logger.info(
            f"[{instance_id}] Starting deployment of scenario '{scenario_name}' "
            f"(provider: {self.provider.name})"
        )
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

    def _load_scenario(self, scenario_name: str) -> dict:
        """Load scenario YAML configuration (delegates to the registry)."""
        return load_scenario(scenario_name)
