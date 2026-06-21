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
hostname and rejects it if ANY address it maps to is internal — the authoritative
check, used right before the actual clone/build (which already has network).
"""
import ipaddress
import socket
from urllib.parse import urlsplit

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
