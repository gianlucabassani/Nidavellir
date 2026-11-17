"""Strict OCI reference parsing and anonymous registry digest resolution."""
import json

import pytest

import netguard
import oci_intake


class _Response:
    def __init__(self, status, *, headers=None, body=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body or {}

    def json(self):
        return self._body

    def iter_content(self, chunk_size=8192):
        yield json.dumps(self._body).encode()

    def close(self):
        pass


def test_parse_docker_hub_short_name():
    parsed = oci_intake.parse_reference("ubuntu:22.04")
    assert parsed.registry == "docker.io"
    assert parsed.api_registry == "registry-1.docker.io"
    assert parsed.repository == "library/ubuntu"
    assert parsed.selector == "22.04"


def test_parse_generic_registry_and_digest():
    digest = "sha256:" + "a" * 64
    parsed = oci_intake.parse_reference(f"ghcr.io/acme/widget@{digest}")
    assert parsed.registry == "ghcr.io"
    assert parsed.repository == "acme/widget"
    assert parsed.selector == digest
    assert parsed.pinned(digest) == f"ghcr.io/acme/widget@{digest}"


@pytest.mark.parametrize(
    "value",
    (
        "http://registry.example/acme/widget:latest",
        "localhost/acme/widget:latest",
        "ghcr.io/ACME/widget:latest",
        "ghcr.io/acme/widget@sha256:abcd",
        "ghcr.io/acme//widget:latest",
        "ghcr.io/acme/widget:tag?redirect=https://example.com",
    ),
)
def test_parse_rejects_unsafe_or_invalid_references(value):
    with pytest.raises((oci_intake.OciIntakeError, netguard.UnsafeHostError)):
        oci_intake.parse_reference(value)


def test_resolve_public_bearer_registry_to_digest(monkeypatch):
    digest = "sha256:" + "b" * 64
    calls = []

    monkeypatch.setattr(
        oci_intake.netguard, "assert_public_host", lambda *args, **kwargs: None
    )

    def fake_head(url, **kwargs):
        calls.append(("head", url, kwargs))
        if len([call for call in calls if call[0] == "head"]) == 1:
            return _Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer realm="https://auth.docker.io/token",'
                        'service="registry.docker.io"'
                    )
                },
            )
        return _Response(200, headers={"Docker-Content-Digest": digest})

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return _Response(200, body={"token": "anonymous-pull-token"})

    monkeypatch.setattr(oci_intake.requests, "head", fake_head)
    monkeypatch.setattr(oci_intake.requests, "get", fake_get)

    result = oci_intake.resolve_image("ubuntu:22.04")

    assert result["resolved_digest"] == digest
    assert result["runtime_ref"] == f"docker.io/library/ubuntu@{digest}"
    assert calls[1][2]["params"]["scope"] == "repository:library/ubuntu:pull"
    assert calls[2][2]["headers"]["Authorization"] == "Bearer anonymous-pull-token"
    assert all(call[2]["allow_redirects"] is False for call in calls)


def test_resolve_rejects_registry_digest_mismatch(monkeypatch):
    requested = "sha256:" + "a" * 64
    returned = "sha256:" + "b" * 64
    monkeypatch.setattr(
        oci_intake.netguard, "assert_public_host", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        oci_intake.requests,
        "head",
        lambda *args, **kwargs: _Response(
            200, headers={"Docker-Content-Digest": returned}
        ),
    )

    with pytest.raises(oci_intake.OciIntakeError, match="does not match"):
        oci_intake.resolve_image(f"ghcr.io/acme/widget@{requested}")
