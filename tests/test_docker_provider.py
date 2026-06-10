"""
Tests for the docker-local provider (backlog P1-3 / P1-4).

Unit tests drive the provider with a fake Docker client (no daemon needed);
the integration test at the bottom runs a real container lab end-to-end and
is what CI uses to prove the provider against an actual Docker daemon.
"""
import pytest

from providers.docker_local import (
    LABEL_LAB_ID,
    LABEL_ROLE,
    DockerLocalProvider,
)

# --- fake docker client -------------------------------------------------------


class _FakeContainer:
    def __init__(self, name, labels, network, ports=None):
        self.name = name
        self.labels = labels
        self.removed = False
        bindings = {}
        if ports:
            for i, port in enumerate(ports):
                bindings[port] = [{"HostIp": "0.0.0.0", "HostPort": str(49000 + i)}]
        self.attrs = {
            "NetworkSettings": {
                "Networks": {network: {"IPAddress": "172.99.0.10"}},
                "Ports": bindings,
            }
        }

    def reload(self):
        pass

    def remove(self, force=False):
        self.removed = True


class _FakeNetwork:
    def __init__(self, name, labels):
        self.name = name
        self.labels = labels
        self.removed = False

    def remove(self):
        self.removed = True


class _FakeContainers:
    def __init__(self):
        self.created = []
        self.run_kwargs = []

    def run(self, **kwargs):
        self.run_kwargs.append(kwargs)
        container = _FakeContainer(
            kwargs["name"],
            kwargs["labels"],
            kwargs["network"],
            list((kwargs.get("ports") or {}).keys()),
        )
        self.created.append(container)
        return container

    def list(self, all=False, filters=None):
        label = filters["label"]
        return [
            c for c in self.created
            if not c.removed and f"{LABEL_LAB_ID}={c.labels.get(LABEL_LAB_ID)}" == label
        ]


class _FakeNetworks:
    def __init__(self):
        self.created = []

    def create(self, name, driver=None, labels=None):
        network = _FakeNetwork(name, labels or {})
        self.created.append(network)
        return network

    def list(self, filters=None):
        label = filters["label"]
        return [
            n for n in self.created
            if not n.removed and f"{LABEL_LAB_ID}={n.labels.get(LABEL_LAB_ID)}" == label
        ]


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()
        self.networks = _FakeNetworks()


CONTAINER_SCENARIO = {
    "requires": {"provider_class": "container"},
    "vms": [
        {"name": "victim", "role": "victim", "image": "vulnerables/web-dvwa:latest", "ports": [80]},
        {"name": "attacker", "role": "attacker", "image": "kalilinux/kali-rolling:latest"},
        {"name": "soc", "role": "monitor", "image": "wazuh:whatever"},
    ],
}


# --- unit tests ----------------------------------------------------------------


def test_rejects_vm_class_scenarios():
    provider = DockerLocalProvider(client=_FakeClient())
    result = provider.deploy({"requires": {"provider_class": "vm"}}, "lab-1")
    assert result["success"] is False
    assert "container" in result["error"]


def test_deploy_creates_labeled_network_and_containers():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)

    result = provider.deploy(CONTAINER_SCENARIO, "abcd1234-rest-of-uuid")

    assert result["success"] is True
    # One isolated network, labeled with the full lab id
    (network,) = client.networks.created
    assert network.name == "cyberguard-abcd1234"
    assert network.labels[LABEL_LAB_ID] == "abcd1234-rest-of-uuid"
    # Monitor node skipped -> exactly victim + attacker
    roles = {kw["labels"][LABEL_ROLE] for kw in client.containers.run_kwargs}
    assert roles == {"victim", "attacker"}
    # Attacker kept alive with the default command
    attacker_kw = next(
        kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_ROLE] == "attacker"
    )
    assert attacker_kw["command"] == "sleep infinity"


def test_outputs_render_for_the_dashboard():
    provider = DockerLocalProvider(client=_FakeClient())
    outputs = provider.deploy(CONTAINER_SCENARIO, "abcd1234")["outputs"]

    assert outputs["provider"] == "docker-local"
    assert outputs["victim_vm_private_ip"] == "172.99.0.10"
    assert outputs["attack_vm_private_ip"] == "172.99.0.10"
    assert outputs["attack_vm_ssh_command"] == "docker exec -it cg-abcd1234-attacker /bin/bash"
    # Published victim port becomes a host-reachable URL
    assert outputs["victim_web_url"].startswith("http://127.0.0.1:")
    assert outputs["victim_vm_floating_ip"].startswith("127.0.0.1:")


def test_destroy_removes_everything_and_is_idempotent():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    provider.deploy(CONTAINER_SCENARIO, "abcd1234")

    assert provider.destroy("abcd1234") == {"success": True}
    assert all(c.removed for c in client.containers.created)
    assert all(n.removed for n in client.networks.created)

    # Second destroy finds nothing — still success.
    assert provider.destroy("abcd1234") == {"success": True}


def test_failed_deploy_rolls_back(monkeypatch):
    client = _FakeClient()

    def explode(**kwargs):
        if kwargs["labels"][LABEL_ROLE] == "attacker":
            raise RuntimeError("image pull failed")
        return _FakeContainers.run(client.containers, **kwargs)

    monkeypatch.setattr(client.containers, "run", explode)
    provider = DockerLocalProvider(client=client)

    result = provider.deploy(CONTAINER_SCENARIO, "abcd1234")

    assert result["success"] is False
    assert "image pull failed" in result["error"]
    # The half-created lab must have been torn down.
    assert all(c.removed for c in client.containers.created)
    assert all(n.removed for n in client.networks.created)


# --- real-docker integration (the P1-4 e2e; runs in CI) -------------------------


def _docker_available():
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="no Docker daemon available")
def test_real_container_lab_lifecycle():
    """deploy -> inspect -> destroy with real containers (tiny alpine images)."""
    import docker

    scenario = {
        "requires": {"provider_class": "container"},
        "vms": [
            {"name": "victim", "role": "victim", "image": "alpine:3.20",
             "command": "sleep 60"},
            {"name": "attacker", "role": "attacker", "image": "alpine:3.20"},
        ],
    }
    provider = DockerLocalProvider()
    instance_id = "itest-docker-lab"

    try:
        result = provider.deploy(scenario, instance_id)
        assert result["success"] is True, result.get("error")

        outputs = result["outputs"]
        assert outputs["victim_vm_private_ip"], "victim must get a lab-network IP"
        assert outputs["attack_vm_private_ip"], "attacker must get a lab-network IP"

        # Both containers actually running, on a dedicated labeled network
        client = docker.from_env()
        labs = client.containers.list(
            filters={"label": f"{LABEL_LAB_ID}={instance_id}"}
        )
        assert {c.labels[LABEL_ROLE] for c in labs} == {"victim", "attacker"}

        # Containment sanity: the lab network is dedicated to this lab
        (network,) = client.networks.list(
            filters={"label": f"{LABEL_LAB_ID}={instance_id}"}
        )
        assert network.name == outputs["lab_network"]
    finally:
        assert provider.destroy(instance_id)["success"] is True

    # Nothing left behind
    client = docker.from_env()
    assert client.containers.list(
        all=True, filters={"label": f"{LABEL_LAB_ID}={instance_id}"}
    ) == []
    assert client.networks.list(
        filters={"label": f"{LABEL_LAB_ID}={instance_id}"}
    ) == []
