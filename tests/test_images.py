"""
Tests for the per-provider image map (ROADMAP Phase 1, P1-2).

Pins: logical names resolve to the right per-provider reference; concrete
tags/AMI ids pass through unchanged; docker-local actually deploys the resolved
tag (not the logical name).
"""
import images
from providers.docker_local import DockerLocalProvider


class _FakeContainer:
    def __init__(self, **kw):
        self.name = kw["name"]
        self.attrs = {"NetworkSettings": {"Networks": {kw["network"]: {"IPAddress": "1.2.3.4"}}, "Ports": {}}}

    def reload(self):
        pass


class _FakeContainers:
    def __init__(self):
        self.run_kwargs = []

    def run(self, **kw):
        self.run_kwargs.append(kw)
        return _FakeContainer(**kw)


class _FakeNetworks:
    def create(self, name, driver=None, labels=None):
        class _N:
            pass

        n = _N()
        n.name = name
        return n


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()
        self.networks = _FakeNetworks()


def test_logical_names_resolve_per_provider():
    assert images.resolve("dvwa", "docker-local") == "vulnerables/web-dvwa:latest"
    assert images.resolve("kali", "docker-local") == "kalilinux/kali-rolling:latest"
    aws_kali = images.resolve("kali", "aws")
    assert aws_kali["owner"] == "679593333241"
    assert aws_kali["name"].startswith("kali-linux")


def test_unknown_and_concrete_references_pass_through():
    # concrete container tag -> unchanged
    assert images.resolve("vulnerables/web-dvwa:latest", "docker-local") == (
        "vulnerables/web-dvwa:latest"
    )
    # concrete AMI id -> unchanged
    assert images.resolve("ami-0abc123", "aws") == "ami-0abc123"
    # known logical name but provider has no mapping -> pass through
    assert images.resolve("dvwa", "aws") == "dvwa"


def test_docker_local_deploys_resolved_image():
    client = _FakeClient()
    provider = DockerLocalProvider(client=client)
    scenario = {
        "requires": {"provider_class": "container"},
        "nodes": [{"name": "web", "role": "victim", "image": "dvwa"}],
    }
    provider.deploy(scenario, "imgtest1")
    (kw,) = client.containers.run_kwargs
    assert kw["image"] == "vulnerables/web-dvwa:latest"
