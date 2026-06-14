"""
Curated image catalog for the manual scenario creator (ROADMAP P1-3).

Lets an operator build a custom arena by *picking* a vetted attacker box and one
or more victims — no hand-written scenario file — which the docker-local
provider then pulls and spawns. Each entry resolves to a v3 node; the whole
selection is compiled to a validated `ScenarioSpec` before anything is queued.

This is the secure manual path: arenas are built from this whitelist, not from
arbitrary client-supplied image strings (arbitrary images would be an explicit,
separately-gated capability). Entries are easy to extend; image tags are
best-effort and an operator can adjust them.
"""
from dataclasses import dataclass, field

from scenario_spec import ScenarioSpec

DEFAULT_SEGMENT = "lab"


@dataclass(frozen=True)
class CatalogImage:
    id: str  # catalog slug, doubles as the node name
    name: str  # display name
    kind: str  # "attacker" | "victim"
    image: str  # concrete container image reference
    provider_class: str = "container"  # "container" | "vm"
    description: str = ""
    ports: tuple[int, ...] = ()
    command: str | None = None
    access: str = "cli"  # "cli" | "web" | "vnc"
    available: bool = True  # False → listed but not deployable here (e.g. VM-only)
    note: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_node(self, segment: str = DEFAULT_SEGMENT) -> dict:
        node = {
            "name": self.id,
            "role": "attacker" if self.kind == "attacker" else "victim",
            "image": self.image,
            "segments": [segment],
        }
        if self.kind == "attacker":
            node["entrypoint"] = True
        if self.ports:
            node["ports"] = list(self.ports)
        if self.command is not None:
            node["command"] = self.command
        return node


# --- the catalog -------------------------------------------------------------

CATALOG: list[CatalogImage] = [
    # --- attackers ---
    CatalogImage(
        "kali-cli", "Kali Linux (CLI)", "attacker", "kalilinux/kali-rolling:latest",
        description="Kali rolling, command-line. Minimal base — apt install tools at runtime.",
        command="sleep infinity", access="cli", tags=("kali", "cli"),
    ),
    CatalogImage(
        "kali-gui", "Kali Linux (GUI / noVNC)", "attacker",
        "kasmweb/kali-rolling-desktop:1.16.0",
        description="Kali XFCE desktop reachable in the browser via noVNC.",
        ports=(6901,), access="vnc", tags=("kali", "gui", "vnc"),
        note="Browser desktop on the published 6901 port (KASM; default user 'kasm_user').",
    ),
    CatalogImage(
        "ubuntu", "Ubuntu 22.04", "attacker", "ubuntu:22.04",
        description="Plain Ubuntu box for custom tooling.",
        command="sleep infinity", access="cli", tags=("ubuntu", "cli"),
    ),
    CatalogImage(
        "parrot", "Parrot Security (CLI)", "attacker", "parrotsec/security:latest",
        description="Parrot Security OS, command-line, security tooling included.",
        command="sleep infinity", access="cli", tags=("parrot", "cli"),
    ),
    # --- victims (container) ---
    CatalogImage(
        "dvwa", "DVWA", "victim", "vulnerables/web-dvwa:latest",
        description="Damn Vulnerable Web Application — classic web pentest target.",
        ports=(80,), access="web", tags=("web", "owasp"),
    ),
    CatalogImage(
        "juice-shop", "OWASP Juice Shop", "victim", "bkimminich/juice-shop:latest",
        description="Modern intentionally-vulnerable web app (OWASP).",
        ports=(3000,), access="web", tags=("web", "owasp"),
    ),
    CatalogImage(
        "bwapp", "bWAPP", "victim", "raesene/bwapp:latest",
        description="buggy Web Application — a broad catalogue of web vulnerabilities.",
        ports=(80,), access="web", tags=("web",),
    ),
    # --- victims (VM-only; listed but not deployable on docker-local) ---
    CatalogImage(
        "mr-robot", "Mr. Robot (VulnHub)", "victim", "vulnhub/mr-robot",
        provider_class="vm", available=False, access="web", tags=("vulnhub", "boot2root"),
        note="VulnHub VM image — needs a VM provider (AWS/OpenStack) + the VulnHub "
             "importer (P1-5); not runnable on docker-local.",
    ),
]

_BY_ID = {img.id: img for img in CATALOG}


class CatalogError(ValueError):
    """A custom-arena selection referenced an unknown/incompatible image."""


def list_catalog(kind: str | None = None) -> list[dict]:
    """The catalog as plain dicts (for GET /catalog), optionally filtered."""
    return [
        {
            "id": i.id, "name": i.name, "kind": i.kind, "image": i.image,
            "provider_class": i.provider_class, "description": i.description,
            "ports": list(i.ports), "access": i.access, "available": i.available,
            "note": i.note, "tags": list(i.tags),
        }
        for i in CATALOG
        if kind is None or i.kind == kind
    ]


def get(image_id: str) -> CatalogImage:
    img = _BY_ID.get(image_id)
    if img is None:
        raise CatalogError(f"unknown catalog image '{image_id}' — see GET /catalog")
    return img


def build_custom_scenario(
    name: str,
    attacker: str,
    victims: list[str],
    *,
    segment: str = DEFAULT_SEGMENT,
) -> dict:
    """Compile an operator's picks into a validated v3 scenario dict.

    Raises CatalogError on an unknown id, a wrong-kind pick, a duplicate, or an
    image that isn't deployable on docker-local (VM-only / unavailable).
    """
    if not victims:
        raise CatalogError("pick at least one victim image")

    atk = get(attacker)
    if atk.kind != "attacker":
        raise CatalogError(f"'{attacker}' is not an attacker image")
    _require_container(atk)

    victim_imgs = []
    seen = {atk.id}
    for vid in victims:
        if vid in seen:
            raise CatalogError(f"duplicate image '{vid}' in the selection")
        seen.add(vid)
        vim = get(vid)
        if vim.kind != "victim":
            raise CatalogError(f"'{vid}' is not a victim image")
        _require_container(vim)
        victim_imgs.append(vim)

    raw = {
        "schema": "cyberguard/v3",
        "name": name,
        "title": name,
        "difficulty": "custom",
        "requires": {"provider_class": "container"},
        "network": {"segments": [{"name": segment}]},
        "nodes": [atk.to_node(segment)] + [v.to_node(segment) for v in victim_imgs],
        "agents": [{"stance": "attacker", "node": atk.id}],
    }
    # Validate now so a bad selection fails fast (before anything is queued).
    ScenarioSpec.from_raw(raw)
    return raw


def _require_container(img: CatalogImage) -> None:
    if not img.available or img.provider_class != "container":
        raise CatalogError(
            f"'{img.id}' ({img.name}) is not runnable on docker-local"
            + (f": {img.note}" if img.note else "")
        )
