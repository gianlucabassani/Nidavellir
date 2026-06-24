"""
Deterministic Vulhub → v3 scenario importer (ROADMAP P1-5 / Classic-range track C).

Vulhub (https://github.com/vulhub/vulhub) ships hundreds of pre-built, vulnerable
container environments as Docker Compose files — one directory per CVE/app, e.g.
``weblogic/CVE-2017-10271/docker-compose.yml``. This module converts such a
compose file into a CyberGuard **v3 scenario** that lands in the import registry
(``scenarios.save_scenario``) exactly like a hand-authored pack, so it can be
previewed and deployed on docker-local — native to the container model.

The conversion is **deterministic** (no LLM — that is the separate prompt→spec
generator, track D) and **honest**: every compose key we can't faithfully map
(``volumes``, ``depends_on``, ``privileged``, …) is reported in ``warnings`` so
the operator knows what was dropped, rather than silently producing a different
arena than the one Vulhub describes.

Mapping per compose service → one v3 node (role ``victim``):
  * ``image:``        → ``node.image`` (runs as-is).
  * ``build:``        → ``node.service.source`` pointing at the Vulhub repo
                        subdir + ref. Representable and complete, but DEPLOYING it
                        needs the source-build gate (``CYBERGUARD_ALLOW_SOURCE_BUILD``,
                        off by default) — surfaced as a warning.
  * ``ports:``        → ``node.ports`` (the container side; published to a random
                        host port for browser access).
  * ``environment:``  → ``node.environment`` (dict or KEY=VALUE list).
  * ``command:``      → ``node.command``.

All victims attach to one segment; an optional Kali foothold (default on) makes
the arena drivable by a human or a BYO agent with no model in the loop
(AI-centered, never AI-required).

The network fetch is isolated in ``fetch_vulhub_compose`` so ``convert_compose``
stays pure and offline-testable.
"""
from __future__ import annotations

import logging
import posixpath
import re

import requests
import yaml

import catalog
import netguard
from scenario_spec import _slugify

logger = logging.getLogger(__name__)

# The canonical Vulhub repository. ``build:`` services point a v3 source build at
# a subdir of this repo; the raw host serves the compose file for fetch-by-path.
VULHUB_REPO_URL = "https://github.com/vulhub/vulhub.git"
VULHUB_RAW_BASE = "https://raw.githubusercontent.com/vulhub/vulhub"
# Default git ref. ``master`` tracks the live catalog; pass an explicit commit/tag
# for a reproducible build (the source-build path warns on an unpinned ref).
DEFAULT_REF = "master"

DEFAULT_SEGMENT = catalog.DEFAULT_SEGMENT  # "lab"
ATTACKER_IMAGE_ID = catalog.SUT_ATTACKER   # "kali-cli"

# Vulhub environment paths look like "weblogic/CVE-2017-10271"; restrict to a
# safe charset and reject traversal so the path can't escape the repo subtree.
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_CVE_RE = re.compile(r"CVE-\d{4}-\d{3,7}", re.IGNORECASE)

# Compose keys we map; everything else under a service is dropped with a warning.
_MAPPED_SERVICE_KEYS = {"image", "build", "ports", "environment", "command"}


class VulhubImportError(ValueError):
    """The Vulhub source was missing, unparseable, or had no convertible service."""


def _container_port(spec) -> int | None:
    """Extract the CONTAINER-side port from one compose ``ports`` entry.

    Handles the short forms ``"8080:80"``, ``"80"``, ``"127.0.0.1:8080:80"``,
    ``"8080:80/tcp"`` and the long form ``{"target": 80, ...}``. Returns None if
    no integer container port can be read (the caller warns)."""
    if isinstance(spec, dict):
        target = spec.get("target")
        try:
            return int(target)
        except (TypeError, ValueError):
            return None
    text = str(spec).split("/", 1)[0]      # drop "/tcp" | "/udp"
    parts = text.split(":")
    candidate = parts[-1]                   # container port is the last field
    try:
        return int(candidate)
    except ValueError:
        return None


def _environment(raw) -> tuple[dict[str, str], list[str]]:
    """Normalize a compose ``environment`` (dict or KEY=VALUE list) to str→str."""
    warns: list[str] = []
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            out[str(k)] = "" if v is None else str(v)
    elif isinstance(raw, list):
        for item in raw:
            key, sep, value = str(item).partition("=")
            if not sep:
                warns.append(
                    f"environment entry {item!r} has no value (host-env "
                    "passthrough is not supported) — set to empty string"
                )
            out[key] = value
    elif raw is not None:
        warns.append(f"unexpected environment shape {type(raw).__name__}; ignored")
    return out, warns


def _build_source(build, env_path: str, ref: str) -> tuple[dict, list[str]]:
    """Map a compose ``build:`` (str path or object) to a v3 ``service.source``
    rooted at the Vulhub repo subdir, plus warnings."""
    warns: list[str] = []
    context = "."
    dockerfile = None
    if isinstance(build, str):
        context = build or "."
    elif isinstance(build, dict):
        context = build.get("context", ".") or "."
        dockerfile = build.get("dockerfile")
        if build.get("args"):
            warns.append("build args are not modeled and were dropped")
    # Compose build context is relative to the compose file (the env dir).
    subdir = posixpath.normpath(posixpath.join(env_path, context)).lstrip("./")
    source = {"repo": VULHUB_REPO_URL, "ref": ref, "context": subdir or env_path}
    if dockerfile:
        source["dockerfile"] = dockerfile
    return source, warns


def _service_to_node(
    svc_name: str, svc: dict, *, env_path: str, ref: str, segment: str
) -> tuple[dict, list[str]]:
    """Convert one compose service into a v3 victim node + per-service warnings."""
    warns: list[str] = []
    name = _slugify(svc_name)
    node: dict = {"name": name, "role": "victim", "segments": [segment]}

    image = svc.get("image")
    build = svc.get("build")
    if image:
        # Prefer the published image — Vulhub publishes its built images, and
        # compose itself pulls `image` before falling back to `build`. Runnable
        # out of the box (no build gate).
        node["image"] = image
        if build:
            warns.append(
                f"service {svc_name!r}: both `image` and `build` set — using the "
                f"published image {image!r} (compose pulls it before building)"
            )
    elif build:
        source, bw = _build_source(build, env_path, ref)
        node["service"] = {"source": source}
        warns.extend(bw)
        warns.append(
            f"service {svc_name!r} builds from source — deploying it requires "
            "CYBERGUARD_ALLOW_SOURCE_BUILD=true (off by default)"
        )
    else:
        raise VulhubImportError(
            f"service {svc_name!r} has neither `image` nor `build` — cannot convert"
        )

    ports: list[int] = []
    for entry in svc.get("ports") or []:
        port = _container_port(entry)
        if port is None:
            warns.append(f"service {svc_name!r}: could not parse port {entry!r}")
        elif 1 <= port <= 65535:
            ports.append(port)
        else:
            warns.append(f"service {svc_name!r}: port {port} out of range; dropped")
    if ports:
        node["ports"] = ports

    env, ew = _environment(svc.get("environment"))
    warns.extend(f"service {svc_name!r}: {w}" for w in ew)
    if env:
        node["environment"] = env

    command = svc.get("command")
    if isinstance(command, list):
        node["command"] = " ".join(str(c) for c in command)
        warns.append(
            f"service {svc_name!r}: list-form command joined with spaces "
            "(check quoting if it relies on exec-form)"
        )
    elif command is not None:
        node["command"] = str(command)

    dropped = sorted(set(svc) - _MAPPED_SERVICE_KEYS)
    if dropped:
        warns.append(
            f"service {svc_name!r}: dropped unmapped compose key(s): "
            + ", ".join(dropped)
        )
    return node, warns


def convert_compose(
    compose: dict,
    *,
    name: str | None = None,
    env_path: str = "",
    ref: str = DEFAULT_REF,
    include_attacker: bool = True,
    segment: str = DEFAULT_SEGMENT,
) -> tuple[dict, list[str]]:
    """Convert a parsed Docker Compose dict into a v3 scenario dict + warnings.

    Pure and deterministic: no network, no clock, no randomness. ``env_path`` is
    the Vulhub environment directory (used to root ``build:`` source contexts and
    to name the pack/tags); ``ref`` is the git ref recorded for source builds.
    Raises ``VulhubImportError`` if the compose has no convertible services."""
    if not isinstance(compose, dict):
        raise VulhubImportError("compose document is not a mapping")
    services = compose.get("services")
    # Compose v1 had services at the top level (no `services:` key).
    if not isinstance(services, dict):
        if "version" not in compose and all(isinstance(v, dict) for v in compose.values()):
            services = compose
        else:
            raise VulhubImportError("compose document has no `services` mapping")
    if not services:
        raise VulhubImportError("compose document declares no services")

    warnings: list[str] = []
    nodes: list[dict] = []
    used_names: set[str] = set()
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            warnings.append(f"service {svc_name!r} is not a mapping; skipped")
            continue
        node, node_warns = _service_to_node(
            svc_name, svc, env_path=env_path, ref=ref, segment=segment
        )
        if node["name"] in used_names:  # slug collision after slugify
            base = node["name"]
            i = 2
            while f"{base}-{i}" in used_names:
                i += 1
            node["name"] = f"{base}-{i}"
        used_names.add(node["name"])
        nodes.append(node)
        warnings.extend(node_warns)

    if not nodes:
        raise VulhubImportError("no convertible services found in the compose file")

    agents: list[dict] = []
    if include_attacker:
        atk = catalog.get(ATTACKER_IMAGE_ID).to_node(segment)
        if atk["name"] in used_names:        # extremely unlikely name clash
            atk["name"] = "attacker"
        nodes.append(atk)
        agents.append({"stance": "attacker", "node": atk["name"]})

    pack_name = name or (_slugify(env_path) if env_path else "vulhub-import")
    tags = ["vulhub"]
    if env_path:
        top = env_path.strip("/").split("/")[0]
        if top:
            tags.append(_slugify(top))
    cve = _CVE_RE.search(env_path or "")
    if cve:
        tags.append(cve.group(0).upper())

    description = (
        f"Imported from Vulhub ({env_path}@{ref})." if env_path
        else "Imported from a Vulhub Docker Compose file."
    )
    raw = {
        "schema": "cyberguard/v3",
        "name": pack_name,
        "title": pack_name,
        "description": description,
        "difficulty": "vulhub",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": segment}]},
        "nodes": nodes,
        "agents": agents,
        "tags": tags,
    }
    return raw, warnings


def _validate_path(path: str) -> str:
    """Normalize + safety-check a Vulhub environment path (reject traversal)."""
    clean = (path or "").strip().strip("/")
    if not clean or not _PATH_RE.match(clean) or ".." in clean.split("/"):
        raise VulhubImportError(
            f"invalid Vulhub path {path!r} — expected e.g. 'weblogic/CVE-2017-10271'"
        )
    return posixpath.normpath(clean)


def fetch_vulhub_compose(
    path: str, *, ref: str = DEFAULT_REF, timeout: int = 15
) -> tuple[dict, str]:
    """Fetch and parse the docker-compose file for a Vulhub environment ``path``
    at git ``ref``. Returns ``(compose_dict, env_path)``.

    The host is the fixed GitHub raw CDN — still passed through the SSRF guard as
    defense in depth. Tries ``docker-compose.yml`` then ``docker-compose.yaml``."""
    env_path = _validate_path(path)
    last_err: Exception | None = None
    for filename in ("docker-compose.yml", "docker-compose.yaml"):
        url = f"{VULHUB_RAW_BASE}/{ref}/{env_path}/{filename}"
        netguard.assert_public_host(url, resolve=False)
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException as e:
            last_err = e
            continue
        if resp.status_code == 404:
            last_err = VulhubImportError(f"not found: {url}")
            continue
        if resp.status_code != 200:
            raise VulhubImportError(
                f"fetch failed ({resp.status_code}) for {url}"
            )
        try:
            compose = yaml.safe_load(resp.text)
        except yaml.YAMLError as e:
            raise VulhubImportError(f"could not parse compose at {url}: {e}") from e
        if not isinstance(compose, dict):
            raise VulhubImportError(f"compose at {url} is not a mapping")
        return compose, env_path
    raise VulhubImportError(
        f"no docker-compose.(yml|yaml) for Vulhub path {env_path!r} at ref {ref!r}"
        + (f": {last_err}" if last_err else "")
    )
