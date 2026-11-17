"""FR-05 (B8): arena target containers are bounded.

Asserts the `containers.run` kwargs for every node: default memory/PID/CPU limits,
per-node overrides clamped to the server ceiling, and `no-new-privileges` with an
explicit, recorded per-node opt-out. Live gates (the seven fixtures, a contained
fork bomb) are operator actions.
"""
import config
from providers.docker_local import LABEL_NODE, DockerLocalProvider, node_limits
from scenario_spec import ScenarioSpec
from tests.test_docker_provider import _FakeClient

SCENARIO = {
    "requires": {"provider_class": "container", "egress": "open"},
    "nodes": [
        {"name": "victim", "role": "victim", "image": "vulnerables/web-dvwa:latest"},
        {"name": "heavy", "role": "victim", "image": "elasticsearch:7",
         "resources": {"memory_mb": 999_999, "pids": 64, "cpu_millis": 99_000}},
        {"name": "suid", "role": "victim", "image": "alpine:3", "allow_new_privileges": True},
        {"name": "attacker", "role": "attacker", "image": "kalilinux/kali-rolling:latest",
         "entrypoint": True},
    ],
}


def _deploy():
    client = _FakeClient()
    result = DockerLocalProvider(client=client).deploy(SCENARIO, "fr05abcd-lab")
    assert result["success"] is True, result
    kwargs = {kw["labels"][LABEL_NODE]: kw for kw in client.containers.run_kwargs
              if kw.get("labels", {}).get(LABEL_NODE)}
    return result["outputs"], kwargs


def test_every_node_gets_default_limits_and_no_new_privileges():
    _, kwargs = _deploy()
    for name in ("victim", "attacker"):
        kw = kwargs[name]
        assert kw["mem_limit"] == f"{config.ARENA_NODE_DEFAULT_MEMORY_MB}m"
        assert kw["memswap_limit"] == kw["mem_limit"]
        assert kw["pids_limit"] == config.ARENA_NODE_DEFAULT_PIDS
        assert kw["nano_cpus"] == config.ARENA_NODE_DEFAULT_CPU_MILLIS * 1_000_000
        assert kw["security_opt"] == ["no-new-privileges:true"]
        assert "cap_drop" not in kw and not kw.get("privileged")


def test_override_is_clamped_to_the_server_ceiling():
    _, kwargs = _deploy()
    kw = kwargs["heavy"]
    assert kw["mem_limit"] == f"{config.ARENA_NODE_MAX_MEMORY_MB}m"
    assert kw["pids_limit"] == 64  # below the ceiling: honoured
    assert kw["nano_cpus"] == config.ARENA_NODE_MAX_CPU_MILLIS * 1_000_000


def test_no_new_privileges_opt_out_is_explicit_and_recorded():
    outputs, kwargs = _deploy()
    assert "security_opt" not in kwargs["suid"]
    assert kwargs["suid"]["pids_limit"] == config.ARENA_NODE_DEFAULT_PIDS
    assert outputs["node_suid_limits"].endswith("no_new_privileges=false (opt-out)")
    assert outputs["node_victim_limits"].endswith("no_new_privileges=true")


def test_spec_accepts_resources_and_rejects_unknown_resource_keys():
    spec = ScenarioSpec.model_validate({"id": "fr05", "name": "fr05", **SCENARIO})
    heavy = next(n for n in spec.nodes if n.name == "heavy")
    assert heavy.resources.pids == 64
    bad = {**SCENARIO, "nodes": [{"name": "x", "image": "alpine", "resources": {"gpus": 1}}]}
    try:
        ScenarioSpec.model_validate({"id": "fr05", "name": "fr05", **bad})
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unknown resource key accepted")


def test_legacy_nodes_without_resources_get_defaults():
    limits = node_limits({"name": "legacy"})
    assert limits == {"memory_mb": config.ARENA_NODE_DEFAULT_MEMORY_MB,
                      "pids": config.ARENA_NODE_DEFAULT_PIDS,
                      "cpu_millis": config.ARENA_NODE_DEFAULT_CPU_MILLIS,
                      "no_new_privileges": True}
