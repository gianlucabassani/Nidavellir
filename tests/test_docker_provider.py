"""
Tests for the docker-local provider (backlog P1-3 / P1-4).

Unit tests drive the provider with a fake Docker client (no daemon needed);
the integration test at the bottom runs a real container lab end-to-end and
is what CI uses to prove the provider against an actual Docker daemon.
"""
import config
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

    def exec_run(self, cmd, **kwargs):
        self.exec_calls = getattr(self, "exec_calls", [])
        self.exec_calls.append(cmd)
        return (0, b"")

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

    def connect(self, container, aliases=None):
        # Mirror docker SDK: attaching a running container adds an interface
        # (and an IP) on this network. `aliases` registers DNS names (used by
        # the package mirror, reachable as `mirror` on each arena segment).
        self.connected.append(container)
        self.aliases = getattr(self, "aliases", {})
        self.aliases[container.name] = list(aliases or [])
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
        # The git-clone helper runs un-named on the default bridge (no `name`/
        # `network`), so tolerate their absence.
        node = kwargs.get("labels", {}).get(LABEL_NODE)
        container = _FakeContainer(
            kwargs.get("name", "auto"),
            kwargs.get("labels", {}),
            kwargs.get("network"),
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


class _FakeImage:
    def __init__(self, tag=None, labels=None, attrs=None):
        self.tags = [tag] if tag else []
        self.id = tag or "sha256:fake"
        self.labels = labels or {}
        # Default config mimics a legacy 'VM-in-a-container' image: a startup that
        # daemonizes then returns (ends in interactive bash). The keepalive wrap
        # re-runs this and then blocks.
        self.attrs = attrs or {
            "Config": {"Entrypoint": None, "Cmd": ["sh", "-c", "/bin/services.sh && bash"]}
        }


class _FakeImages:
    def __init__(self, present=True):
        self.present = present  # whether the mirror image already exists
        self.built = []
        self._images = []       # _FakeImage objects, for list()/remove()
        self.removed = []

    def get(self, name):
        if self.present:
            return _FakeImage(tag=name)
        raise RuntimeError(f"image {name} not found")

    def build(self, **kwargs):
        self.built.append(kwargs)
        image = _FakeImage(tag=kwargs.get("tag"), labels=kwargs.get("labels"))
        self._images.append(image)
        return (image, [])

    def list(self, filters=None):
        if not filters:
            return list(self._images)
        key, _, val = filters["label"].partition("=")
        return [i for i in self._images if i.labels.get(key) == val]

    def remove(self, image_id, force=False):
        self.removed.append(image_id)
        self._images = [i for i in self._images if i.id != image_id]


class _FakeVolume:
    def __init__(self, name, labels):
        self.name = name
        self.labels = labels or {}
        self.removed = False

    def remove(self, force=False):
        self.removed = True


class _FakeVolumes:
    def __init__(self):
        self.created = []

    def create(self, name=None, labels=None):
        volume = _FakeVolume(name, labels or {})
        self.created.append(volume)
        return volume

    def list(self, filters=None):
        if not filters:
            return [v for v in self.created if not v.removed]
        key, _, val = filters["label"].partition("=")
        return [v for v in self.created if not v.removed and v.labels.get(key) == val]


class _FakeClient:
    def __init__(self, exit_nodes=None, mirror_image_present=True):
        self.containers = _FakeContainers(exit_nodes=exit_nodes)
        self.networks = _FakeNetworks()
        self.images = _FakeImages(present=mirror_image_present)
        self.volumes = _FakeVolumes()


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
    assert network.name == "nidavellir-abcd1234"
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
    assert outputs["attack_vm_ssh_command"] == "docker exec -it nv-abcd1234-attacker /bin/bash"
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


def test_image_not_found_is_classified_with_phase(monkeypatch):
    """A missing image gets a clear, classified error (not an opaque str) plus the
    deploy phase — the Field-B observability fix."""
    import docker

    client = _FakeClient()

    def explode(**kwargs):
        raise docker.errors.ImageNotFound("no such image: ghost/img:latest")

    monkeypatch.setattr(client.containers, "run", explode)
    result = DockerLocalProvider(client=client).deploy(CONTAINER_SCENARIO, "abcd1234")

    assert result["success"] is False
    assert result["error_kind"] == "image_not_found"
    assert result["phase"] == "start node containers"
    assert "not found on the registry" in result["error"]
    assert all(n.removed for n in client.networks.created)  # rolled back


def test_generic_deploy_failure_carries_phase_and_kind(monkeypatch):
    client = _FakeClient()

    def explode(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(client.containers, "run", explode)
    result = DockerLocalProvider(client=client).deploy(CONTAINER_SCENARIO, "abcd1234")

    assert result["success"] is False
    assert result["error_kind"] == "RuntimeError"
    assert result["phase"] == "start node containers"


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
    assert names == {"nidavellir-multiseg-corp", "nidavellir-multiseg-dmz"}

    # The straddling foothold is attached to both of its segments.
    jump = next(c for c in client.containers.created if c.name.endswith("-jump"))
    assert set(jump.attrs["NetworkSettings"]["Networks"]) >= {
        "nidavellir-multiseg-dmz", "nidavellir-multiseg-corp"
    }

    # Containers are keyed/labeled by unique node name (not role).
    node_labels = {kw["labels"][LABEL_NODE] for kw in client.containers.run_kwargs}
    assert node_labels == {"web", "db", "jump"}
    # default-first then alpha → corp, dmz; the primary is the first.
    assert result["outputs"]["lab_networks"] == [
        "nidavellir-multiseg-corp", "nidavellir-multiseg-dmz"
    ]
    assert result["outputs"]["lab_network"] == "nidavellir-multiseg-corp"


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

    kw = next(kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "ops")
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


def test_no_command_victim_gets_generic_keepalive_wrap():
    # Liveness guardrail (generic — NO image allowlist): any victim with no
    # explicit command is wrapped so it can't die on a headless boot. The wrap
    # re-runs the image's OWN startup and then blocks, with the image CMD cleared
    # so it isn't re-appended. A real foreground service is unaffected (its server
    # blocks before the trailing blocker is reached).
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            # An arbitrary image the model might pick — not on any known list.
            {"name": "target", "role": "victim", "image": "some/obscure-cve-box:1.2", "ports": [8080]},
            # An author/generator-supplied explicit command must always win.
            {"name": "scripted", "role": "victim", "image": "ubuntu",
             "command": "sh -c 'service ssh start; sleep infinity'"},
            {"name": "kali", "role": "attacker", "image": "kali", "entrypoint": True},
        ],
    }
    provider.deploy(scenario, "keepaliv")
    by_node = {kw["labels"][LABEL_NODE]: kw for kw in client.containers.run_kwargs}

    # No-command victim -> wrapped (re-run startup, then a portable blocker).
    target = by_node["target"]
    assert target["entrypoint"][:2] == ["/bin/sh", "-c"]
    script = target["entrypoint"][2]
    assert "/bin/services.sh" in script          # the image's own startup is preserved
    assert "tail -f /dev/null" in script         # portable blocker (not `sleep infinity`)
    assert target.get("command") == []           # image CMD cleared (folded into script)

    # An explicit command always wins — never overridden by the guardrail.
    scripted = by_node["scripted"]
    assert "entrypoint" not in scripted
    assert scripted["command"] == "sh -c 'service ssh start; sleep infinity'"

    # The foothold keeps its existing keepalive command; no entrypoint override.
    kali = by_node["kali"]
    assert "entrypoint" not in kali
    assert kali.get("command") == "sleep infinity"


def test_open_url_targets_web_port_not_first_published():
    # The WebUI "Open" button must land on the real web server. A multi-port box
    # (metasploitable: 21/80/3306) must open on 80, not whatever Docker bound first.
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "box", "role": "victim", "image": "metasploitable2",
             "ports": [21, 80, 3306]},  # fake binds 21->49000, 80->49001, 3306->49002
            {"name": "kali", "role": "attacker", "image": "kali", "entrypoint": True},
        ],
    }
    out = provider.deploy(scenario, "weburl12")["outputs"]
    assert out["node_box_url"] == "http://127.0.0.1:49001"          # 80, not 21
    assert out["node_box_floating_ip"] == "127.0.0.1:49001"
    assert out["victim_web_url"] == "http://127.0.0.1:49001"        # legacy key too
    # The full mapping is surfaced so non-web services stay reachable.
    assert out["node_box_ports"] == {"21": "49000", "80": "49001", "3306": "49002"}


def test_open_url_uses_https_scheme_for_tls_port():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [{"name": "web", "role": "victim", "image": "nginx", "ports": [443]}],
    }
    out = provider.deploy(scenario, "httpsweb")["outputs"]
    assert out["node_web_url"] == "https://127.0.0.1:49000"


def test_no_web_port_emits_no_open_url_but_keeps_mapping():
    # An FTP-only target gets a reachable host:port but NO browser Open URL (so
    # the button doesn't link the operator to a non-web port).
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [{"name": "ftp", "role": "victim", "image": "some/ftp", "ports": [21]}],
    }
    out = provider.deploy(scenario, "ftponly1")["outputs"]
    assert "node_ftp_url" not in out
    assert "victim_web_url" not in out
    assert out["node_ftp_floating_ip"] == "127.0.0.1:49000"
    assert out["node_ftp_ports"] == {"21": "49000"}


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
    seg = by_name["nidavellir-lockaaaa-lab"]
    assert seg.internal is True  # hard egress block (no route to the internet)
    ingress = by_name["nidavellir-lockaaaa-ingress"]
    assert ingress.internal is False
    assert ingress.options.get("com.docker.network.bridge.enable_ip_masquerade") == "false"

    # The web node (publishes a port) runs PRIMARY on the ingress bridge so the
    # operator's browser can reach it; publishing dies on an `internal` net.
    web_kw = next(kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "web")
    assert web_kw["network"] == "nidavellir-lockaaaa-ingress"
    assert web_kw.get("ports")  # the published port rides the ingress net
    # The foothold (no ports) stays on the internal segment only — no ingress.
    kali_kw = next(kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "kali")
    assert kali_kw["network"] == "nidavellir-lockaaaa-lab"
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
    assert not any(n.name.endswith("-ingress") for n in client.networks.created)
    # Segment nets are internal (no egress). The only non-internal bridge is the
    # package mirror's own egress bridge (the mirror needs to reach the repos).
    seg_nets = [n for n in client.networks.created if not n.name.endswith("-mirror")]
    assert seg_nets and all(n.internal for n in seg_nets)
    mirror_net = next(n for n in client.networks.created if n.name.endswith("-mirror"))
    assert mirror_net.internal is False


# --- allowlisted package mirror (P2-3 / ADR-0005) -----------------------------


def test_locked_arena_with_foothold_gets_allowlisted_mirror():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    outputs = provider.deploy(LOCKED_SCENARIO, "mirroraa-uuid")["outputs"]

    assert outputs["package_mirror"] == "allowlisted"

    # A dedicated egress bridge + a mirror container running on it.
    mirror_net = next(n for n in client.networks.created if n.name.endswith("-mirror"))
    assert mirror_net.internal is False  # the mirror must reach the package repos
    mirror_kw = next(
        kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "mirror"
    )
    assert mirror_kw["network"] == mirror_net.name

    # The mirror joins each internal segment as `mirror` so footholds resolve it.
    seg = next(n for n in client.networks.created if n.name == "nidavellir-mirroraa-lab")
    assert "mirror" in seg.aliases.get(mirror_kw["name"], [])

    # The foothold (kali) gets its apt/pip pointed at the mirror; the victim does not.
    kali_kw = next(kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "kali")
    assert kali_kw["environment"]["http_proxy"] == "http://mirror:3128"
    assert kali_kw["environment"]["https_proxy"] == "http://mirror:3128"
    web_kw = next(kw for kw in client.containers.run_kwargs if kw["labels"][LABEL_NODE] == "web")
    assert "environment" not in web_kw

    # The foothold's apt is pinned to the allowlisted direct CDN.
    kali_ct = next(c for c in client.containers.created if c.labels.get(LABEL_NODE) == "kali")
    assert any("kali.download" in str(c) for c in getattr(kali_ct, "exec_calls", []))


def test_mirror_image_is_built_when_absent():
    client = _FakeClient(mirror_image_present=False)
    provider = DockerLocalProvider(client=client)
    provider.deploy(LOCKED_SCENARIO, "buildimg-uuid")
    assert client.images.built, "mirror image should be built on first use"
    assert client.images.built[0]["tag"] == "nidavellir/arena-mirror:latest"


def test_mirror_opt_out_and_open_arena_have_no_mirror():
    # Explicit opt-out on a locked arena.
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "mirror": "off"},
        "nodes": [{"name": "box", "role": "attacker", "image": "alpine", "entrypoint": True}],
    }
    outputs = provider.deploy(scenario, "nomirror1")["outputs"]
    assert "package_mirror" not in outputs
    assert not any(n.name.endswith("-mirror") for n in client.networks.created)

    # An open (un-contained) arena never needs a mirror — egress works directly.
    client2 = _FakeClient()
    provider2 = DockerLocalProvider(client=client2)
    open_scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [{"name": "box", "role": "attacker", "image": "alpine", "entrypoint": True}],
    }
    outputs2 = provider2.deploy(open_scenario, "nomirror2")["outputs"]
    assert "package_mirror" not in outputs2
    assert not any(n.name.endswith("-mirror") for n in client2.networks.created)


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
        # Open arena: a focused deploy/inspect/destroy lifecycle test. Egress
        # containment + the package mirror have their own dedicated tests below.
        "requires": {"provider_class": "container", "egress": "open"},
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
        exec_res = provider.exec_in_node(instance_id, "attacker", "echo nidavellir-ok")
        assert exec_res["success"] is True, exec_res.get("error")
        assert exec_res["exit_code"] == 0
        assert "nidavellir-ok" in exec_res["stdout"]
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


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="no Docker daemon available")
def test_locked_arena_mirror_allows_repos_but_not_egress_real_docker():
    """The package mirror (P2-3 / ADR-0005) lets a contained foothold reach
    allowlisted repos via the proxy, WITHOUT re-opening general egress: direct
    internet is still dead, and a non-allowlisted host is denied by the proxy."""
    scenario = {
        "requires": {"provider_class": "container"},  # locked + mirror by default
        "nodes": [{"name": "box", "role": "attacker", "image": "alpine:3.20",
                   "entrypoint": True}],
    }
    provider = DockerLocalProvider()
    iid = "itest-mirror"
    try:
        assert provider.deploy(scenario, iid)["success"] is True

        # 1) Direct egress is STILL blocked — the mirror must not be a NAT hole.
        direct = provider.exec_in_node(
            iid, "box",
            "env -u http_proxy -u https_proxy wget -q -T5 -O- http://1.1.1.1 "
            "&& echo REACHED || echo BLOCKED",
            timeout=15,
        )
        assert "BLOCKED" in direct["stdout"], direct
        assert "REACHED" not in direct["stdout"], direct

        # 2) An allowlisted repo IS reachable through the proxy (http_proxy is
        #    pre-set on the foothold, so plain wget routes via the mirror).
        allowed = provider.exec_in_node(
            iid, "box",
            "wget -q -T15 -O- http://deb.debian.org/debian/dists/bookworm/Release "
            "| head -c1 >/dev/null && echo REACHED || echo BLOCKED",
            timeout=25,
        )
        assert "REACHED" in allowed["stdout"], allowed

        # 3) A non-allowlisted host is denied by the proxy (squid 403).
        denied = provider.exec_in_node(
            iid, "box",
            "wget -q -T10 -O- http://example.com/ && echo REACHED || echo DENIED",
            timeout=20,
        )
        assert "REACHED" not in denied["stdout"], denied
    finally:
        assert provider.destroy(iid)["success"] is True


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="no Docker daemon available")
def test_keepalive_keeps_arbitrary_victim_alive_real_docker(tmp_path):
    """Generic liveness guardrail, real containers, NO image allowlist. A tiny
    purpose-built image whose CMD daemonizes then returns reproduces the 'victim
    dies on boot' failure when run raw — but deploying it as a no-command victim
    keeps it running, because the provider wraps ANY no-command victim's own
    startup in a keepalive. (Mirrors real metasploitable2 without the multi-GB pull.)"""
    import time

    import docker

    client = docker.from_env()
    # Tiny legacy-style image: starts a background 'daemon', prints, and exits.
    (tmp_path / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN printf '#!/bin/sh\\n(while true; do sleep 30; done) &\\necho up\\n'"
        " > /bin/services.sh && chmod +x /bin/services.sh\n"
        'CMD ["/bin/services.sh"]\n'
    )
    tag = "nidavellir-legacy-itest:latest"
    client.images.build(path=str(tmp_path), tag=tag, rm=True)

    raw = None
    provider = DockerLocalProvider()
    iid = "itest-keepalive"
    try:
        # Baseline: run the image the way a plain detached deploy would — it exits.
        raw = client.containers.run(tag, detach=True, name="itest-keepalive-raw")
        time.sleep(6)  # outlast the daemonize-then-exit window
        raw.reload()
        assert raw.attrs["State"]["Status"] == "exited", "control: raw image should die on boot"

        # The guardrail: the SAME image as a no-command victim stays up.
        scenario = {
            "requires": {"provider_class": "container", "egress": "open"},
            "nodes": [{"name": "victim", "role": "victim", "image": tag}],
        }
        assert provider.deploy(scenario, iid)["success"] is True
        time.sleep(6)
        c = provider._find_node_container(iid, "victim")
        c.reload()
        assert c.attrs["State"]["Status"] == "running", "keepalive must keep the victim up"
        # The wrap re-ran the image's OWN startup, so its 'daemon' is alive inside.
        rc, _ = c.exec_run(["sh", "-c", "pgrep -f 'sleep 30' >/dev/null"])
        assert rc == 0, "the image's own startup must still have run under the wrap"
    finally:
        provider.destroy(iid)
        if raw is not None:
            try:
                raw.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        try:
            client.images.remove(tag, force=True)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


# --- software-under-test `service:` provisioning (P1-6, packaged-first) -------

def test_sut_packaged_service_image_is_used_and_whitebox_surfaced():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "victim", "role": "victim", "ports": [3000],
             "service": {"image": "bkimminich/juice-shop:latest", "whitebox": True}},
            {"name": "attacker", "role": "attacker",
             "image": "kalilinux/kali-rolling:latest", "entrypoint": True},
        ],
    }
    result = provider.deploy(scenario, "sut12345-rest-of-uuid")
    assert result["success"] is True
    images_run = [k["image"] for k in client.containers.run_kwargs]
    assert "bkimminich/juice-shop:latest" in images_run   # packaged service image used
    assert result["outputs"].get("node_victim_whitebox") is True


def test_sut_source_build_disabled_by_default_fails_clearly(monkeypatch):
    # Building untrusted source executes it at build time, so it is OFF unless
    # NIDAVELLIR_ALLOW_SOURCE_BUILD is set — a `source` service then fails with a
    # clear, actionable error pointing at the flag (default-deny posture).
    monkeypatch.setattr(config, "ALLOW_SOURCE_BUILD", False)
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "victim", "role": "victim",
             "service": {"source": {"repo": "https://github.com/o/p", "ref": "v1"}}},
            {"name": "attacker", "role": "attacker",
             "image": "kalilinux/kali-rolling:latest", "entrypoint": True},
        ],
    }
    result = provider.deploy(scenario, "sut99999-rest-of-uuid")
    assert result["success"] is False
    assert "build-from-source" in result["error"]
    assert "NIDAVELLIR_ALLOW_SOURCE_BUILD" in result["error"]


def test_sut_source_build_runs_built_image_when_enabled(monkeypatch):
    # With the gate enabled, a `source` service is built via the daemon from a
    # pinned remote git context and the node runs the freshly built image.
    monkeypatch.setattr(config, "ALLOW_SOURCE_BUILD", True)
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "victim", "role": "victim", "ports": [3000],
             "service": {"source": {
                 "repo": "https://github.com/o/p", "ref": "v1", "context": "web"}}},
            {"name": "attacker", "role": "attacker",
             "image": "kalilinux/kali-rolling:latest", "entrypoint": True},
        ],
    }
    result = provider.deploy(scenario, "sutbuild1-rest-of-uuid")
    assert result["success"] is True, result.get("error")

    # The daemon was asked to build from a pinned, sub-dir'd remote git context,
    # tagged + arena-labeled, pulling fresh bases.
    build = next(b for b in client.images.built
                 if str(b.get("tag", "")).startswith("nidavellir/sut:"))
    assert build["path"] == "https://github.com/o/p#v1:web"
    assert build["dockerfile"] == "Dockerfile"
    assert build["pull"] is True
    assert build["labels"][LABEL_LAB_ID] == "sutbuild1-rest-of-uuid"

    # The victim runs that built image — not a pulled catalog tag.
    victim_kw = next(kw for kw in client.containers.run_kwargs
                     if kw["labels"][LABEL_NODE] == "victim")
    assert victim_kw["image"] == build["tag"]


def test_sut_source_build_image_is_reclaimed_on_destroy(monkeypatch):
    # A from-source build would leak one image per arena; destroy() reclaims the
    # arena-labeled built image.
    monkeypatch.setattr(config, "ALLOW_SOURCE_BUILD", True)
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "victim", "role": "victim",
             "service": {"source": {"repo": "https://github.com/o/p", "ref": "v1"}}},
        ],
    }
    provider.deploy(scenario, "sutbuild2-uuid")
    built_tag = client.images.built[-1]["tag"]

    assert provider.destroy("sutbuild2-uuid")["success"] is True
    assert built_tag in client.images.removed


# --- white-box source access (P2-10 safe half: read-only source mount) --------

def test_whitebox_source_cloned_and_mounted_readonly_on_foothold():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "app", "role": "victim", "ports": [3000],
             "service": {"image": "bkimminich/juice-shop:latest", "whitebox": True,
                         "source": {"repo": "https://github.com/juice-shop/juice-shop",
                                    "ref": "v15.0.0"}}},
            {"name": "kali", "role": "attacker",
             "image": "kalilinux/kali-rolling:latest", "entrypoint": True},
        ],
    }
    outputs = provider.deploy(scenario, "wbx12345-rest-of-uuid")["outputs"]

    # A per-arena, labeled source volume was created.
    (vol,) = client.volumes.created
    assert vol.name == "nv-wbx12345-src-app"
    assert vol.labels[LABEL_LAB_ID] == "wbx12345-rest-of-uuid"

    # The git-clone helper ran with repo/ref via env (no shell-injection surface).
    helper = next(kw for kw in client.containers.run_kwargs
                  if kw.get("image") == "alpine/git:latest")
    assert helper["environment"] == {
        "REPO": "https://github.com/juice-shop/juice-shop", "REF": "v15.0.0"}
    assert helper["volumes"][vol.name]["bind"] == "/src"
    assert helper["remove"] is True

    # The foothold mounts that volume READ-ONLY at /whitebox/<victim>; the victim
    # does not mount it.
    kali = next(kw for kw in client.containers.run_kwargs
                if kw.get("labels", {}).get(LABEL_NODE) == "kali")
    assert kali["volumes"][vol.name] == {"bind": "/whitebox/app", "mode": "ro"}
    app = next(kw for kw in client.containers.run_kwargs
               if kw.get("labels", {}).get(LABEL_NODE) == "app")
    assert "volumes" not in app

    # The readable path is surfaced and the whitebox flag retained.
    assert outputs["node_app_whitebox_source"] == "/whitebox/app"
    assert outputs["node_app_whitebox"] is True


def test_whitebox_without_source_warns_and_still_deploys():
    # A packaged image + the `whitebox` flag but no source: backward-compatible —
    # no clone, deploy succeeds, the flag is still surfaced (no source to mount).
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "app", "role": "victim", "ports": [3000],
             "service": {"image": "bkimminich/juice-shop:latest", "whitebox": True}},
            {"name": "kali", "role": "attacker",
             "image": "kalilinux/kali-rolling:latest", "entrypoint": True},
        ],
    }
    result = provider.deploy(scenario, "wbxnosrc-uuid")
    assert result["success"] is True
    assert client.volumes.created == []
    assert result["outputs"]["node_app_whitebox"] is True
    assert "node_app_whitebox_source" not in result["outputs"]


def test_whitebox_source_volume_reclaimed_on_destroy():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container", "egress": "open"},
        "nodes": [
            {"name": "app", "role": "victim",
             "service": {"image": "nginx", "whitebox": True,
                         "source": {"repo": "https://github.com/o/p", "ref": "v1"}}},
            {"name": "kali", "role": "attacker", "image": "alpine", "entrypoint": True},
        ],
    }
    provider.deploy(scenario, "wbxgc-uuid")
    (vol,) = client.volumes.created
    assert not vol.removed

    assert provider.destroy("wbxgc-uuid")["success"] is True
    assert vol.removed is True
