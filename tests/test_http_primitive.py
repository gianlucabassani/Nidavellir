"""Tests for the R1 arena HTTP primitive (provider layer).

Unit tests drive the providers with fake Docker clients / canned data (no
daemon needed); the live compose verification is performed per milestone
against a real docker-local arena, outside this suite.
"""
import hashlib

import config
import pytest

from providers.aws import AWSProvider
from providers.docker_local import LABEL_LAB_ID, LABEL_ROLE, DockerLocalProvider
from providers.mock import MockProvider
from providers.openstack import OpenStackProvider


# --- fakes ---------------------------------------------------------------------


class _Target:
    def __init__(self, labels=None, network="nidavellir-abcd1234", ip="172.99.0.10"):
        self.labels = labels or {}
        self.attrs = {
            "NetworkSettings": {"Networks": {network: {"IPAddress": ip}}},
        }
        self.reloaded = False

    def reload(self):
        self.reloaded = True


class _Runner:
    def __init__(self, stdout=b"", stderr=b"", exit_code=0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.wait_timeout = None
        self.removed = False

    def wait(self, timeout):
        self.wait_timeout = timeout
        return {"StatusCode": self.exit_code}

    def logs(self, stdout=True, stderr=True):
        if stderr and not stdout:
            return self.stderr
        return self.stdout

    def remove(self, force=False):
        self.removed = True


class _Containers:
    def __init__(self, runner):
        self.runner = runner
        self.kwargs = None

    def run(self, **kwargs):
        self.kwargs = kwargs
        return self.runner


class _Client:
    def __init__(self, runner):
        self.containers = _Containers(runner)


def _provider(runner=None, target=None):
    provider = DockerLocalProvider(client=_Client(runner or _Runner()))
    provider._find_node_container = lambda _arena, _node: (
        target if target is not None else _Target()
    )
    return provider


_RAW_OK = (
    b"HTTP/1.1 200 OK\r\n"
    b"Server: nginx\r\n"
    b"Content-Type: text/html\r\n"
    b"\r\n"
    b"<html>hello</html>"
)


# --- contracts -----------------------------------------------------------------


def test_providers_without_the_primitive_refuse_it():
    for provider_cls in (OpenStackProvider, AWSProvider):
        with pytest.raises(NotImplementedError):
            provider_cls().http_request(
                "a1", "victim", "172.99.0.10", 80, "http", "/"
            )


def test_mock_http_request_is_deterministic_and_hashed():
    result = MockProvider().http_request(
        "a1", "victim", "192.168.50.10", 80, "http", "/login", {"u": "admin"},
        method="POST", body="x=1",
    )
    assert result["success"] is True
    assert result["status"] == 200
    assert result["url"] == "http://192.168.50.10:80/login?u=admin"
    expected = hashlib.sha256(result["body"].encode()).hexdigest()
    assert result["body_sha256"] == f"sha256:{expected}"
    assert result["truncated"] is False
    assert MockProvider().http_request(
        "a1", "victim", "192.168.50.10", 80, "http", "/login", {"u": "admin"},
        method="POST", body="x=1",
    )["body_sha256"] == result["body_sha256"]


# --- docker-local happy paths ---------------------------------------------------


def test_http_request_is_hardened_arena_bound_and_parses_the_response():
    runner = _Runner(stdout=_RAW_OK)
    provider = _provider(runner=runner)

    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 80, "http", "/search",
        {"q": "a b"},
    )

    assert result["success"] is True
    assert result["status"] == 200
    assert result["reason"] == "OK"
    assert result["http_version"] == "HTTP/1.1"
    assert result["headers"]["server"] == "nginx"
    assert result["header_count"] == 2
    assert result["redirect_location"] is None
    assert result["body"] == "<html>hello</html>"
    assert result["body_bytes"] == len(b"<html>hello</html>")
    assert result["body_sha256"] == (
        f"sha256:{hashlib.sha256(b'<html>hello</html>').hexdigest()}"
    )
    assert result["truncated"] is False
    assert runner.wait_timeout == config.HTTP_TIMEOUT_SECONDS + 5
    assert runner.removed is True

    kwargs = provider.client.containers.kwargs
    assert kwargs["image"] == config.HTTP_RUNNER_IMAGE
    assert kwargs["entrypoint"] == "curl"
    assert kwargs["network"] == "nidavellir-abcd1234"
    assert kwargs["labels"] == {
        LABEL_LAB_ID: "abcd1234-rest",
        LABEL_ROLE: "http",
    }
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["read_only"] is True
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["pids_limit"] == 64
    command = kwargs["command"]
    assert "-L" not in command
    assert command[-1] == "http://172.99.0.10:80/search?q=a+b"


def test_http_request_sends_method_headers_body_without_framing_overrides():
    provider = _provider(runner=_Runner(stdout=_RAW_OK))
    provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 8000, "http", "/api/item",
        method="post",
        headers={"X-Proof": "1", "Content-Length": "3", "Transfer-Encoding": "gzip"},
        body="a=b",
    )
    command = provider.client.containers.kwargs["command"]
    assert command[command.index("-X") + 1] == "POST"
    assert "X-Proof: 1" in command
    joined = "\n".join(command)
    assert "content-length" not in joined.lower()
    assert "transfer-encoding" not in joined.lower()
    assert command[command.index("--data-binary") + 1] == "a=b"
    assert command[-1] == "http://172.99.0.10:8000/api/item"


def test_http_request_truncates_but_hashes_the_full_body(monkeypatch):
    monkeypatch.setattr(config, "HTTP_MAX_RESPONSE_BYTES", 5)
    raw = b"HTTP/1.1 200 OK\r\n\r\nabcdefghij"
    _, _, payload = raw.partition(b"\r\n\r\n")
    provider = _provider(runner=_Runner(stdout=raw))

    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 80, "http", "/"
    )

    assert result["success"] is True
    assert result["body"] == "abcde"
    assert result["body_bytes"] == 10
    assert result["truncated"] is True
    assert result["body_sha256"] == f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_http_request_reports_redirects_instead_of_following_them():
    raw = (
        b"HTTP/1.1 302 Found\r\nLocation: /session\r\n\r\n"
    )
    provider = _provider(runner=_Runner(stdout=raw))
    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 80, "http", "/login"
    )
    assert result["success"] is True
    assert result["status"] == 302
    assert result["redirect_location"] == "/session"
    assert "-L" not in provider.client.containers.kwargs["command"]


def test_http_request_handles_header_only_response():
    provider = _provider(runner=_Runner(stdout=b"HTTP/1.0 204 No Content\r\nX: y\r\n"))
    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 80, "http", "/"
    )
    assert result["success"] is True
    assert result["status"] == 204
    assert result["body"] == ""
    assert result["body_bytes"] == 0
    assert result["headers"]["x"] == "y"


def test_http_request_joins_repeated_headers():
    raw = b"HTTP/1.1 200 OK\r\nSet-Cookie: a=1\r\nSet-Cookie: b=2\r\n\r\n"
    provider = _provider(runner=_Runner(stdout=raw))
    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 80, "http", "/"
    )
    assert result["headers"]["set-cookie"] == "a=1, b=2"


# --- failure paths --------------------------------------------------------------


def test_http_request_surfaces_curl_timeouts_cleanly():
    provider = _provider(runner=_Runner(exit_code=28, stderr=b""))
    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 80, "http", "/"
    )
    assert result["success"] is False
    assert "timed out" in result["error"]


def test_http_request_refuses_target_ip_not_owned_by_node():
    provider = DockerLocalProvider(client=_FakeListClient())
    provider._find_node_container = lambda _arena, _node: _Target()
    result = provider.http_request(
        "abcd1234-rest", "victim", "169.254.169.254", 80, "http", "/"
    )
    assert result["success"] is False
    assert "not attached" in result["error"]


def test_http_request_refuses_unknown_node():
    provider = DockerLocalProvider(client=_FakeListClient())
    provider._find_node_container = lambda _arena, _node: None
    result = provider.http_request(
        "abcd1234-rest", "ghost", "172.99.0.10", 80, "http", "/"
    )
    assert result["success"] is False
    assert "not found in arena" in result["error"]


class _FakeListClient:
    """A client that must never be asked to run anything (validation refusals)."""

    class _Containers:
        def run(self, **kwargs):
            raise AssertionError("runner started despite an invalid request")

    def __init__(self):
        self.containers = self._Containers()


# --- request validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scheme": "ftp"},
        {"path": "relative"},
        {"path": "//evil.example.com/"},
        {"port": 0},
        {"port": 70000},
        {"method": "GET; rm -rf /"},
        {"body": "nul\x00byte"},
        {"headers": {"X-Bad": "one\r\nX-Injected: two"}},
        {"headers": {"Bad Header": "1"}},
    ],
)
def test_http_request_refuses_invalid_requests(kwargs):
    provider = _provider()
    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10",
        kwargs.get("port", 80), kwargs.get("scheme", "http"),
        kwargs.get("path", "/"),
        method=kwargs.get("method", "GET"),
        body=kwargs.get("body"),
        headers=kwargs.get("headers"),
    )
    assert result["success"] is False
    assert provider.client.containers.kwargs is None


def test_http_request_refuses_oversized_body(monkeypatch):
    monkeypatch.setattr(config, "HTTP_MAX_REQUEST_BYTES", 4)
    provider = _provider()
    result = provider.http_request(
        "abcd1234-rest", "victim", "172.99.0.10", 80, "http", "/", body="12345"
    )
    assert result["success"] is False
    assert "limit" in result["error"]
