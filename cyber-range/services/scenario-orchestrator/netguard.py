"""
SSRF guard for user-supplied URLs (the SUT-wizard repo, white-box `service.source`,
and the build-from-source context).

A user can hand us a ``repo`` URL that the worker/daemon will then dereference
(``git clone`` / Docker remote build context) from inside the trust boundary. An
``https://``-only check is NOT enough: ``https://169.254.169.254/…`` (cloud
metadata), ``https://127.0.0.1/…``, or any RFC1918 host is still SSRF. This module
rejects URLs whose host is — or resolves to — an internal / metadata / loopback /
link-local / private / CGNAT address.

``resolve=False`` checks only literal-IP hosts (no DNS) — cheap and dependency-free,
for the request-validation path. ``resolve=True`` (default) additionally resolves a
hostname and rejects it if ANY address it maps to is internal.

A resolve-then-use check alone has a DNS-rebinding window: the consumer resolves the
name again and can get a different, internal answer (PF-01 U2). The fetchers
therefore use the address that was checked:

* ``git_network_args(url)`` resolves and checks once, then pins git's HTTP transport
  to exactly those addresses (``http.curloptResolve``). It also refuses redirects and
  allows only HTTP(S), because git otherwise follows a redirect to any host.
* ``public_session()`` is a ``requests`` session whose connections check the real
  peer address of each socket before anything is sent on it.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

# Carrier-grade NAT (RFC 6598) — not covered by ``is_private``, but routable to
# internal infrastructure on many cloud/ISP networks.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class UnsafeHostError(ValueError):
    """The URL's host targets an internal / metadata / reserved address."""


def _as_ip(value: str):
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_blocked_ip(ip) -> bool:
    return (
        ip.is_private          # RFC1918 v4 + ULA v6 (fc00::/7, incl. fd00::)
        or ip.is_loopback      # 127/8, ::1
        or ip.is_link_local    # 169.254/16 (incl. 169.254.169.254 metadata), fe80::/10
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified   # 0.0.0.0, ::
        or (ip.version == 4 and ip in _CGNAT)
    )


def assert_public_host(url: str, *, resolve: bool = True) -> str:
    """Return ``url`` unchanged if its host is a public address; raise
    ``UnsafeHostError`` otherwise. With ``resolve=True`` a hostname is resolved
    and rejected if any resolved address is internal."""
    host = urlsplit(url).hostname
    if not host:
        raise UnsafeHostError("could not parse a host from the URL")

    literal = _as_ip(host)
    if literal is not None:
        if _is_blocked_ip(literal):
            raise UnsafeHostError(f"host {host} is an internal/reserved address")
        return url

    if not resolve:
        return url  # literal-only mode: a hostname can't be checked without DNS

    try:
        infos = socket.getaddrinfo(host, urlsplit(url).port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeHostError(f"could not resolve host {host!r}: {e}") from e
    for info in infos:
        ip = _as_ip(info[4][0])
        if ip is not None and _is_blocked_ip(ip):
            raise UnsafeHostError(
                f"host {host!r} resolves to internal address {info[4][0]}"
            )
    return url


def _default_port(url: str) -> int:
    parts = urlsplit(url)
    return parts.port or (80 if parts.scheme == "http" else 443)


def resolve_public(url: str) -> tuple[str, int, list[str]]:
    """Resolve ``url``'s host once and return ``(host, port, addresses)``. Raises
    ``UnsafeHostError`` if the host is missing, unresolvable, or ANY address is
    internal. A literal public IP resolves to itself."""
    host = urlsplit(url).hostname
    if not host:
        raise UnsafeHostError("could not parse a host from the URL")
    port = _default_port(url)
    literal = _as_ip(host)
    if literal is not None:
        if _is_blocked_ip(literal):
            raise UnsafeHostError(f"host {host} is an internal/reserved address")
        return host, port, [str(literal)]
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeHostError(f"could not resolve host {host!r}: {e}") from e
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        ip = _as_ip(address)
        if ip is None or _is_blocked_ip(ip):
            raise UnsafeHostError(f"host {host!r} resolves to internal address {address}")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise UnsafeHostError(f"host {host!r} has no address")
    return host, port, addresses


def git_network_config(url: str) -> list[tuple[str, str]]:
    """git configuration for a networked git command on ``url``: only HTTP(S),
    no redirects, and the host pinned to the addresses checked here, so git
    cannot re-resolve the name to an internal address. Raises
    ``UnsafeHostError`` for an unsafe or non-HTTP(S) URL."""
    if urlsplit(url).scheme not in ("https", "http"):
        raise UnsafeHostError("only https:// and http:// git remotes are accepted")
    host, port, addresses = resolve_public(url)
    pinned = ",".join(f"[{a}]" if ":" in a else a for a in addresses)
    return [("protocol.allow", "never"), ("protocol.https.allow", "always"),
            ("protocol.http.allow", "always"), ("http.followRedirects", "false"),
            ("http.curloptResolve", f"{host}:{port}:{pinned}")]


def git_network_args(url: str) -> list[str]:
    """``git_network_config`` as ``-c key=value`` options for a git argv."""
    args: list[str] = []
    for key, value in git_network_config(url):
        args += ["-c", f"{key}={value}"]
    return args


def git_network_env(url: str) -> dict[str, str]:
    """``git_network_config`` as ``GIT_CONFIG_COUNT``/``KEY_n``/``VALUE_n``
    environment, for a git that runs where its argv cannot be extended safely
    (a helper container's shell)."""
    config = git_network_config(url)
    env = {"GIT_CONFIG_COUNT": str(len(config))}
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def _checked_peer(sock: socket.socket) -> socket.socket:
    address = sock.getpeername()[0]
    ip = _as_ip(address.split("%", 1)[0])
    if ip is None or _is_blocked_ip(ip):
        sock.close()
        raise UnsafeHostError(f"connection reached internal address {address}")
    return sock


class _PublicHTTPConnection(HTTPConnection):
    def _new_conn(self) -> socket.socket:
        return _checked_peer(super()._new_conn())


class _PublicHTTPSConnection(HTTPSConnection):
    def _new_conn(self) -> socket.socket:
        return _checked_peer(super()._new_conn())


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PublicHTTPPool,
                                                   "https": _PublicHTTPSPool}


def public_session() -> requests.Session:
    """A ``requests`` session that refuses to talk to internal addresses. Each new
    socket's real peer address is checked before TLS or the request starts, so a
    name that re-resolves to an internal address after an earlier check is still
    refused. Proxy environment variables are ignored: through a proxy the peer
    would be the proxy, and the check would prove nothing."""
    session = requests.Session()
    session.trust_env = False
    adapter = _PublicAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
