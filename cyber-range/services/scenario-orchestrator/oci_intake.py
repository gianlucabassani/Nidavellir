"""Strict, public OCI image intake with immutable digest resolution.

This module performs metadata-only registry calls. It never pulls or executes the
target image in the control plane; the provider later pulls the digest-pinned
reference inside the deployment path.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

import netguard

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_REGISTRY_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[1-9][0-9]{0,4})?\Z"
)
_COMPONENT_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
_TIMEOUT = (4, 8)
_MAX_TOKEN_RESPONSE_BYTES = 64 * 1024
_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


class OciIntakeError(ValueError):
    """The image reference or its immutable registry identity is invalid."""


@dataclass(frozen=True)
class OciReference:
    requested: str
    registry: str
    api_registry: str
    repository: str
    selector: str
    supplied_digest: str | None

    def pinned(self, digest: str) -> str:
        return f"{self.registry}/{self.repository}@{digest}"


def parse_reference(value: str) -> OciReference:
    """Parse a Docker/OCI reference without accepting URLs or local registries."""
    requested = (value or "").strip()
    if not requested or len(requested) > 500:
        raise OciIntakeError("image must be a non-empty OCI image reference")
    if "://" in requested or requested.count("@") > 1:
        raise OciIntakeError("image must be an OCI reference, not a URL")

    name, separator, supplied_digest = requested.partition("@")
    if separator and not _DIGEST_RE.fullmatch(supplied_digest):
        raise OciIntakeError("OCI digest must be sha256 followed by 64 lowercase hex digits")

    last_slash = name.rfind("/")
    last_colon = name.rfind(":")
    if last_colon > last_slash:
        selector = name[last_colon + 1 :]
        name = name[:last_colon]
    else:
        selector = "latest"
    if supplied_digest:
        selector = supplied_digest
    if not supplied_digest and not _TAG_RE.fullmatch(selector):
        raise OciIntakeError("image tag is empty or invalid")

    parts = name.split("/")
    first = parts[0] if parts else ""
    has_registry = len(parts) > 1 and (
        "." in first or ":" in first or first == "localhost"
    )
    if has_registry:
        registry = first.lower()
        repository_parts = parts[1:]
    else:
        registry = "docker.io"
        repository_parts = parts
        if len(repository_parts) == 1:
            repository_parts.insert(0, "library")

    if not _REGISTRY_RE.fullmatch(registry):
        raise OciIntakeError("invalid OCI registry host")
    hostname, separator, port_text = registry.rpartition(":")
    if separator and port_text.isdigit():
        if int(port_text) > 65535:
            raise OciIntakeError("OCI registry port must be in range 1-65535")
    else:
        hostname = registry
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise OciIntakeError("local OCI registries are outside strict public intake")
    if not repository_parts or any(
        not _COMPONENT_RE.fullmatch(component) for component in repository_parts
    ):
        raise OciIntakeError(
            "image repository must use lowercase OCI name components"
        )

    api_registry = "registry-1.docker.io" if registry == "docker.io" else registry
    netguard.assert_public_host(f"https://{api_registry}", resolve=False)
    return OciReference(
        requested=requested,
        registry=registry,
        api_registry=api_registry,
        repository="/".join(repository_parts),
        selector=selector,
        supplied_digest=supplied_digest or None,
    )


def _bearer_challenge(header: str) -> dict[str, str]:
    scheme, separator, parameters = (header or "").partition(" ")
    if not separator or scheme.lower() != "bearer":
        raise OciIntakeError("registry requires unsupported authentication")
    parsed = requests.utils.parse_dict_header(parameters)
    realm = parsed.get("realm")
    if not realm:
        raise OciIntakeError("registry authentication challenge has no realm")
    url = urlparse(realm)
    if url.scheme != "https" or not url.hostname:
        raise OciIntakeError("registry authentication realm must be public HTTPS")
    netguard.assert_public_host(realm)
    return parsed


def _public_bearer_token(challenge: dict[str, str], reference: OciReference) -> str:
    params = {"scope": f"repository:{reference.repository}:pull"}
    if challenge.get("service"):
        params["service"] = challenge["service"]
    response = requests.get(
        challenge["realm"],
        params=params,
        timeout=_TIMEOUT,
        allow_redirects=False,
        stream=True,
    )
    try:
        if response.status_code != 200:
            raise OciIntakeError(
                f"registry token service returned HTTP {response.status_code}"
            )
        body = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            body.extend(chunk)
            if len(body) > _MAX_TOKEN_RESPONSE_BYTES:
                raise OciIntakeError("registry token response exceeded 64 KiB")
        try:
            payload = json.loads(body)
            token = payload.get("token") or payload.get("access_token")
        except (AttributeError, UnicodeDecodeError, ValueError) as exc:
            raise OciIntakeError("registry token service returned invalid JSON") from exc
    finally:
        response.close()
    if not token:
        raise OciIntakeError(
            "image is private or the registry did not issue an anonymous pull token"
        )
    if not isinstance(token, str) or len(token) > 32 * 1024:
        raise OciIntakeError("registry returned an invalid anonymous pull token")
    return token


def resolve_image(value: str) -> dict:
    """Resolve a public OCI tag/digest to a verified digest-pinned runtime ref."""
    reference = parse_reference(value)
    netguard.assert_public_host(f"https://{reference.api_registry}")
    url = (
        f"https://{reference.api_registry}/v2/"
        f"{reference.repository}/manifests/{reference.selector}"
    )
    headers = {"Accept": _ACCEPT}
    response = requests.head(
        url, headers=headers, timeout=_TIMEOUT, allow_redirects=False
    )
    if response.status_code == 401:
        challenge = _bearer_challenge(response.headers.get("WWW-Authenticate", ""))
        headers["Authorization"] = f"Bearer {_public_bearer_token(challenge, reference)}"
        response = requests.head(
            url, headers=headers, timeout=_TIMEOUT, allow_redirects=False
        )
    if response.status_code == 404:
        raise OciIntakeError("OCI image or requested tag/digest was not found")
    if response.status_code in {301, 302, 303, 307, 308}:
        raise OciIntakeError("registry redirects are not accepted during strict intake")
    if response.status_code != 200:
        raise OciIntakeError(
            f"registry manifest lookup returned HTTP {response.status_code}"
        )

    digest = (response.headers.get("Docker-Content-Digest") or "").lower()
    if not _DIGEST_RE.fullmatch(digest):
        raise OciIntakeError("registry did not return a valid sha256 manifest digest")
    if reference.supplied_digest and reference.supplied_digest != digest:
        raise OciIntakeError("registry digest does not match the requested digest")
    return {
        "requested_image": reference.requested,
        "registry": reference.registry,
        "repository": reference.repository,
        "requested_ref": reference.selector,
        "resolved_digest": digest,
        "runtime_ref": reference.pinned(digest),
    }
