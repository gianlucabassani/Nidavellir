"""
docker-local provider: container arenas on the host Docker daemon (ADR-0003).

Compiles a v3 scenario topology to Docker (ROADMAP Phase 1, P1-2): one bridge
network per declared network segment (per arena), one container per node,
attached to the networks of the segments it declares. A node may straddle
several segments; nodes that declare none share a per-arena default bridge.
Everything is tagged with `cyberguard.lab_id` so destroy() can find and remove
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
import logging
import os

import config
import images
from providers.base import RangeProvider
from redaction import redact_mapping
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

LABEL_LAB_ID = "cyberguard.lab_id"
LABEL_ROLE = "cyberguard.role"
LABEL_NODE = "cyberguard.node"

# Sentinel segment for nodes that declare none — realized as the per-arena
# default bridge, named WITHOUT a segment suffix so legacy/flat single-network
# scenarios keep their original `cyberguard-<short>` network name.
_DEFAULT_SEGMENT = "_default"

# Keeps tool containers (kali etc.) alive when the scenario doesn't say how.
DEFAULT_ATTACKER_COMMAND = "sleep infinity"

# Software-under-test (SUT) arenas, P1-6: a node may build its workload from
# source (ADR-0007). The built image is tagged + labeled per arena so destroy()
# can reclaim it — otherwise a from-source build leaks one image per arena.
_SUT_IMAGE_PREFIX = "cyberguard/sut"

# White-box source access (SUT arenas, P2-10 safe half; ADR-0007). When a victim
# node's service is `whitebox: true` AND has a `source`, the repo is cloned
# (read-only, pinned to `ref`) into a per-arena docker volume and mounted
# **read-only** into the foothold(s) at `/whitebox/<victim>` — the agent reads
# the source while it tests the running service. Cloning runs nothing from the
# repo (a `git clone` is not code execution — that's why read access is ungated,
# unlike build-from-source). The clone helper has egress only to the git host
# during deploy; the volume is arena-labeled and reclaimed on destroy.
_GIT_HELPER_IMAGE = os.getenv("CYBERGUARD_GIT_HELPER_IMAGE", "alpine/git:latest")
_WHITEBOX_MOUNT_BASE = "/whitebox"

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
_MIRROR_IMAGE = "cyberguard/arena-mirror:latest"
# Build context baked into the orchestrator/worker image at /app/infra/...
_MIRROR_CONTEXT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "infra", "arena-mirror"
)


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
        base = f"cyberguard-{self._short(instance_id)}"
        return base if segment == _DEFAULT_SEGMENT else f"{base}-{segment}"

    def _container_name(self, instance_id: str, node_name: str) -> str:
        return f"cg-{self._short(instance_id)}-{node_name}"

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

        try:
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
            ingress = None
            if needs_ingress:
                ing_name = self._network_name(instance_id, _INGRESS_SEGMENT)
                logger.info(f"[{instance_id}] Creating ingress network {ing_name} (no egress)")
                ingress = self.client.networks.create(
                    ing_name, driver="bridge", options=_NO_MASQUERADE, labels=labels
                )

            # Bring the package mirror up before the nodes so its `mirror` alias
            # resolves the moment a foothold runs apt/pip.
            mirror = self._run_mirror(instance_id, networks, wanted, labels) if needs_mirror else None

            # White-box source (read-only) must be cloned before the footholds
            # start, since they mount it. Only meaningful with a foothold to read
            # it from.
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
            sut_sources = self._prepare_sut_sources(instance_id, nodes, labels)

            records = []
            for node in nodes:
                container = self._run_node(
                    instance_id, node, networks, ingress, labels, locked,
                    mirror, whitebox, sut_sources,
                )
                records.append((node, container))

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
            logger.error(f"[{instance_id}] docker-local deploy failed: {e}")
            # Roll back whatever was created so nothing leaks.
            self.destroy(instance_id)
            return {"success": False, "error": str(e)}

    def _run_node(self, instance_id, node, networks, ingress, labels, locked,
                  mirror=None, whitebox=None, sut_sources=None):
        role = node.get("role", "node")
        segments = self._node_segments(node)
        # Resolve the workload image. Packaged-first (SUT arenas, P1-6): `image`
        # is the effective image from normalized_nodes (a service's published
        # image wins). A build-from-source service (`needs_build`) is built here
        # via the daemon — gated by CYBERGUARD_ALLOW_SOURCE_BUILD (ADR-0007).
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
        if command is None and (role == "attacker" or node.get("entrypoint")):
            command = DEFAULT_ATTACKER_COMMAND
        if command is not None:
            run_kwargs["command"] = command

        # Point a foothold's apt/pip at the allowlisted mirror. Set in the
        # container config so `docker exec` sessions inherit it too. NO_PROXY
        # keeps loopback/intra-arena traffic off the proxy.
        if mirror is not None and self._is_foothold(node):
            run_kwargs["environment"] = {
                "http_proxy": _MIRROR_PROXY_URL,
                "https_proxy": _MIRROR_PROXY_URL,
                "HTTP_PROXY": _MIRROR_PROXY_URL,
                "HTTPS_PROXY": _MIRROR_PROXY_URL,
                "no_proxy": "localhost,127.0.0.1,::1",
                "NO_PROXY": "localhost,127.0.0.1,::1",
            }

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

    def _build_service_image(self, instance_id, node, labels):
        """Build a node's workload from source (SUT arenas, P1-6; ADR-0007).

        **OFF by default** — building an arbitrary repo runs third-party code at
        BUILD time (Dockerfile RUN), strictly more dangerous than pulling a
        published image — so it requires CYBERGUARD_ALLOW_SOURCE_BUILD=true.

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
                "at build time). Enable explicitly with CYBERGUARD_ALLOW_SOURCE_"
                "BUILD=true (see SECURITY.md), or supply a packaged `service.image`"
            )
        service = node.get("service") or {}
        source = service.get("source")
        if not source:
            # `service.package` install needs a base image + an install recipe;
            # only source (git) builds are wired in this increment.
            raise ValueError(
                f"node {node['name']!r}: `service.package` install is not "
                "supported yet — supply a `service.source` or a packaged `image`"
            )
        repo = source.get("repo")
        if not repo:
            raise ValueError(f"node {node['name']!r}: service.source needs a `repo`")
        ref = source.get("ref")
        subdir = source.get("context")
        dockerfile = source.get("dockerfile") or "Dockerfile"

        # Daemon-side remote git context: "<repo>#<ref>:<subdir>". The repo is
        # operator-authored (authoring the scenario is the approval); pin `ref`
        # to a commit/tag for a reproducible, trustworthy build.
        if ref and subdir:
            remote = f"{repo}#{ref}:{subdir}"
        elif ref:
            remote = f"{repo}#{ref}"
        elif subdir:
            remote = f"{repo}#:{subdir}"
        else:
            remote = repo
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
            vol_name = f"cg-{self._short(instance_id)}-src-{node['name']}"
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
            vol_name = f"cg-{self._short(instance_id)}-sut-{node['name']}"
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

            # First published port (if any) → host-reachable URL.
            floating = url = None
            ports = container.attrs["NetworkSettings"].get("Ports") or {}
            for bindings in ports.values():
                if bindings:
                    host_port = bindings[0]["HostPort"]
                    floating = f"127.0.0.1:{host_port}"
                    url = f"http://127.0.0.1:{host_port}"
                    break

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
                outputs[f"node_{name}_url"] = url

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
                    if role == "victim":
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
                logger.info(f"[{instance_id}] setup egress OPEN for node {node!r}")
                return {"success": True, "egress": "open", "network": net_name}
            # close
            try:
                self.client.networks.get(net_name).disconnect(container, force=True)
            except docker.errors.NotFound:
                pass  # bridge gone → already closed
            except docker.errors.APIError:
                pass  # not attached → already closed
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

    @classmethod
    def _decode(cls, raw) -> str:
        if not raw:
            return ""
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        return text[: cls.EXEC_OUTPUT_CAP]

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
