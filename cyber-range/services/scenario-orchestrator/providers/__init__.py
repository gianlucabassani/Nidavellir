"""
Provider registry (ADR-0003).

Selection precedence:
1. explicit `name` argument
2. RANGE_PROVIDER env var
3. legacy MOCK_MODE=true  -> "mock"
4. default                -> "openstack"
"""
import os

from providers.aws import AWSProvider
from providers.base import RangeProvider
from providers.docker_local import DockerLocalProvider
from providers.mock import MockProvider
from providers.openstack import OpenStackProvider

_REGISTRY: dict[str, type[RangeProvider]] = {
    MockProvider.name: MockProvider,
    OpenStackProvider.name: OpenStackProvider,
    DockerLocalProvider.name: DockerLocalProvider,
    AWSProvider.name: AWSProvider,
}


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def infra_class_of(name: str) -> str:
    """The infrastructure class ("vm" | "container" | "any") a provider serves."""
    return _REGISTRY[name].infra_class


def get_provider(name: str | None = None) -> RangeProvider:
    if name is None:
        name = os.getenv("RANGE_PROVIDER")
    if name is None:
        mock = os.getenv("MOCK_MODE", "false").lower() == "true"
        name = "mock" if mock else "openstack"
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown provider {name!r} (available: {available_providers()})"
        ) from None
