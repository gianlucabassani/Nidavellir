"""
Provider registry (ADR-0003).

Selection precedence:
1. MOCK_MODE=true         -> "mock"  (hard global override)
2. explicit `name` argument
3. RANGE_PROVIDER env var
4. default                -> "openstack"

MOCK_MODE=true is a master switch: it forces the in-memory mock provider for
EVERY resolution, ignoring both an explicit ``name`` and RANGE_PROVIDER, so a
no-infra demo run never provisions real containers/VMs — no matter what a
request (or the compose default ``RANGE_PROVIDER=docker-local``) asks for.
Leave MOCK_MODE unset/false to run the real backends, where the precedence is
explicit name > RANGE_PROVIDER > openstack.
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


def _mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "false").lower() == "true"


def resolve_provider_name(name: str | None = None) -> str:
    """Resolve the effective provider name with the precedence documented at the
    top of this module. ``MOCK_MODE=true`` wins over everything (an explicit
    ``name`` and ``RANGE_PROVIDER``) so the no-infra path is a single dependable
    switch; otherwise an explicit ``name`` wins, then ``RANGE_PROVIDER``, then
    the openstack default."""
    if _mock_mode():
        return MockProvider.name
    if name is not None:
        return name
    return os.getenv("RANGE_PROVIDER") or OpenStackProvider.name


def default_provider_name() -> str:
    """The provider name `get_provider(None)` resolves to, without instantiating
    a driver. Lets callers (API/UI) reason about the active default."""
    return resolve_provider_name(None)


def get_provider(name: str | None = None) -> RangeProvider:
    resolved = resolve_provider_name(name)
    try:
        return _REGISTRY[resolved]()
    except KeyError:
        raise ValueError(
            f"Unknown provider {resolved!r} (available: {available_providers()})"
        ) from None
