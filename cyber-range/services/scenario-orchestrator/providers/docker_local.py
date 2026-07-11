"""
docker-local provider: container arenas on the host Docker daemon (ADR-0003).

Compiles a v3 scenario topology to Docker (ROADMAP Phase 1, P1-2): one bridge
network per declared network segment (per arena), one container per node,
attached to the networks of the segments it declares. A node may straddle
several segments; nodes that declare none share a per-arena default bridge.
Everything is tagged with `nidavellir.lab_id` so destroy() can find and remove
an arena without any local state. Deploys take seconds and cost nothing — the
workhorse for laptops, CI end-to-end tests, and cheap agent-test iteration.

Notes:
- `monitor`-role nodes are skipped for now: containerizing the Wazuh SOC is an
  open product question (backlog P7-5).
- Scenarios opt in via `requires.provider_class: container` (or `any`);
  VM-class scenarios are rejected with a clear error instead of a failed pull.
- Needs access to a Docker daemon. In-container workers must mount
  /var/run/docker.sock (root-equivalent on the host — see SECURITY.md).
"""
import io
import logging
import os
import re
import shlex
import shutil
import subprocess  # nosec B404 — fixed argv (no shell), timeout, SSRF-guarded host
import tempfile

import config
import images
import netguard
from providers.base import RangeProvider
from redaction import redact_mapping
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

LABEL_LAB_ID = "nidavellir.lab_id"
LABEL_ROLE = "nidavellir.role"
LABEL_NODE = "nidavellir.node"

# Sentinel segment for nodes that declare none — realized as the per-arena
# default bridge, named WITHOUT a segment suffix so legacy/flat single-network
# scenarios keep their original `nidavellir-<short>` network name.
_DEFAULT_SEGMENT = "_default"

# Keeps tool containers (kali etc.) alive when the scenario doesn't say how.
DEFAULT_ATTACKER_COMMAND = "sleep infinity"

# Portable "block forever" for the no-command victim keepalive (see
# _keepalive_run_args). NOT `sleep infinity`: that needs coreutils >= 8.x, and
# classic targets like Metasploitable ship 6.10 where `sleep infinity` errors out.
# `tail -f /dev/null` blocks on essentially everything (ancient coreutils + busybox).
KEEPALIVE_BLOCK = "tail -f /dev/null"

# Container ports that serve a browser UI, in preference order — the WebUI "Open"
# button must land on the real web server, not whatever port Docker happened to
# bind first. A multi-service box (metasploitable publishes 21/23/445/3306/…
# alongside 80) would otherwise open on FTP. 443/8443 are https; the rest are
# assumed http (best-effort by port number — the scheme isn't probed).
_WEB_PORT_PREFERENCE: tuple[tuple[int, str], ...] = (
    (80, "http"), (443, "https"),
    (8080, "http"), (8000, "http"), (8443, "https"),
    (3000, "http"), (5000, "http"), (8888, "http"),
    (8081, "http"), (9000, "http"), (8090, "http"),
)

# Software-under-test (SUT) arenas, P1-6: a node may build its workload from
# source (ADR-0007). The built image is tagged + labeled per arena so destroy()
# can reclaim it — otherwise a from-source build leaks one image per arena.
_SUT_IMAGE_PREFIX = "nidavellir/sut"

# `service.package` install (M1-4): base image + apt install recipe. Each package
# token is validated against this before it is baked into a Dockerfile RUN, so a
# malicious spec can't inject shell (only `name` or `name=version` is accepted).
_PKG_BASE_IMAGE = os.getenv("NIDAVELLIR_PACKAGE_BASE_IMAGE", "debian:stable-slim")
_PKG_TOKEN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+_-]*(=[a-zA-Z0-9.+:~_-]+)?$")

# White-box source access (SUT arenas, P2-10 safe half; ADR-0007). When a victim
# node's service is `whitebox: true` AND has a `source`, the repo is cloned
# (read-only, pinned to `ref`) into a per-arena docker volume and mounted
# **read-only** into the foothold(s) at `/whitebox/<victim>` — the agent reads
# the source while it tests the running service. Cloning runs nothing from the
# repo (a `git clone` is not code execution — that's why read access is ungated,
# unlike build-from-source). The clone helper has egress only to the git host
# during deploy; the volume is arena-labeled and reclaimed on destroy.
_GIT_HELPER_IMAGE = os.getenv("NIDAVELLIR_GIT_HELPER_IMAGE", "alpine/git:latest")
_WHITEBOX_MOUNT_BASE = "/whitebox"


def _as_git_remote(repo: str) -> str:
    """Normalize an https git URL to the `.git` form the docker daemon recognizes
    as a GIT build context. The daemon treats an https remote as a git repo only
    when its path ends in `.git` (or `<repo.git>#<ref>`); otherwise it downloads
    the URL as a tarball context — a plain `https://github.com/org/repo` then
    returns the repo's HTML page and the build fails. Scheme-less `github.com/…`
    and `git@…`/`git://…` are already git-detected, so they pass through."""
    r = repo.strip().rstrip("/")
    if r.startswith(("git@", "git://")) or r.endswith(".git"):
        return r
    if r.startswith(("http://", "https://")):
        return r + ".git"
    return r  # scheme-less host paths (e.g. github.com/org/repo) are git-detected

# Canonical roles get stable, dashboard-facing output key prefixes (the mock
# provider and WebUI expect these). Other roles are addressed per-node only.
_ROLE_PREFIX = {"attacker": "attack_vm", "victim": "victim_vm", "monitor": "log_vm"}

# Egress containment (ROADMAP P2-3), default-ON. A locked arena's segment
# networks are `internal` — no route to the internet (verified: a node cannot
# reach a public IP). Publishing a host port is silently dropped on an
# `internal` net, so a node that exposes web ports ALSO joins a per-arena
# no-masquerade "ingress" bridge: host->container DNAT works there for the
# operator's browser, while the absence of SNAT keeps egress dead. A scenario
# opts out (e.g. for tooling that must apt-install at runtime) with
# `requires.egress: open`.
_INGRESS_SEGMENT = "ingress"
_NO_MASQUERADE = {"com.docker.network.bridge.enable_ip_masquerade": "false"}

# Allowlisted package mirror (ROADMAP P2-3 / ADR-0005). A locked arena has no
# egress, so a foothold can't `apt`/`pip install` tooling. The mirror sidecar
# fixes that without re-opening egress: it runs on a per-arena bridge that DOES
# have egress, joins each internal segment under the alias `mirror`, and runs an
# allowlisted forward proxy (squid) reachable only from arena clients and only
# for package repos. Footholds get `http_proxy` pointed at it. The proxy is not
# a router, so peers can't tunnel arbitrary traffic — only HTTP(S) to the
# allowlist. ON by default for locked arenas that have a foothold; opt out with
# `requires.mirror: off`.
_MIRROR_SEGMENT = "mirror"           # per-arena egress bridge suffix
# Per-arena NAT bridge for SUT *setup-time* egress (ADR-0007 / P2-10): a victim
# joins it while the configurator brings an arbitrary OSS service up (so it can
# fetch any dependency — git/npm/go/cargo/…), and is disconnected before the
# engagement so the arena runtime stays egress-locked. Arena-labeled → destroy()
# reclaims it.
_SETUP_EGRESS_SEGMENT = "setupgw"
_MIRROR_NODE = "mirror"              # container suffix + DNS alias on segments
_MIRROR_PORT = 3128
_MIRROR_PROXY_URL = f"http://{_MIRROR_NODE}:{_MIRROR_PORT}"
# A foothold points its apt/pip at the mirror proxy — but the attacker's own HTTP
# tools (curl/wget) must reach in-arena victim services DIRECTLY, not via squid
# (which denies anything that isn't a package repo → a confusing 403 on the
# target). Exclude the private ranges (all arena nodes live in 172.16/12, plus
# 10/8 and 192.168/16 for other providers) so target traffic bypasses the proxy
# while external package repos (public IPs) still go through it. curl ≥ 7.86
# matches CIDRs in no_proxy; wget needs `--no-proxy` for the target (documented).
_FOOTHOLD_NO_PROXY = "localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
_MIRROR_IMAGE = "nidavellir/arena-mirror:latest"
# Build context baked into the orchestrator/worker image at /app/infra/...
_MIRROR_CONTEXT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "infra", "arena-mirror"
)


# tcpdump (`-nn -tt`) line: "<ts> IP <src>.<sport> > <dst>.<dport>: Flags ..."
# (ports optional for ICMP/ARP). Parsed into a flow summary for the MITM stance.
_TCPDUMP_RE = re.compile(
    r"IP6?\s+(?P<src>[0-9a-fA-F:.]+?)(?:\.(?P<sport>\d+))?\s+>\s+"
    r"(?P<dst>[0-9a-fA-F:.]+?)(?:\.(?P<dport>\d+))?:\s*(?P<rest>.*)"
)


def _parse_tcpdump(text: str) -> list[dict]:
    """Summarize tcpdump output into ``[{src,dst,proto,sport,dport}]`` flows."""
    flows = []
    for line in (text or "").splitlines():
        m = _TCPDUMP_RE.search(line)
        if not m:
            continue
        rest = m.group("rest") or ""
        proto = ("udp" if "UDP" in rest else "icmp" if "ICMP" in rest
                 else "tcp" if ("Flags" in rest or "ack" in rest or "seq" in rest) else "ip")
        flows.append({
            "src": m.group("src"), "dst": m.group("dst"), "proto": proto,
            "sport": int(m.group("sport")) if m.group("sport") else None,
            "dport": int(m.group("dport")) if m.group("dport") else None,
        })
    return flows


class DockerLocalProvider(RangeProvider):
    name = "docker-local"
    infra_class = "container"

    def __init__(self, client=None):
        # Injectable for tests; lazily resolved so importing this module
        # never requires a running Docker daemon (or the docker package).
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _short(instance_id: str) -> str:
        return instance_id[:8]

    def _network_name(self, instance_id: str, segment: str) -> str:
        base = f"nidavellir-{self._short(instance_id)}"
        return base if segment == _DEFAULT_SEGMENT else f"{base}-{segment}"

    def _container_name(self, instance_id: str, node_name: str) -> str:
        return f"nv-{self._short(instance_id)}-{node_name}"

    @staticmethod
    def _supports(scenario_config: dict) -> bool:
        required = (scenario_config.get("requires") or {}).get("provider_class", "any")
        return required in ("container", "any")

    @staticmethod
    def _node_segments(node: dict) -> list[str]:
        """The segments a node attaches to, defaulting to the shared bridge."""
        return list(node.get("segments") or [_DEFAULT_SEGMENT])

    @staticmethod
    def _is_locked(scenario_config: dict) -> bool:
        """Egress containment is ON unless the scenario opts out
        (`requires.egress: open`)."""
        egress = (scenario_config.get("requires") or {}).get("egress", "none")
        return str(egress).lower() != "open"

    @staticmethod
    def _mirror_enabled(scenario_config: dict) -> bool:
        """The allowlisted package mirror is ON unless the scenario opts out
        (`requires.mirror: off`)."""
        mirror = (scenario_config.get("requires") or {}).get("mirror", "on")
        return str(mirror).lower() not in ("off", "false", "no", "none", "0")

    @staticmethod
    def _is_foothold(node: dict) -> bool:
        """A node an agent operates from (attacker role or explicit entrypoint).
        Only footholds get the package-mirror proxy wired in."""
        return node.get("role") == "attacker" or bool(node.get("entrypoint"))

    # --- interface -----------------------------------------------------------

    def deploy(self, scenario_config, instance_id, user_vars=None):
        if not self._supports(scenario_config):
            return {
                "success": False,
                "error": (
                    "Scenario requires VM-class infrastructure; the "
                    "docker-local provider only runs container scenarios "
                    "(requires.provider_class: container)"
                ),
            }
        if user_vars:
            logger.warning(
                f"[{instance_id}] docker-local ignores user_vars: "
                f"{redact_mapping(user_vars)}"
            )

        labels = {LABEL_LAB_ID: instance_id}

        nodes = []
        for node in normalized_nodes(scenario_config):
            if node.get("role") == "monitor":
                logger.info(
                    f"[{instance_id}] Skipping monitor node {node.get('name')!r} "
                    "(SOC containerization pending — backlog P7-5)"
                )
                continue
            nodes.append(node)

        # One bridge per segment any kept node attaches to. Default segment
        # first so it stays the primary `lab_network`; the rest sorted for
        # deterministic ordering.
        wanted: list[str] = []
        for node in nodes:
            for seg in self._node_segments(node):
                if seg not in wanted:
                    wanted.append(seg)
        wanted.sort(key=lambda s: (s != _DEFAULT_SEGMENT, s))

        locked = self._is_locked(scenario_config)
        needs_ingress = locked and any(node.get("ports") for node in nodes)
        # A contained arena gets an allowlisted package mirror so its foothold
        # can still install tooling. Pointless on an open arena (direct egress
        # already works) or one with nothing to operate from.
        needs_mirror = (
            locked
            and self._mirror_enabled(scenario_config)
            and any(self._is_foothold(node) for node in nodes)
        )

        phase = "init"
        try:
            phase = "create networks"
            networks = {}
            for seg in wanted:
                net_name = self._network_name(instance_id, seg)
                logger.info(
                    f"[{instance_id}] Creating arena network {net_name}"
                    f"{' (internal/no-egress)' if locked else ''}"
                )
                networks[seg] = self.client.networks.create(
                    net_name, driver="bridge", internal=locked, labels=labels
                )

            # Per-arena ingress bridge (no SNAT): lets the operator's browser
            # reach published web ports on a locked arena without giving the
            # node any working egress.
            phase = "create ingress network"
            ingress = None
            if needs_ingress:
                ing_name = self._network_name(instance_id, _INGRESS_SEGMENT)
                logger.info(f"[{instance_id}] Creating ingress network {ing_name} (no egress)")
                ingress = self.client.networks.create(
                    ing_name, driver="bridge", options=_NO_MASQUERADE, labels=labels
                )

            # Bring the package mirror up before the nodes so its `mirror` alias
            # resolves the moment a foothold runs apt/pip.
            phase = "start package mirror"
            mirror = self._run_mirror(instance_id, networks, wanted, labels) if needs_mirror else None

            # White-box source (read-only) must be cloned before the footholds
            # start, since they mount it. Only meaningful with a foothold to read
            # it from.
            phase = "clone white-box sources"
            whitebox = {}
            if any(self._is_foothold(node) for node in nodes):
                whitebox = self._prepare_whitebox_sources(instance_id, nodes, labels)
            elif any(node.get("whitebox") for node in nodes):
                logger.warning(
                    f"[{instance_id}] white-box node(s) declared but no foothold to "
                    "mount the source on — skipping white-box source provisioning"
                )

            # SUT clone-into-box (P2-10 wizard): clone each declared repo read-WRITE
            # into a per-arena volume, mounted into the victim so the configurator
            # (human or HITL agent) can build/run the project in place.
            phase = "clone SUT sources"
            sut_sources = self._prepare_sut_sources(instance_id, nodes, labels)

            phase = "start node containers"
            records = []
            for node in nodes:
                container = self._run_node(
                    instance_id, node, networks, ingress, labels, locked,
                    mirror, whitebox, sut_sources,
                )
                records.append((node, container))

            phase = "collect outputs"
            outputs = self._collect_outputs(instance_id, networks, wanted, records)
            outputs["egress"] = "blocked" if locked else "open"
            # Surface where each white-box source is readable on the foothold(s).
            for victim in whitebox:
                outputs[f"node_{victim}_whitebox_source"] = f"{_WHITEBOX_MOUNT_BASE}/{victim}"
            if mirror is not None:
                # A dead mirror means the foothold can't install tooling — don't
                # report it as healthy (same philosophy as unhealthy_nodes).
                mirror.reload()
                mstate = (mirror.attrs.get("State") or {}).get("Status", "running")
                if mstate == "running":
                    outputs["package_mirror"] = "allowlisted"
                else:
                    outputs["package_mirror"] = "failed"
                    logger.warning(
                        f"[{instance_id}] package mirror is {mstate} right after "
                        f"start — foothold installs will fail. Logs: "
                        f"{self._tail_logs(mirror)}"
                    )
            unhealthy = outputs.get("unhealthy_nodes")
            if unhealthy:
                # Don't pretend the arena is healthy: a node that exited the
                # instant it started (a target with no foreground service, a bad
                # image, a crash-on-boot) is the #1 docker-local gotcha. Surface
                # it loudly rather than reporting a silent, useless success.
                logger.warning(
                    f"[{instance_id}] deployment complete but these nodes exited "
                    f"immediately: {unhealthy} — see node_<name>_state / logs"
                )
            else:
                logger.info(f"[{instance_id}] docker-local deployment complete")
            return {"success": True, "outputs": outputs}

        except Exception as e:
            # Roll back whatever was created so nothing leaks.
            self.destroy(instance_id)
            import docker  # lazy: the SDK is present here (we used self.client above)
            if isinstance(e, (docker.errors.ImageNotFound, docker.errors.NotFound)):
                msg = (
                    f"image could not be pulled — not found on the registry "
                    f"(phase: {phase}): {e}. Use a known logical image "
                    f"(GET /catalog) or fix the tag."
                )
                logger.error(f"[{instance_id}] docker-local deploy failed: {msg}")
                return {"success": False, "error": msg, "phase": phase,
                        "error_kind": "image_not_found"}
            logger.error(f"[{instance_id}] docker-local deploy failed (phase: {phase}): {e}")
            return {"success": False, "error": str(e), "phase": phase,
                    "error_kind": type(e).__name__}

    def _run_node(self, instance_id, node, networks, ingress, labels, locked,
                  mirror=None, whitebox=None, sut_sources=None):
        role = node.get("role", "node")
        segments = self._node_segments(node)
        # Resolve the workload image. Packaged-first (SUT arenas, P1-6): `image`
        # is the effective image from normalized_nodes (a service's published
        # image wins). A build-from-source service (`needs_build`) is built here
        # via the daemon — gated by NIDAVELLIR_ALLOW_SOURCE_BUILD (ADR-0007).
        if node.get("needs_build"):
            image = self._build_service_image(instance_id, node, labels)
        elif not node.get("image"):
            # The schema validator guarantees a workload; defensive only.
            raise ValueError(f"node {node['name']!r} has no runnable image")
        else:
            image = images.resolve(node["image"], self.name)
        has_ports = bool(node.get("ports"))

        # A locked node that publishes ports runs PRIMARY on the no-masquerade
        # ingress bridge (publishing is silently dropped on an `internal` net),
        # then joins its segment(s) for inter-node traffic — egress stays dead.
        # Otherwise it runs on its first segment as before.
        if locked and has_ports and ingress is not None:
            run_net = ingress.name
            attach = segments
        else:
            run_net = networks[segments[0]].name
            attach = segments[1:]

        run_kwargs = {
            "image": image,
            "name": self._container_name(instance_id, node["name"]),
            "detach": True,
            "network": run_net,
            "labels": {**labels, LABEL_ROLE: role, LABEL_NODE: node["name"]},
        }

        command = node.get("command")
        if command is None and self._is_foothold(node):
            command = DEFAULT_ATTACKER_COMMAND
        if command is not None:
            run_kwargs["command"] = command
        elif not node.get("needs_build"):
            # Liveness guardrail (generic — no image allowlist). A container is
            # reaped the instant its foreground process exits, and Nidavellir
            # deploys headlessly (detached, no TTY). Any target whose image starts
            # daemons then returns — or ends in an interactive shell — therefore
            # dies on boot (the classic 'VM-in-a-container' failure: metasploitable,
            # many imported CVE boxes, a bare OS image, …), often a few seconds in,
            # so an immediate health check can even see a misleading 'running'.
            # Re-run the image's OWN entrypoint+cmd and THEN block, so the box
            # stays up regardless of which image the operator/generator chose.
            # Transparent to a real foreground service (its server blocks, so the
            # trailing blocker is never reached). Skipped for footholds (handled
            # above) and from-source builds (the operator's Dockerfile owns CMD).
            # An explicit `command` from the author/generator always wins.
            run_kwargs.update(self._keepalive_run_args(instance_id, image))

        # The node's own environment (e.g. a Vulhub CVE env's compose `environment`).
        environment = {str(k): str(v) for k, v in (node.get("environment") or {}).items()}

        # Point a foothold's apt/pip at the allowlisted mirror. Set in the
        # container config so `docker exec` sessions inherit it too. NO_PROXY
        # keeps loopback/intra-arena traffic off the proxy. Merged on TOP of the
        # node env so the foothold's proxy settings always win.
        if mirror is not None and self._is_foothold(node):
            environment.update({
                "http_proxy": _MIRROR_PROXY_URL,
                "https_proxy": _MIRROR_PROXY_URL,
                "HTTP_PROXY": _MIRROR_PROXY_URL,
                "HTTPS_PROXY": _MIRROR_PROXY_URL,
                # In-arena (private-range) targets bypass the proxy → the attacker
                # reaches victim services directly; external repos still proxied.
                "no_proxy": _FOOTHOLD_NO_PROXY,
                "NO_PROXY": _FOOTHOLD_NO_PROXY,
            })
        if environment:
            run_kwargs["environment"] = environment

        # Mount white-box source read-only into the foothold so the agent can
        # read it while testing the running service from here (SUT arenas).
        if whitebox and self._is_foothold(node):
            run_kwargs["volumes"] = {
                vol: {"bind": f"{_WHITEBOX_MOUNT_BASE}/{victim}", "mode": "ro"}
                for victim, vol in whitebox.items()
            }

        # Mount this node's SUT source read-WRITE so the configurator can build
        # and run the open-source project in place (SUT clone-into-box wizard).
        if sut_sources and node["name"] in sut_sources:
            vol, path = sut_sources[node["name"]]
            run_kwargs.setdefault("volumes", {})[vol] = {"bind": path, "mode": "rw"}

        # Publish declared service ports on random host ports so the operator's
        # browser can reach e.g. DVWA (via the ingress bridge when locked).
        if has_ports:
            run_kwargs["ports"] = {f"{p}/tcp": None for p in node["ports"]}

        logger.info(
            f"[{instance_id}] Starting node {node['name']!r} ({role}): {image}"
        )
        container = self.client.containers.run(**run_kwargs)

        # Attach to the remaining segments this node straddles.
        for seg in attach:
            networks[seg].connect(container)

        # With a mirror, normalize a foothold's apt to the allowlisted direct
        # CDN (the default Kali host is a redirector to mirrors we can't allow).
        if mirror is not None and self._is_foothold(node):
            self._pin_foothold_repos(container)
        return container

    def _inspect_image(self, image):
        """The local image object, pulling it first if absent so its config is
        inspectable before we run it. (containers.run would auto-pull, but the
        keepalive wrap needs the image's own ENTRYPOINT/CMD up front.)"""
        try:
            return self.client.images.get(image)
        except Exception:  # noqa: BLE001 - not present locally yet
            logger.info(f"pulling image {image} to inspect its startup")
            pulled = self.client.images.pull(image)
            return pulled[0] if isinstance(pulled, list) else pulled

    def _keepalive_run_args(self, instance_id, image) -> dict:
        """Run kwargs that keep a no-command victim alive headlessly: re-run the
        image's OWN ENTRYPOINT+CMD (so a real service still comes up the normal
        way), then block forever. The original startup is read from the image
        config — never hardcoded or allowlisted — so it works for ANY image the
        operator/generator picks. For a foreground service the original blocks and
        the trailing blocker is never reached (transparent); for a daemonize-then-
        exit image the blocker keeps the box up. On any inspection failure we fall
        back to a bare blocker: the box stays reachable even if its service didn't
        start (a dead-service-but-reachable box is diagnosable; a vanished one is
        the silent failure we're fixing)."""
        orig = ""
        try:
            cfg = (self._inspect_image(image).attrs or {}).get("Config") or {}
            parts = list(cfg.get("Entrypoint") or []) + list(cfg.get("Cmd") or [])
            orig = shlex.join(parts) if parts else ""
        except Exception as e:  # noqa: BLE001 - degrade to a bare keepalive
            logger.warning(
                f"[{instance_id}] keepalive: could not inspect {image!r} startup "
                f"({e}); using a bare blocker"
            )
        # Run the original (if any), THEN block — `;` not `&&`, so the box stays up
        # even if the startup exits non-zero. `exec` hands PID control to the
        # blocker so `docker stop` signals it directly.
        script = f"{orig}; exec {KEEPALIVE_BLOCK}" if orig else f"exec {KEEPALIVE_BLOCK}"
        logger.info(
            f"[{instance_id}] keepalive wrap on {image!r}: re-run its startup then "
            f"block, so the victim can't die on a headless boot"
        )
        # Override the entrypoint with our wrapper and clear command so the image's
        # own CMD isn't re-appended (it is already folded into `script`).
        return {"entrypoint": ["/bin/sh", "-c", script], "command": []}

    def _build_service_image(self, instance_id, node, labels):
        """Build a node's workload from source (SUT arenas, P1-6; ADR-0007).

        **OFF by default** — building an arbitrary repo runs third-party code at
        BUILD time (Dockerfile RUN), strictly more dangerous than pulling a
        published image — so it requires NIDAVELLIR_ALLOW_SOURCE_BUILD=true.

        Builds via the daemon (BuildKit) with a **remote git context**, so there
        is no local checkout and no `git` binary needed here; the ``#<ref>``
        fragment pins the source for reproducibility. **Build-time network is
        open** (apt/pip/npm/go mod) by design — the arena *runtime* stays
        egress-locked regardless. The built image is tagged + arena-labeled so
        destroy() reclaims it. Returns the concrete local tag to run.
        """
        if not config.ALLOW_SOURCE_BUILD:
            raise ValueError(
                f"node {node['name']!r} declares a build-from-source service, but "
                "source builds are disabled (building untrusted code executes it "
                "at build time). Enable explicitly with NIDAVELLIR_ALLOW_SOURCE_"
                "BUILD=true (see SECURITY.md), or supply a packaged `service.image`"
            )
        service = node.get("service") or {}
        source = service.get("source")
        if not source:
            package = service.get("package")
            if package:
                return self._build_package_image(instance_id, node, package, labels)
            raise ValueError(
                f"node {node['name']!r}: service needs a `source`, `package`, or a "
                "packaged `image`"
            )
        repo = source.get("repo")
        if not repo:
            raise ValueError(f"node {node['name']!r}: service.source needs a `repo`")
        netguard.assert_public_host(repo)  # SSRF guard before the daemon fetches it
        ref = source.get("ref")
        subdir = source.get("context")
        dockerfile = source.get("dockerfile") or "Dockerfile"

        # Daemon-side remote git context: "<repo.git>#<ref>:<subdir>". The daemon
        # only treats an https remote as a GIT repo when the path ends in `.git`
        # (else it fetches the URL as a tarball context — a plain GitHub URL then
        # returns the repo's HTML page and the build fails). Normalize to the
        # `.git` form so any https git URL builds. The repo is operator-authored
        # (authoring the scenario is the approval); pin `ref` for reproducibility.
        git_repo = _as_git_remote(repo)
        if ref and subdir:
            remote = f"{git_repo}#{ref}:{subdir}"
        elif ref:
            remote = f"{git_repo}#{ref}"
        elif subdir:
            remote = f"{git_repo}#:{subdir}"
        else:
            remote = git_repo
            logger.warning(
                f"[{instance_id}] node {node['name']!r} builds from {repo} with "
                "no pinned source.ref — not reproducible (pin a commit/tag)"
            )

        tag = f"{_SUT_IMAGE_PREFIX}:{self._short(instance_id)}-{node['name']}"
        logger.info(
            f"[{instance_id}] Building SUT image {tag} for node {node['name']!r} "
            f"from {remote} (dockerfile={dockerfile}); build-time egress is OPEN"
        )
        image_obj, _logs = self.client.images.build(
            path=remote,
            dockerfile=dockerfile,
            tag=tag,
            rm=True,
            forcerm=True,
            pull=True,
            labels=dict(labels),
            timeout=config.SOURCE_BUILD_TIMEOUT,
        )
        return image_obj.tags[0] if getattr(image_obj, "tags", None) else tag

    def _build_package_image(self, instance_id, node, package, labels):
        """Install `service.package` on a base image (SUT arenas, P1-6 / M1-4).

        A lighter build than from-source: no repo, just apt-install the named
        package(s) on ``_PKG_BASE_IMAGE`` and bake a pinned, arena-labeled image
        (reclaimed by destroy()). Each whitespace-separated token must be a bare
        package name or ``name=version`` — validated so nothing can inject into
        the Dockerfile RUN. Built via a context-free ``fileobj`` build. Still gated
        by ALLOW_SOURCE_BUILD (apt runs as root at build time) and, like all builds,
        build-time egress is open while the arena runtime stays locked."""
        tokens = str(package).split()
        for tok in tokens:
            if not _PKG_TOKEN_RE.match(tok):
                raise ValueError(
                    f"node {node['name']!r}: invalid package spec {tok!r} — only "
                    "'name' or 'name=version' tokens are allowed"
                )
        if not tokens:
            raise ValueError(f"node {node['name']!r}: service.package is empty")
        if not any("=" in t for t in tokens):
            logger.warning(
                f"[{instance_id}] node {node['name']!r} installs {tokens} with no "
                "pinned version — not reproducible (use 'name=version')"
            )
        pkgs = " ".join(tokens)
        dockerfile = (
            f"FROM {_PKG_BASE_IMAGE}\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            f"{pkgs} && rm -rf /var/lib/apt/lists/*\n"
        )
        tag = f"{_SUT_IMAGE_PREFIX}:{self._short(instance_id)}-{node['name']}"
        logger.info(
            f"[{instance_id}] Building package image {tag} for node {node['name']!r} "
            f"({pkgs} on {_PKG_BASE_IMAGE}); build-time egress is OPEN"
        )
        image_obj, _logs = self.client.images.build(
            fileobj=io.BytesIO(dockerfile.encode()),
            tag=tag, rm=True, forcerm=True, pull=True,
            labels=dict(labels), timeout=config.SOURCE_BUILD_TIMEOUT,
        )
        return image_obj.tags[0] if getattr(image_obj, "tags", None) else tag

    def verify_build_dockerfile(self, repo, ref, dockerfile_text, *, timeout=None) -> tuple[bool, str]:
        """VERIFICATION build for LLM Dockerfile synthesis (M1-3, ADR-0008 tier-3;
        Repo2Run). Shallow-clone ``repo`` into a temp context, drop the candidate
        ``dockerfile_text`` in it, and try to build it. Returns ``(ok, logs)`` — the
        log tail feeds the model's next fix attempt. The image is **removed after**
        (this only proves buildability; the deploy build is separate), the temp
        context is always cleaned up, and build-time egress is open (as for
        `_build_service_image`; the arena runtime stays locked). Never raises —
        a build failure is a normal ``(False, logs)`` result for the loop.

        Gated by ALLOW_SOURCE_BUILD (building untrusted code executes it), same as
        the from-source path. SSRF-guarded before the clone."""
        if not config.ALLOW_SOURCE_BUILD:
            return False, ("source builds are disabled — set NIDAVELLIR_ALLOW_SOURCE_"
                           "BUILD=true to synthesize + verify a Dockerfile")
        try:
            netguard.assert_public_host(repo)
        except netguard.UnsafeHostError as e:
            return False, f"unsafe repo host: {e}"
        tmp = tempfile.mkdtemp(prefix="nv-synthbuild-")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        clone_timeout = min(timeout or config.SOURCE_BUILD_TIMEOUT, 300)
        try:
            argv = ["git", "clone", "--quiet", "--depth", "1", "--no-tags"]
            if ref:
                argv += ["--branch", ref]
            argv += ["--", _as_git_remote(repo), tmp]
            proc = subprocess.run(  # nosec B603 — fixed argv, no shell, timeout, guarded host
                argv, capture_output=True, timeout=clone_timeout, env=env, text=True,
            )
            if proc.returncode != 0:
                return False, f"git clone failed: {proc.stderr.strip()[-1500:]}"
            # Write the candidate under a name that won't clobber repo files.
            df_name = "Dockerfile.nidavellir-synth"
            with open(os.path.join(tmp, df_name), "w", encoding="utf-8") as fh:
                fh.write(dockerfile_text)
            tag = f"{_SUT_IMAGE_PREFIX}:synthverify-{os.path.basename(tmp)[-8:]}"
            image_obj = None
            try:
                import docker  # lazy: the SDK is present (used elsewhere in this class)

                image_obj, log_stream = self.client.images.build(
                    path=tmp, dockerfile=df_name, tag=tag, rm=True, forcerm=True,
                    pull=True, timeout=(timeout or config.SOURCE_BUILD_TIMEOUT),
                )
                # Drain the log stream to a string (also confirms completion).
                logs = "".join(
                    chunk.get("stream", "") for chunk in log_stream
                    if isinstance(chunk, dict)
                )
                return True, logs[-4000:]
            except docker.errors.BuildError as e:
                logs = "".join(
                    (c.get("stream") or c.get("error") or "")
                    for c in (e.build_log or []) if isinstance(c, dict)
                )
                return False, (logs or str(e))[-4000:]
            except docker.errors.APIError as e:
                return False, f"docker build error: {e}"
            finally:
                if image_obj is not None:
                    try:
                        self.client.images.remove(image_obj.id, force=True)
                    except Exception:  # noqa: BLE001 — best-effort cleanup
                        logger.warning("could not remove synth-verify image %s", tag)
        except (subprocess.SubprocessError, OSError) as e:
            return False, f"synthesis build setup failed: {e}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # Kali's default `http.kali.org` is a MirrorBrain redirector that 302s to
    # rotating community mirrors the allowlist can't cover; `kali.download` (the
    # official CDN) serves directly and IS allowlisted. Rewrite both the DEB822
    # (`.sources`) and classic (`.list`) forms. No-op on images without them.
    _APT_PIN_SCRIPT = (
        r"sed -i -E 's#(https?://)(http\.)?kali\.org/#\1kali.download/#g' "
        "/etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list "
        "/etc/apt/sources.list 2>/dev/null || true"
    )

    def _pin_foothold_repos(self, container):
        """Point a foothold's apt at the allowlisted direct CDN. Best-effort —
        a foothold is still useful (pip, already-direct Debian/Ubuntu) if this
        no-ops on an unfamiliar image."""
        try:
            container.exec_run(["sh", "-c", self._APT_PIN_SCRIPT])
        except Exception as e:
            logger.warning(f"apt-source pin on {container.name} failed (non-fatal): {e}")

    def _ensure_mirror_image(self):
        """Build the arena-mirror image on first use (cached thereafter). The
        build context is baked into this service image at `infra/arena-mirror`."""
        try:
            self.client.images.get(_MIRROR_IMAGE)
            return
        except Exception:
            pass
        logger.info(f"Building arena mirror image {_MIRROR_IMAGE} from {_MIRROR_CONTEXT}")
        self.client.images.build(path=_MIRROR_CONTEXT, tag=_MIRROR_IMAGE, rm=True)

    def _run_mirror(self, instance_id, networks, wanted, labels):
        """Start the allowlisted package proxy for a contained arena. It runs on
        a per-arena egress bridge (so it can reach the package repos) and joins
        every internal segment under the alias `mirror` (so footholds reach it)."""
        self._ensure_mirror_image()
        egress_name = self._network_name(instance_id, _MIRROR_SEGMENT)
        logger.info(f"[{instance_id}] Creating mirror egress bridge {egress_name}")
        egress_net = self.client.networks.create(
            egress_name, driver="bridge", internal=False, labels=labels
        )
        logger.info(f"[{instance_id}] Starting allowlisted package mirror")
        container = self.client.containers.run(
            image=_MIRROR_IMAGE,
            name=self._container_name(instance_id, _MIRROR_NODE),
            detach=True,
            network=egress_net.name,
            labels={**labels, LABEL_ROLE: "mirror", LABEL_NODE: _MIRROR_NODE},
        )
        # Reachable as `mirror` on each internal arena segment.
        for seg in wanted:
            networks[seg].connect(container, aliases=[_MIRROR_NODE])
        return container

    def _prepare_whitebox_sources(self, instance_id, nodes, labels) -> dict:
        """Clone each white-box node's source into a per-arena read-only volume.

        Returns ``{victim_node_name: volume_name}`` for the footholds to mount.
        A white-box node with no `service.source` keeps the prior behaviour (the
        `whitebox` flag is still surfaced) but gets no mounted source — warned,
        not failed, so a packaged-image + `whitebox` flag arena still deploys.
        """
        mounts: dict[str, str] = {}
        for node in nodes:
            if not node.get("whitebox"):
                continue
            source = (node.get("service") or {}).get("source") or {}
            if not source.get("repo"):
                logger.warning(
                    f"[{instance_id}] node {node['name']!r} is white-box but has no "
                    "service.source repo — no source mounted for the agent"
                )
                continue
            vol_name = f"nv-{self._short(instance_id)}-src-{node['name']}"
            self._clone_source_into_volume(instance_id, vol_name, source, labels)
            mounts[node["name"]] = vol_name
        return mounts

    def _prepare_sut_sources(self, instance_id, nodes, labels) -> dict:
        """Clone each SUT node's repo read-WRITE into a per-arena volume (P2-10
        wizard). Returns ``{node_name: (volume_name, mount_path)}`` for `_run_node`
        to mount. Unlike white-box (read-only into the foothold), the SUT source is
        mounted **into the victim itself** so the configurator builds/runs it in
        place. `git clone` runs nothing from the repo (read, not execution), so the
        clone itself is ungated — the same reasoning as white-box source."""
        mounts: dict[str, tuple[str, str]] = {}
        for node in nodes:
            clone = node.get("sut_clone")
            if not clone or not clone.get("repo"):
                continue
            vol_name = f"nv-{self._short(instance_id)}-sut-{node['name']}"
            self._clone_source_into_volume(
                instance_id, vol_name,
                {"repo": clone["repo"], "ref": clone.get("ref")}, labels,
            )
            path = clone.get("path") or f"/opt/{node['name']}"
            mounts[node["name"]] = (vol_name, path)
        return mounts

    def _clone_source_into_volume(self, instance_id, vol_name, source, labels):
        """Clone a repo (read-only, pinned to `ref`) into a labeled docker volume
        via a short-lived helper. The helper runs on the default bridge (egress
        to the git host only — never the locked arena net) and `git clone` runs
        nothing from the repo. `repo`/`ref` are passed as env and referenced
        quoted, so an odd value cannot inject into the helper shell."""
        repo = source["repo"]
        ref = source.get("ref") or ""
        # SSRF guard (authoritative, resolves the host): the repo is user-supplied
        # and the clone helper has egress — reject internal/metadata/loopback hosts.
        netguard.assert_public_host(repo)
        logger.info(
            f"[{instance_id}] Cloning white-box source {repo}"
            f"{('@' + ref) if ref else ''} into volume {vol_name}"
        )
        self.client.volumes.create(name=vol_name, labels=dict(labels))
        # Full clone (not shallow) so checking out an arbitrary commit SHA works;
        # .git is kept (commit history is useful for white-box source review).
        script = (
            'set -e; git clone --quiet -- "$REPO" /src; '
            'if [ -n "$REF" ]; then git -C /src checkout --quiet "$REF"; fi'
        )
        try:
            self.client.containers.run(
                image=_GIT_HELPER_IMAGE,
                entrypoint="/bin/sh",
                command=["-c", script],
                environment={"REPO": repo, "REF": ref},
                volumes={vol_name: {"bind": "/src", "mode": "rw"}},
                labels=dict(labels),
                detach=False,
                remove=True,
            )
        except Exception as e:
            raise RuntimeError(
                f"white-box source clone failed for {repo}: {e}"
            ) from e

    @staticmethod
    def _published_ports(container) -> dict:
        """{container_port:int -> host_port:str} for every published TCP port."""
        mapping = {}
        for key, bindings in (container.attrs["NetworkSettings"].get("Ports") or {}).items():
            if not bindings:
                continue
            cport, _, proto = key.partition("/")
            if proto and proto != "tcp":
                continue
            try:
                mapping[int(cport)] = bindings[0]["HostPort"]
            except (ValueError, KeyError, IndexError):
                continue
        return mapping

    @staticmethod
    def _parse_listening_ports(proc_net_tcp: str) -> set:
        """LISTEN local ports parsed from concatenated /proc/net/tcp{,6} content.
        Each row's 2nd column is `HEXADDR:HEXPORT` and the 4th (st) is `0A` for
        LISTEN. Robust to the header row and to IPv4+IPv6 in one blob."""
        ports: set[int] = set()
        for line in proc_net_tcp.splitlines():
            cols = line.split()
            if len(cols) < 4 or cols[3] != "0A":  # 0A = TCP_LISTEN
                continue
            hexport = cols[1].rsplit(":", 1)[-1]
            try:
                ports.add(int(hexport, 16))
            except ValueError:
                continue
        return ports

    def _listening_ports(self, container) -> set | None:
        """The set of TCP ports the container is actually LISTENING on, read from
        `/proc/net/tcp{,6}` via exec. Returns None when it can't be determined (no
        shell/cat, exec error) so the caller falls back to preference order — the
        worker runs in its own netns and can't reach the arena's published ports,
        so a socket probe would be useless; reading the container's own /proc is
        the reliable signal."""
        try:
            res = container.exec_run(["cat", "/proc/net/tcp", "/proc/net/tcp6"])
            code = getattr(res, "exit_code", res[0] if isinstance(res, tuple) else None)
            output = getattr(res, "output", res[1] if isinstance(res, tuple) else b"")
            if code not in (0, None):
                return None
            text = output.decode("utf-8", "replace") if isinstance(output, bytes) else str(output)
            return self._parse_listening_ports(text)
        except Exception:  # noqa: BLE001 — best-effort; any failure → fall back
            return None

    @staticmethod
    def _browser_target(published: dict, listening: set | None = None):
        """(host_port, scheme) the browser 'Open' should hit — the actual web
        server — or None when no recognizable web port is published (so a non-web
        box like an FTP/SMB target gets no bogus Open URL).

        A target can EXPOSE web ports it does not actually serve (e.g. a repo whose
        Dockerfile/README declares both 80 and 8000 but listens only on 8000, or
        introspection guessing a port from README prose). When ``listening`` (the
        container's actual LISTEN ports) is known, prefer a web port that is really
        being served, by preference order; fall back to plain preference order when
        that's unknown or none match — unchanged for single-port targets."""
        candidates = [(cport, scheme) for cport, scheme in _WEB_PORT_PREFERENCE
                      if cport in published]
        if not candidates:
            return None
        if listening:
            for cport, scheme in candidates:
                if cport in listening:
                    return published[cport], scheme
        cport, scheme = candidates[0]
        return published[cport], scheme

    def _collect_outputs(self, instance_id, networks, wanted, records) -> dict:
        outputs = {
            "provider": self.name,
            "lab_network": networks[wanted[0]].name if wanted else None,
            "lab_networks": [networks[s].name for s in wanted],
        }

        seen_roles = set()
        unhealthy = []
        for node, container in records:
            container.reload()  # IP/ports/state are only populated after start
            role = node.get("role", "node")
            name = node["name"]
            primary_net = networks[self._node_segments(node)[0]].name

            # Liveness: a node that already exited (a target with no foreground
            # service, a crash-on-boot, a bad image) is the #1 docker-local
            # gotcha. Record its state so a dead box is diagnosable, not silent.
            state = (container.attrs.get("State") or {}).get("Status", "running")
            outputs[f"node_{name}_state"] = state
            if state != "running":
                unhealthy.append(name)
                logger.warning(
                    f"[{instance_id}] node {name!r} ({role}) is {state} right "
                    f"after start — last logs: {self._tail_logs(container)}"
                )

            nets = container.attrs["NetworkSettings"]["Networks"]
            ip = nets.get(primary_net, {}).get("IPAddress", "")
            ssh = f"docker exec -it {container.name} /bin/bash"
            is_foothold = role == "attacker" or bool(node.get("entrypoint"))

            # Map published ports → host ports, then point the browser "Open" URL
            # at the actual WEB port (80/443/8080/…), not whatever Docker bound
            # first — a multi-service box (metasploitable) would otherwise open on
            # FTP. `floating` is the reachable host:port (the web mapping when there
            # is one, else the first published port so it's still visible).
            published = self._published_ports(container)
            # Prefer a web port the container actually listens on (a target may
            # EXPOSE ports it doesn't serve, or introspection may have guessed one
            # from the README) — read its own /proc, since the worker can't reach
            # the arena's published ports from its netns.
            target = self._browser_target(published, listening=self._listening_ports(container))
            floating = url = None
            if target:
                host_port, scheme = target
                floating = f"127.0.0.1:{host_port}"
                url = f"{scheme}://127.0.0.1:{host_port}"
            elif published:
                floating = f"127.0.0.1:{next(iter(published.values()))}"

            # Per-node outputs — always emitted, so repeated roles and N-node
            # topologies are fully addressable.
            outputs[f"node_{name}_name"] = container.name
            outputs[f"node_{name}_private_ip"] = ip
            if node.get("whitebox"):
                outputs[f"node_{name}_whitebox"] = True
            # SUT victim: surface the clone path + a connect command so a human
            # operator can `docker exec` in to build the project (the box is a
            # victim, not a foothold — `_setup_shell` is a distinct key so it is
            # NOT mistaken for an attacker foothold by the scope derivation).
            if node.get("sut_clone"):
                clone = node["sut_clone"]
                outputs[f"node_{name}_sut_source"] = clone.get("path") or f"/opt/{name}"
                outputs[f"node_{name}_setup_shell"] = f"docker exec -it {container.name} /bin/bash"
            if is_foothold:
                outputs[f"node_{name}_ssh_command"] = ssh
            if floating:
                outputs[f"node_{name}_floating_ip"] = floating
            if url:
                outputs[f"node_{name}_url"] = url
            if published:
                # All published mappings (container→host) so the operator can also
                # reach non-web services on a multi-port box (FTP/SMB/MySQL/…).
                outputs[f"node_{name}_ports"] = {
                    str(c): h for c, h in sorted(published.items())
                }

            # Legacy role-prefixed outputs for the FIRST node of each canonical
            # role (the dashboard + mock-parity contract).
            prefix = _ROLE_PREFIX.get(role)
            if prefix and role not in seen_roles:
                seen_roles.add(role)
                outputs[f"{prefix}_private_ip"] = ip
                outputs[f"{prefix}_name"] = container.name
                if is_foothold:
                    outputs[f"{prefix}_ssh_command"] = ssh
                if floating:
                    outputs[f"{prefix}_floating_ip"] = floating
                if url and role == "victim":
                    outputs["victim_web_url"] = url

        if unhealthy:
            outputs["unhealthy_nodes"] = unhealthy
        return outputs

    @staticmethod
    def _tail_logs(container, limit: int = 500) -> str:
        """Best-effort last log lines from a (likely exited) container."""
        try:
            raw = container.logs(tail=20)
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            return text.strip()[-limit:]
        except Exception:
            return "<no logs>"

    # Cap captured output so a chatty command can't blow up the payload/DB.
    EXEC_OUTPUT_CAP = 65536

    def exec_in_node(self, instance_id, node, command, timeout=30):
        container = self._find_node_container(instance_id, node)
        if container is None:
            return {"success": False, "error": f"node {node!r} not found in arena {instance_id}"}
        try:
            # `timeout` (coreutils/busybox) bounds the command inside the
            # container — the SDK's exec has no native timeout. `sh -c` gives
            # the agent a normal shell.
            exit_code, output = container.exec_run(
                ["timeout", str(int(timeout)), "sh", "-c", command], demux=True
            )
        except Exception as e:
            logger.error(f"[{instance_id}] exec on {node} failed: {e}")
            return {"success": False, "error": str(e)}

        stdout, stderr = output if isinstance(output, tuple) else (output, None)
        return {
            "success": True,
            "exit_code": exit_code,
            "stdout": self._decode(stdout),
            "stderr": self._decode(stderr),
        }

    def _find_node_container(self, instance_id, node):
        name = self._container_name(instance_id, node)
        try:
            return self.client.containers.get(name)
        except Exception:
            # Fall back to the node label (handles any naming drift).
            matches = self.client.containers.list(
                all=True, filters={"label": f"{LABEL_LAB_ID}={instance_id}"}
            )
            return next((c for c in matches if c.labels.get(LABEL_NODE) == node), None)

    def set_node_egress(self, instance_id, node, open):
        """Open/close a node's internet egress for the SUT setup phase (ADR-0007).

        Opening connects the node to a per-arena NAT bridge — full egress, so the
        configurator can fetch dependencies from anywhere (git, npm, go, cargo,
        distro repos, …) for the diversity of real OSS targets. Closing
        disconnects it. The bridge is arena-labeled, so destroy() reclaims it and
        the arena runtime returns to egress-locked. Idempotent."""
        import docker

        container = self._find_node_container(instance_id, node)
        if container is None:
            return {"success": False, "error": f"node {node!r} not found in arena {instance_id}"}
        net_name = self._network_name(instance_id, _SETUP_EGRESS_SEGMENT)

        try:
            if open:
                net = self._ensure_setup_egress_net(instance_id, net_name)
                try:
                    net.connect(container)
                except docker.errors.APIError:
                    pass  # already attached → idempotent
                # Make the NAT bridge the DEFAULT route. A victim that publishes a
                # port runs primary on the no-masquerade ingress bridge, whose
                # gateway otherwise wins the default route — so the NAT bridge is
                # attached but never carries outbound traffic (apt/npm time out).
                self._set_default_route(container, self._net_gateway(net))
                logger.info(f"[{instance_id}] setup egress OPEN for node {node!r}")
                return {"success": True, "egress": "open", "network": net_name}
            # close
            try:
                self.client.networks.get(net_name).disconnect(container, force=True)
            except docker.errors.NotFound:
                pass  # bridge (or container's attachment) gone → already closed
            except docker.errors.APIError as e:
                # Could be a benign "not attached" OR a real failure. Don't assume
                # success — a false "closed" leaves the victim on the egress bridge
                # with full internet into the engagement (a containment hole). Verify.
                logger.info(f"[{instance_id}] disconnect APIError on {node!r}: {e} — verifying")
            # Verify the node is genuinely off the egress bridge before reporting closed.
            try:
                container.reload()
                attached = net_name in (
                    (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
                )
            except Exception as e:  # noqa: BLE001 - if we can't verify, fail closed (report failure)
                return {"success": False, "error": f"could not verify egress revoke on {node!r}: {e}"}
            if attached:
                return {
                    "success": False,
                    "error": f"egress revoke failed: {node!r} is still attached to {net_name}",
                }
            # Restore the default route to the (no-egress) ingress bridge so the
            # arena runtime returns to its locked state with inbound still working.
            # A victim with no ingress bridge is simply left without a default
            # route — pure containment, intra-arena reachable via direct routes.
            self._set_default_route(container, self._ingress_gateway(container))
            logger.info(f"[{instance_id}] setup egress CLOSED for node {node!r}")
            return {"success": True, "egress": "closed"}
        except Exception as e:
            logger.error(f"[{instance_id}] set_node_egress({node!r}, open={open}) failed: {e}")
            return {"success": False, "error": str(e)}

    def _ensure_setup_egress_net(self, instance_id, net_name):
        import docker

        try:
            return self.client.networks.get(net_name)
        except docker.errors.NotFound:
            logger.info(f"[{instance_id}] creating setup-egress NAT bridge {net_name}")
            return self.client.networks.create(
                net_name, driver="bridge", internal=False,
                labels={LABEL_LAB_ID: instance_id},
            )

    # --- default-route management for setup egress ---------------------------
    # The SUT base image (ubuntu) ships no `iproute2`, and a port-publishing
    # victim runs primary on the no-masquerade ingress bridge whose gateway wins
    # the default route. So we set the route from a short-lived privileged sidecar
    # that shares the victim's network namespace (busybox `ip` from the already-
    # present git-helper image). Inbound published-port traffic is unaffected —
    # replies follow the directly-connected ingress subnet, not the default route.
    _IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

    @classmethod
    def _is_ipv4(cls, value) -> bool:
        return isinstance(value, str) and bool(cls._IPV4_RE.match(value))

    def _net_gateway(self, net) -> str | None:
        """The IPv4 gateway of a docker network (its NAT bridge gateway)."""
        try:
            net.reload()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        for cfg in ((net.attrs.get("IPAM") or {}).get("Config") or []):
            gw = cfg.get("Gateway")
            if self._is_ipv4(gw):
                return gw
        return None

    def _ingress_gateway(self, container) -> str | None:
        """The container's no-egress ingress-bridge gateway (where published ports
        live), to restore as the default route when setup egress is revoked."""
        try:
            container.reload()
            nets = (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        except Exception:  # noqa: BLE001
            return None
        for name, cfg in nets.items():
            if name.endswith(f"-{_INGRESS_SEGMENT}") and self._is_ipv4(cfg.get("Gateway")):
                return cfg["Gateway"]
        return next((c.get("Gateway") for c in nets.values() if self._is_ipv4(c.get("Gateway"))), None)

    def _set_default_route(self, container, gateway) -> None:
        """Replace the container's default route via `gateway` from a privileged
        netns-sharing sidecar (the victim image has no `ip`). Best-effort: a
        failure leaves the NAT bridge attached, so egress may still work if the
        bridge already won the default route. `gateway` is a docker-assigned IP
        (not user input); validated as IPv4 before use."""
        if not self._is_ipv4(gateway):
            return
        try:
            self.client.containers.run(
                image=_GIT_HELPER_IMAGE,
                entrypoint="sh",
                command=["-c", f"ip route del default 2>/dev/null; ip route add default via {gateway}"],
                network_mode=f"container:{container.id}",
                cap_add=["NET_ADMIN"],
                remove=True,
                detach=False,
            )
        except Exception as e:  # noqa: BLE001 - best-effort route fix
            logger.warning(f"could not set default route via {gateway} on {container.name}: {e}")

    @classmethod
    def _decode(cls, raw) -> str:
        if not raw:
            return ""
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        return text[: cls.EXEC_OUTPUT_CAP]

    # How much of each container's log tail the monitor reads per tick. Bounded
    # so a chatty target can't blow up the collection payload; the scan keeps only
    # the matching lines. ~200 lines is enough to catch a crash/abort footer.
    _MONITOR_LOG_TAIL_LINES = 200
    _MONITOR_LOG_CHARS = 8000
    # Container roles/nodes that are NOT the service-under-test: the attacker's own
    # foothold tooling and arena infrastructure (package mirror). The monitor
    # watches the target, not the harness.
    _MONITOR_SKIP_ROLES = frozenset({"attacker", "mirror"})

    def collect_monitor_signals(self, instance_id):
        """M2 monitor backend: read each service-under-test node's container State
        plus a bounded tail of its logs, so `monitor.detect_signals` can flag
        crashes / sanitizer aborts / unhandled 5xx / resource exhaustion.
        Read-only and best-effort — a single unreadable container is skipped, not
        fatal."""
        try:
            containers = self.client.containers.list(
                all=True, filters={"label": f"{LABEL_LAB_ID}={instance_id}"}
            )
        except Exception as e:  # noqa: BLE001 - surface collection failure cleanly
            logger.error(f"[{instance_id}] monitor collection failed: {e}")
            return {"success": False, "error": str(e)}

        observations = []
        for c in containers:
            labels = getattr(c, "labels", {}) or {}
            role = labels.get(LABEL_ROLE, "node")
            node = labels.get(LABEL_NODE) or getattr(c, "name", "?")
            if role in self._MONITOR_SKIP_ROLES or node == _MIRROR_NODE:
                continue
            try:
                c.reload()  # State/RestartCount are only fresh after a reload
            except Exception:  # noqa: BLE001 - stale attrs are still usable
                pass
            state = (c.attrs.get("State") or {})
            observations.append({
                "name": node,
                "role": role,
                "state": state.get("Status", "unknown"),
                "exit_code": state.get("ExitCode"),
                "oom_killed": bool(state.get("OOMKilled")),
                "restart_count": int(c.attrs.get("RestartCount") or 0),
                "log_tail": self._monitor_logs(c),
            })
        return {"success": True, "observations": observations}

    def _monitor_logs(self, container) -> str:
        """A larger log tail than `_tail_logs` (which caps at 20 lines) so the
        monitor's line scan can see a crash/abort footer. Best-effort."""
        try:
            raw = container.logs(tail=self._MONITOR_LOG_TAIL_LINES)
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            return text[-self._MONITOR_LOG_CHARS:]
        except Exception:  # noqa: BLE001
            return ""

    def capture_traffic(self, instance_id, *, seconds=6, max_packets=200):
        """MITM in-path observation: tcpdump on the arena's primary bridge via a
        short-lived host-network sidecar. A bridge-attached container only sees its
        own + broadcast traffic, so we capture on the *bridge device* (which sees
        all intra-arena unicast). Privileged by nature (NET_RAW + host net) —
        gated upstream to an mitm-bound agent. Bounded by seconds/max_packets."""
        seconds = max(1, min(int(seconds), config.MITM_CAPTURE_MAX_SECONDS))
        max_packets = max(1, min(int(max_packets), 2000))
        nets = self.client.networks.list(filters={"label": f"{LABEL_LAB_ID}={instance_id}"})
        # Capture on a real SEGMENT bridge (where node↔node traffic flows), NOT the
        # auxiliary ingress / mirror / setupgw bridges this arena also creates.
        segs = [n for n in nets if not n.name.endswith(("-ingress", "-mirror", "-setupgw"))]
        if not segs:
            return {"success": False, "error": "no arena segment networks to observe"}
        default_name = self._network_name(instance_id, _DEFAULT_SEGMENT)
        net = next((n for n in segs if n.name == default_name), segs[0])
        bridge = "br-" + net.id[:12]
        cmd = ["sh", "-c",
               f"timeout {seconds} tcpdump -i {bridge} -nn -tt -l -c {max_packets} 2>/dev/null; true"]
        try:
            raw = self.client.containers.run(
                config.MITM_CAPTURE_IMAGE, command=cmd, network_mode="host",
                cap_add=["NET_RAW", "NET_ADMIN"], remove=True, stdout=True, stderr=False,
                labels={LABEL_LAB_ID: instance_id},
            )
        except Exception as e:  # noqa: BLE001 - surface capture failures cleanly
            logger.error(f"[{instance_id}] MITM capture on {bridge} failed: {e}")
            return {"success": False, "error": f"capture failed: {e}"}
        flows = _parse_tcpdump(self._decode(raw))[:max_packets]
        logger.info(f"[{instance_id}] MITM capture on {bridge}: {len(flows)} packet(s) in {seconds}s")
        return {"success": True, "bridge": bridge, "segment": net.name,
                "packets": len(flows), "flows": flows}

    def destroy(self, instance_id):
        try:
            label_filter = {"label": f"{LABEL_LAB_ID}={instance_id}"}

            for container in self.client.containers.list(all=True, filters=label_filter):
                logger.info(f"[{instance_id}] Removing container {container.name}")
                container.remove(force=True)

            for network in self.client.networks.list(filters=label_filter):
                logger.info(f"[{instance_id}] Removing network {network.name}")
                network.remove()

            # Reclaim any per-arena SUT image built from source (P1-6); without
            # this a from-source build leaks one image per arena. Best-effort —
            # an image still referenced elsewhere may refuse removal. The shared
            # package-mirror image is unlabeled, so it is never matched here.
            for image in self.client.images.list(filters=label_filter):
                image_id = getattr(image, "id", None)
                try:
                    self.client.images.remove(image_id, force=True)
                    logger.info(f"[{instance_id}] Removing built image {image_id}")
                except Exception as e:
                    logger.warning(
                        f"[{instance_id}] could not remove image {image_id}: {e}"
                    )

            # Reclaim per-arena white-box source volumes (P2-10); a leaked volume
            # would persist the cloned source across teardowns.
            for volume in self.client.volumes.list(filters=label_filter):
                try:
                    volume.remove(force=True)
                    logger.info(f"[{instance_id}] Removing source volume {volume.name}")
                except Exception as e:
                    logger.warning(
                        f"[{instance_id}] could not remove volume "
                        f"{getattr(volume, 'name', None)}: {e}"
                    )

            return {"success": True}
        except Exception as e:
            logger.error(f"[{instance_id}] docker-local destroy failed: {e}")
            return {"success": False, "error": str(e)}
