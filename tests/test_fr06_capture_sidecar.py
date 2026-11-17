"""FR-06 (B7): the MITM capture sidecar is pinned and narrowed.

The live capture with the narrowed profile is an operator gate.
"""
import config
from providers.docker_local import DockerLocalProvider
from tests.test_mitm import _TCPDUMP, _CapClient, _Net


def _capture(monkeypatch=None, image=None):
    if image is not None:
        monkeypatch.setattr(config, "MITM_CAPTURE_IMAGE", image)
    client = _CapClient([_Net("nidavellir-abcd1234-lab", "1111aaaabbbb0000")], _TCPDUMP.encode())
    result = DockerLocalProvider(client=client).capture_traffic("abcd1234-rest", seconds=2)
    return result, client.containers.kwargs


def test_default_image_is_digest_pinned():
    assert "@sha256:" in config.MITM_CAPTURE_IMAGE
    assert len(config.MITM_CAPTURE_IMAGE.split("@sha256:")[1]) == 64


def test_capture_sidecar_profile_is_narrowed():
    result, kw = _capture()
    assert result["success"] is True
    assert kw["image"] == config.MITM_CAPTURE_IMAGE
    assert kw["cap_drop"] == ["ALL"]
    assert "NET_ADMIN" not in kw["cap_add"] and "NET_RAW" in kw["cap_add"]
    assert set(kw["cap_add"]) <= {"NET_RAW", "SETUID", "SETGID"}
    assert kw["read_only"] is True
    assert kw["security_opt"] == ["no-new-privileges:true"]
    assert kw["mem_limit"] == "64m" and kw["pids_limit"] == 16 and kw["nano_cpus"]
    assert not kw.get("privileged")


def test_unpinned_image_is_refused(monkeypatch):
    result, kw = _capture(monkeypatch, "nicolaka/netshoot:latest")
    assert result["success"] is False and "pinned by digest" in result["error"]
    assert kw is None  # nothing was started
