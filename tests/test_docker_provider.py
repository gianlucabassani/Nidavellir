"""
Tests for the docker-local provider (backlog P1-3 / P1-4).

Unit tests drive the provider with a fake Docker client (no daemon needed);
the integration test at the bottom runs a real container lab end-to-end and
is what CI uses to prove the provider against an actual Docker daemon.
"""
import pytest

from providers.docker_local import (
    LABEL_LAB_ID,
    LABEL_NODE,
    LABEL_ROLE,
    DockerLocalProvider,
)

# --- fake docker client -------------------------------------------------------


class _FakeContainer:
    def __init__(self, name, labels, network, ports=None, state="running"):
        self.name = name
        self.labels = labels
        self.removed = False
        bindings = {}
        if ports:
            for i, port in enumerate(ports):
                bindings[port] = [{"HostIp": "0.0.0.0", "HostPort": str(49000 + i)}]
        self.attrs = {
            "State": {"Status": state, "ExitCode": 0 if state == "running" else 1},
            "NetworkSettings": {
                "Networks": {network: {"IPAddress": "172.99.0.10"}},
                "Ports": bindings,
            },
        }

    def reload(self):
        pass

    def logs(self, tail=20):
        return b"boom: exited\n"

    def remove(self, force=False):
        self.removed = True


class _FakeNetwork:
    def __init__(self, name, labels, internal=False, options=None):
        self.name = name
        self.labels = labels
        self.internal = internal
        self.options = options or {}
        self.removed = False
        self.connected = []

    def connect(self, container):
        # Mirror docker SDK: attaching a running container adds an interface
        # (and an IP) on this network.
        self.connected.append(container)
        container.attrs["NetworkSettings"]["Networks"][self.name] = {
            "IPAddress": "172.99.7.7"
        }

    def remove(self):
        self.removed = True


class _FakeContainers:
    def __init__(self, exit_nodes=None):
        self.created = []
        self.run_kwargs = []
        # node names whose container should report 'exited' right after start
        self.exit_nodes = set(exit_nodes or ())

    def run(self, **kwargs):
        self.run_kwargs.append(kwargs)
        node = kwargs["labels"].get(LABEL_NODE)
        container = _FakeContainer(
            kwargs["name"],
            kwargs["labels"],
            kwargs["network"],
            list((kwargs.get("ports") or {}).keys()),
            state="exited" if node in self.exit_nodes else "running",
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

    def create(self, name, driver=None, labels=None, internal=False, options=None):
        network = _FakeNetwork(name, labels or {}, internal=internal, options=options)
        self.created.append(network)
        return network

    def list(self, filters=None):
        label = filters["label"]
        return [
            n for n in self.created
            if not n.removed and f"{LABEL_LAB_ID}={n.labels.get(LABEL_LAB_ID)}" == label
        ]


class _FakeClient:
    def __init__(self, exit_nodes=None):
        self.containers = _FakeContainers(exit_nodes=exit_nodes)
        self.networks = _FakeNetworks()


CONTAINER_SCENARIO = {
    # egress: open -> exercise the un-contained path (one bridge, publish on it);
    # lockdown (the default) has its own dedicated tests below.
    "requires": {"provider_class": "container", "egress": "open"},
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


# --- v3 multi-segment topology (P1-2) ------------------------------------------


MULTI_SEGMENT = {
    "requires": {"provider_class": "container", "egress": "open"},
    "network": {"segments": [{"name": "dmz"}, {"name": "corp"}]},
    "nodes": [
        {"name": "web", "role": "victim", "image": "dvwa", "segments": ["dmz"], "ports": [80]},
        {"name": "db", "role": "victim", "image": "postgres", "segments": ["corp"]},
        {"name": "jump", "role": "attacker", "image": "kali",
         "segments": ["dmz", "corp"], "entrypoint": True},
    ],
}


def test_multi_segment_creates_one_network_per_segment_and_straddles():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)

    result = provider.deploy(MULTI_SEGMENT, "multiseg1-uuid")
    assert result["success"] is True

    # One bridge per declared segment (short id "multiseg").
    names = {n.name for n in client.networks.created}
    assert names == {"cyberguard-multiseg-corp", "cyberguard-multiseg-dmz"}

    # The straddling foothold is attached to both of its segments.
    jump = next(c for c in client.containers.created if c.name.endswith("-jump"))
    assert set(jump.attrs["NetworkSettings"]["Networks"]) >= {
        "cyberguard-multiseg-dmz", "cyberguard-multiseg-corp"
    }

    # Containers are keyed/labeled by unique node name (not role).
    node_labels = {kw["labels"][LABEL_NODE] for kw in client.containers.run_kwargs}
    assert node_labels == {"web", "db", "jump"}
    # default-first then alpha → corp, dmz; the primary is the first.
    assert result["outputs"]["lab_networks"] == [
        "cyberguard-multiseg-corp", "cyberguard-multiseg-dmz"
    ]
    assert result["outputs"]["lab_network"] == "cyberguard-multiseg-corp"


def test_repeated_roles_get_per_node_outputs_without_collision():
    provider = DockerLocalProvider(client=_FakeClient())
    outputs = provider.deploy(MULTI_SEGMENT, "multiseg2")["outputs"]

    # Both victims are addressable per-node (no overwrite).
    assert outputs["node_web_private_ip"]
    assert outputs["node_db_private_ip"]
    assert outputs["node_jump_private_ip"]
    # The legacy role key resolves to the FIRST victim only.
    assert outputs["victim_vm_name"] == outputs["node_web_name"]
    # The foothold exposes an exec command per-node and on the legacy key.
    assert outputs["node_jump_ssh_command"].startswith("docker exec -it ")
    assert "attack_vm_ssh_command" in outputs
    # A published port surfaces as a per-node URL.
    assert outputs["node_web_url"].startswith("http://127.0.0.1:")


def test_entrypoint_non_attacker_node_gets_keepalive_and_ssh():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [
            {"name": "ops", "role": "jumpbox", "image": "ubuntu",
             "segments": ["lab"], "entrypoint": True},
        ],
    }
    outputs = provider.deploy(scenario, "entry1")["outputs"]

    (kw,) = client.containers.run_kwargs
    assert kw["command"] == "sleep infinity"  # an entrypoint node is kept alive
    assert outputs["node_ops_ssh_command"].startswith("docker exec -it ")
    # non-canonical role → no legacy role-prefixed keys, per-node only
    assert "attack_vm_ssh_command" not in outputs


def test_exited_node_is_surfaced_not_silently_successful():
    # The #1 docker-local gotcha: a target with no foreground service exits the
    # instant it starts. The deploy still 'succeeds', but the dead node must be
    # visible (state + unhealthy_nodes), not silently reported as fine.
    client = _FakeClient(exit_nodes={"web"})
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container"},
        "nodes": [
            {"name": "web", "role": "victim", "image": "alpine"},
            {"name": "jump", "role": "attacker", "image": "alpine"},
        ],
    }
    outputs = provider.deploy(scenario, "exit-test")["outputs"]
    assert outputs["node_web_state"] == "exited"
    assert outputs["node_jump_state"] == "running"
    assert outputs["unhealthy_nodes"] == ["web"]


# --- egress containment (P2-3), default-ON ------------------------------------


LOCKED_SCENARIO = {
    "requires": {"provider_class": "container"},  # egress defaults to locked
    "network": {"segments": [{"name": "lab"}]},
    "nodes": [
        {"name": "web", "role": "victim", "image": "dvwa", "segments": ["lab"], "ports": [80]},
        {"name": "kali", "role": "attacker", "image": "kali", "segments": ["lab"],
         "entrypoint": True},
    ],
}


def test_locked_arena_uses_internal_nets_and_a_no_masquerade_ingress():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)

    outputs = provider.deploy(LOCKED_SCENARIO, "lockaaaa-uuid")["outputs"]
    assert outputs["egress"] == "blocked"

    by_name = {n.name: n for n in client.networks.created}
    seg = by_name["cyberguard-lockaaaa-lab"]
    assert seg.internal is True  # hard egress block (no route to the internet)
    ingress = by_name["cyberguard-lockaaaa-ingress"]
    assert ingress.internal is False
    assert ingress.options.get("com.docker.network.bridge.enable_ip_masquerade") == "false"

    # The web node (publishes a port) runs PRIMARY on the ingress bridge so the
    # operator's browser can reach it; publishing dies on an `internal` net.
    web_kw = next(kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "web")
    assert web_kw["network"] == "cyberguard-lockaaaa-ingress"
    assert web_kw.get("ports")  # the published port rides the ingress net
    # The foothold (no ports) stays on the internal segment only — no ingress.
    kali_kw = next(kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "kali")
    assert kali_kw["network"] == "cyberguard-lockaaaa-lab"
    # The published web node still surfaces a host URL for the browser.
    assert outputs["node_web_url"].startswith("http://127.0.0.1:")


def test_locked_arena_without_published_ports_has_no_ingress_net():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container"},
        "nodes": [{"name": "box", "role": "attacker", "image": "alpine", "entrypoint": True}],
    }
    outputs = provider.deploy(scenario, "nolisten-uuid")["outputs"]
    assert outputs["egress"] == "blocked"
    assert all(n.internal for n in client.networks.created)  # only internal segment net(s)
    assert not any(n.name.endswith("-ingress") for n in client.networks.created)


def test_open_arena_keeps_egress_and_creates_no_ingress():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [{"name": "web", "role": "victim", "image": "dvwa", "ports": [80]}],
    }
    outputs = provider.deploy(scenario, "openaaaa")["outputs"]
    assert outputs["egress"] == "open"
    assert all(n.internal is False for n in client.networks.created)
    assert not any(n.name.endswith("-ingress") for n in client.networks.created)


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

        # Attacker-stance exec works against a real container.
        exec_res = provider.exec_in_node(instance_id, "attacker", "echo cyberguard-ok")
        assert exec_res["success"] is True, exec_res.get("error")
        assert exec_res["exit_code"] == 0
        assert "cyberguard-ok" in exec_res["stdout"]
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


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="no Docker daemon available")
def test_locked_arena_blocks_egress_real_docker():
    """Containment proof (P2-3): a node in a default-locked arena cannot reach
    an external canary. This is the guarantee before any untrusted agent runs."""
    scenario = {
        "requires": {"provider_class": "container"},  # locked by default
        "nodes": [{"name": "box", "role": "attacker", "image": "alpine:3.20",
                   "entrypoint": True}],
    }
    provider = DockerLocalProvider()
    iid = "itest-containment"
    try:
        assert provider.deploy(scenario, iid)["success"] is True
        # Reach for a public IP from inside the arena -> must NOT connect.
        res = provider.exec_in_node(
            iid, "box",
            "wget -q -T5 -O- http://1.1.1.1 && echo REACHED || echo BLOCKED",
            timeout=15,
        )
        assert res["success"] is True, res.get("error")
        assert "BLOCKED" in res["stdout"]
        assert "REACHED" not in res["stdout"]
    finally:
        assert provider.destroy(iid)["success"] is True
