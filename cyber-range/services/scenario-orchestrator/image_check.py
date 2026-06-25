"""
Best-effort Docker Hub image-existence check (Field-A: the generator can emit
images that don't exist → opaque deploy failure). Used at the review gate to warn
BEFORE deploy. Deliberately best-effort: a non-Docker-Hub registry, a network
error, or an ambiguous response returns ``None`` (unknown) so we never raise a
false alarm — only a confident 404 yields a warning.
"""
import logging

import requests

import netguard

logger = logging.getLogger("API")

_HUB = "https://hub.docker.com/v2"
_TIMEOUT = (3, 4)  # (connect, read) — the review gate must stay snappy


def parse_ref(ref: str):
    """Parse a Docker image reference into (namespace, repo, tag) for Docker Hub,
    or ``None`` when it targets another registry or pins a digest (can't check by
    name). ``ubuntu:22.04`` → ("library", "ubuntu", "22.04")."""
    if not ref or not isinstance(ref, str):
        return None
    if "@" in ref:  # digest-pinned — not checkable by tag
        return None
    # A registry host is the first segment when it contains '.' or ':' or is
    # 'localhost' — those aren't Docker Hub, so we can't check them.
    first = ref.split("/", 1)[0]
    if "/" in ref and ("." in first or ":" in first or first == "localhost"):
        return None
    name, _, tag = ref.partition(":")
    tag = tag or "latest"
    if "/" in name:
        ns, _, repo = name.partition("/")
    else:
        ns, repo = "library", name  # official images live under library/
    if not repo:
        return None
    return ns, repo, tag


def exists_on_hub(ref: str):
    """True / False / None(unknown) — does this image:tag exist on Docker Hub?"""
    parsed = parse_ref(ref)
    if parsed is None:
        return None
    ns, repo, tag = parsed
    url = f"{_HUB}/repositories/{ns}/{repo}/tags/{tag}"
    try:
        netguard.assert_public_host(url, resolve=False)
        resp = requests.get(url, timeout=_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - best-effort; unknown on any error
        logger.info("image existence check for %r inconclusive: %s", ref, type(e).__name__)
        return None
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    return None


def missing_images(refs) -> list[str]:
    """Of the given resolved image refs, those that Docker Hub confidently reports
    as NOT existing (404). Unknown/other-registry images are omitted (no false
    alarms). De-duplicated, order-preserving."""
    out, seen = [], set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        if exists_on_hub(ref) is False:
            out.append(ref)
    return out
