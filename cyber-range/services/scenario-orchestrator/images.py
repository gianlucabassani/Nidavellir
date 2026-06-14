"""
Per-provider image map (ROADMAP Phase 1, P1-2).

A scenario node declares a *logical* image (``kali``, ``dvwa``, ``ubuntu``);
this module resolves it to the concrete reference each provider understands:

- **docker-local** → a container image tag (``kalilinux/kali-rolling:latest``)
- **aws** → an AMI selector: ``{"name": <name-filter>, "owner": <account-id>}``
  for a ``data "aws_ami"`` lookup, or ``{"ami": "ami-..."}`` for a fixed id.

Unknown logical names **pass through unchanged**, so scenarios may also use a
concrete tag / AMI id directly (``vulnerables/web-dvwa:latest``, ``ami-0abc…``).
This keeps one logical scenario portable across providers while letting authors
drop down to a concrete reference when they need to.
"""
from __future__ import annotations

# logical name -> {provider: concrete reference}
_IMAGE_MAP: dict[str, dict[str, object]] = {
    "kali": {
        "docker-local": "kalilinux/kali-rolling:latest",
        # Kali Linux official AMIs (Marketplace owner account).
        "aws": {"name": "kali-linux-2024.*", "owner": "679593333241"},
    },
    "ubuntu": {
        "docker-local": "ubuntu:22.04",
        # Canonical's official Ubuntu 22.04 AMIs.
        "aws": {
            "name": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*",
            "owner": "099720109477",
        },
    },
    "ubuntu-22.04": {
        "docker-local": "ubuntu:22.04",
        "aws": {
            "name": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*",
            "owner": "099720109477",
        },
    },
    "dvwa": {"docker-local": "vulnerables/web-dvwa:latest"},
    "juice-shop": {"docker-local": "bkimminich/juice-shop:latest"},
    "metasploitable2": {"docker-local": "tleemcjr/metasploitable2:latest"},
}


def resolve(logical_name: str, provider: str) -> object:
    """Resolve a scenario image reference for ``provider``.

    Returns the provider-specific reference (a tag string for docker-local, an
    AMI-selector dict for aws). Unknown logical names — including concrete tags
    and AMI ids — pass through unchanged.
    """
    entry = _IMAGE_MAP.get(logical_name)
    if entry and provider in entry:
        return entry[provider]
    return logical_name


def known_logical_names() -> list[str]:
    return sorted(_IMAGE_MAP)
