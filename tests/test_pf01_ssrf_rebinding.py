"""
PF-01 U2 (review 2026-11-16): the SSRF guard had a DNS-rebinding window, and
redirects were not checked at all.

``netguard.assert_public_host`` resolved a URL's host and returned the URL; the
fetcher (git, the Docker daemon, requests) then resolved it again, and could get an
internal answer. git also follows the first HTTP redirect by default, so a public
server could send it anywhere. These tests prove the gap and pin the fix:

* git is pinned to the checked addresses (``http.curloptResolve``), redirects are
  off and only HTTP(S) is allowed (``netguard.git_network_config``);
* registry HTTP checks each socket's real peer before sending
  (``netguard.public_session``);
* the from-source build clones locally instead of letting the daemon fetch.
"""
import http.server
import os
import shutil
import socket
import subprocess
import threading
from contextlib import contextmanager

import pytest

import netguard

PUBLIC = "140.82.121.4"
PUBLIC_V6 = "2606:50c0:8000::153"


def _addrinfo(*addresses):
    return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
             (a, 443)) for a in addresses]


def test_rebinding_resolver_cannot_move_git_to_an_internal_address(monkeypatch):
    # First answer public, every later answer internal: a resolve-then-use guard
    # passes, and the consumer would then connect inside.
    answers = iter([_addrinfo(PUBLIC)])
    monkeypatch.setattr(netguard.socket, "getaddrinfo",
                        lambda *a, **k: next(answers, _addrinfo("169.254.169.254")))
    config = dict(netguard.git_network_config("https://code.example/o/r.git"))
    # git is told to use exactly the address that was checked, for that host.
    assert config["http.curloptResolve"] == f"code.example:443:{PUBLIC}"
    assert config["http.followRedirects"] == "false"
    assert config["protocol.allow"] == "never"
    assert config["protocol.https.allow"] == config["protocol.http.allow"] == "always"


@pytest.mark.parametrize("answer", [("10.0.0.5",), (PUBLIC, "127.0.0.1"),
                                    ("169.254.169.254",), ("100.64.1.1",), ("fd00::1",)])
def test_any_internal_answer_is_refused(monkeypatch, answer):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", lambda *a, **k: _addrinfo(*answer))
    with pytest.raises(netguard.UnsafeHostError):
        netguard.git_network_config("https://code.example/o/r.git")


@pytest.mark.parametrize("url", ["ssh://code.example/o/r.git", "git://code.example/o/r",
                                 "file:///etc", "ext::sh -c id", "git@code.example:o/r.git"])
def test_only_http_remotes_are_accepted(url):
    with pytest.raises(netguard.UnsafeHostError):
        netguard.git_network_config(url)


def test_every_checked_address_is_pinned_and_ipv6_is_bracketed(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo(PUBLIC, PUBLIC_V6, PUBLIC))
    config = dict(netguard.git_network_config("http://code.example:8080/r.git"))
    assert config["http.curloptResolve"] == f"code.example:8080:{PUBLIC},[{PUBLIC_V6}]"
    env = netguard.git_network_env("http://code.example:8080/r.git")
    assert int(env["GIT_CONFIG_COUNT"]) == 5
    assert {env[f"GIT_CONFIG_KEY_{i}"] for i in range(5)} == set(config)


# --- connect-time check for registry HTTP ------------------------------------------

class _Recorder(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []
    redirect_to: str | None = None

    def do_GET(self):  # noqa: N802 - stdlib handler name
        type(self).hits.append(self.path)
        if type(self).redirect_to:
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to + self.path)
        else:
            self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@contextmanager
def _server(redirect_to=None):
    handler = type("Handler", (_Recorder,), {"hits": [], "redirect_to": redirect_to})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", handler
    finally:
        server.shutdown()
        server.server_close()


def test_public_session_refuses_an_internal_peer_before_sending():
    with _server() as (url, handler):
        with pytest.raises(netguard.UnsafeHostError):
            netguard.public_session().get(url + "/v2/", timeout=5)
        assert handler.hits == []


def test_public_session_refuses_a_name_that_rebinds_at_connect_time(monkeypatch):
    import urllib3.util.connection as connection

    with _server() as (url, handler):
        port = int(url.rsplit(":", 1)[1])
        real = connection.socket.getaddrinfo

        def rebinding(host, *args, **kwargs):
            if host == "registry.example":
                return real("127.0.0.1", port, *args[1:], **kwargs)
            return real(host, *args, **kwargs)
        monkeypatch.setattr(connection.socket, "getaddrinfo", rebinding)
        with pytest.raises(netguard.UnsafeHostError):
            netguard.public_session().get(f"http://registry.example:{port}/v2/", timeout=5)
        assert handler.hits == []


def test_public_session_ignores_proxy_environment():
    assert netguard.public_session().trust_env is False


# --- git redirects -----------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _ls_remote(url, *config):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(["git", *config, "ls-remote", url], capture_output=True,
                          text=True, timeout=20, env=env, check=False)


@needs_git
def test_git_follows_a_redirect_by_default_but_not_with_the_pinned_config():
    with _server() as (internal, internal_handler), \
            _server(redirect_to=internal) as (public, _):
        # git's default: the first redirect is followed to wherever it points.
        _ls_remote(public + "/o/r.git")
        assert internal_handler.hits, "expected git's default to follow the redirect"
        internal_handler.hits.clear()
        # The pinned configuration refuses it (the pin itself is omitted here only
        # because the test servers are on loopback, which netguard would refuse).
        _ls_remote(public + "/o/r.git", "-c", "http.followRedirects=false")
        assert internal_handler.hits == []


# --- local checkout for daemon builds ----------------------------------------------

@needs_git
def test_pinned_checkout_confines_the_build_context(tmp_path, monkeypatch):
    from providers.docker_local import DockerLocalProvider

    origin = tmp_path / "origin"
    (origin / "web").mkdir(parents=True)
    (origin / "web" / "Dockerfile").write_text("FROM scratch\n")
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    for argv in (["init", "-q"], ["add", "."], ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(origin), *argv], check=True, env=env)
    # A local path stands in for the remote; the network pin is covered above.
    monkeypatch.setattr(netguard, "git_network_args", lambda url: [])

    dest = tmp_path / "checkout"
    context = DockerLocalProvider._pinned_checkout(str(origin), None, "web", str(dest))
    assert context == os.path.realpath(dest / "web")
    with pytest.raises(ValueError, match="escapes"):
        DockerLocalProvider._pinned_checkout(str(origin), None, "../..", str(tmp_path / "c2"))
