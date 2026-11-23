"""
Issue #20: live acceptance gates must not touch production's images.

The production worker runs PoC jobs with ``nidavellir/poc-runner:py311``
(``NIDAVELLIR_POC_RUNNER_IMAGE``). An acceptance stack that built that tag would
silently swap production's runner whenever a gate ran on the production host, and
under the containerd image store the previous image cannot be recovered by ID.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_RUNNER = "nidavellir/poc-runner:py311"


class _ComposeLoader(yaml.SafeLoader):
    """Safe YAML that passes Compose's merge tags (!override, !reset) through."""


for _tag in ("!override", "!reset"):
    _ComposeLoader.add_constructor(
        _tag, lambda loader, node: (loader.construct_sequence(node)
                                    if isinstance(node, yaml.SequenceNode)
                                    else loader.construct_mapping(node)
                                    if isinstance(node, yaml.MappingNode)
                                    else loader.construct_scalar(node)))


def _stack(path):
    return yaml.load(path.read_text(), Loader=_ComposeLoader) or {}  # nosec B506


def test_no_acceptance_stack_builds_or_uses_the_production_runner_tag():
    for path in sorted((ROOT / "compose" / "acceptance").glob("*.yml")):
        assert PRODUCTION_RUNNER not in path.read_text(), path.name


def test_acceptance_runner_service_and_worker_agree():
    for path in sorted((ROOT / "compose" / "acceptance").glob("*.yml")):
        services = _stack(path).get("services") or {}
        runner = services.get("poc-runner-image")
        if not runner:
            continue
        env = (services.get("worker") or {}).get("environment") or {}
        assert env.get("NIDAVELLIR_POC_RUNNER_IMAGE") == runner["image"], path.name


def test_live_verifiers_do_not_inspect_the_production_runner():
    for path in sorted((ROOT / "scripts").glob("verify-*-live.py")):
        assert PRODUCTION_RUNNER not in path.read_text(), path.name


BASE_STACKS = ("nv02", "nv03", "nv04", "nv05", "nv06")


def test_base_stacks_mount_what_startup_validation_requires():
    # The API refuses to start without its Terraform template directory; every
    # live gate starts from one of these base stacks.
    for name in BASE_STACKS:
        services = _stack(ROOT / "compose" / "acceptance" / f"{name}.yml")["services"]
        for service in ("orchestrator", "worker"):
            volumes = services[service].get("volumes") or []
            assert "./cyber-range/infra/terraform:/app/terraform:ro" in volumes, (name, service)
