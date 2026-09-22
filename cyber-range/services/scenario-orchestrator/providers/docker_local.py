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
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import socket
import subprocess  # nosec B404 — fixed argv (no shell), timeout, SSRF-guarded host
import tarfile
import tempfile
import time
import urllib.parse
import uuid
from pathlib import PurePosixPath

import config
import images
import lifecycle_manifest
import netguard
import source_bundle
from providers.base import RangeProvider
from redaction import redact_mapping
from scenario_spec import normalized_nodes

logger = logging.getLogger(__name__)

LABEL_LAB_ID = "nidavellir.lab_id"
LABEL_ROLE = "nidavellir.role"
LABEL_NODE = "nidavellir.node"
LABEL_POC_JOB = "nidavellir.poc_job"


def _already_absent(exc: Exception) -> bool:
    """Docker removal races are successful when the resource is already gone."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 404

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
# (pinned to `ref`) into a per-arena docker volume and mounted as a writable
# **research copy** into the foothold(s) at `/whitebox/<victim>`. It is separate
# from the running victim, so an agent may instrument/patch it and inspect a clean
# diff without mutating the target. Cloning runs nothing from the repo (a `git
# clone` is not code execution). The clone helper has egress only to the git host
# during deploy; the volume is arena-labeled and reclaimed on destroy.
_GIT_HELPER_IMAGE = os.getenv("NIDAVELLIR_GIT_HELPER_IMAGE", "alpine/git:latest")
_WHITEBOX_MOUNT_BASE = "/whitebox"

# Change intelligence is deliberately smaller than command execution: it is a
# read-only evidence primitive used by both the Web UI and MCP.  Git is invoked
# with fixed argv, repository hooks/pagers/external diff drivers are disabled,
# and the provider bounds data before it crosses the container boundary.
_WORKSPACE_BASE_RE = re.compile(
    r"^(?:HEAD(?:[~^][0-9]{0,4})*|[0-9a-fA-F]{7,40})$"
)
_WORKSPACE_MAX_CONTEXT = 20
_WORKSPACE_MAX_LINES = 500
_WORKSPACE_RAW_CAP = 1024 * 1024
_TRANSFER_ROOT = PurePosixPath("/opt/nidavellir-transfer")
_BROWSER_MARKER_ATTR = "data-nidavellir-xss"

# Arena HTTP primitive (R1): request validation and response parsing. The
# method/header rules keep shell metacharacters and CR/LF injection out of the
# runner argv; framing headers are dropped because curl computes them itself.
_HTTP_METHOD_RE = re.compile(r"^[A-Za-z]{1,32}$")
_HTTP_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HTTP_FRAMING_HEADERS = frozenset({"content-length", "transfer-encoding"})
_HTTP_MAX_HEADERS = 32
_HTTP_MAX_HEADER_VALUE_CHARS = 4096


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

            self._client = docker.from_env(timeout=config.DOCKER_API_TIMEOUT_SECONDS)
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

    def browser_visit(
        self, instance_id, node, target_ip, port, scheme, path, params=None,
        *, wait_ms=1500, execution_marker=None,
        job_id=None,
    ):
        """Render a target page in a disposable, arena-network-only Chrome.

        The target IP must match the selected node's Docker attachment. This
        repeats API scope at the provider boundary before starting the runner.
        """
        if scheme not in ("http", "https"):
            return {"success": False, "error": "browser scheme must be http or https"}
        if not path.startswith("/") or path.startswith("//") or "\x00" in path:
            return {"success": False, "error": "browser path must be relative to the target"}
        try:
            port = int(port)
        except (TypeError, ValueError):
            return {"success": False, "error": "invalid browser target port"}
        if not 1 <= port <= 65535:
            return {"success": False, "error": "invalid browser target port"}

        target = self._find_node_container(instance_id, node)
        target.reload()
        networks = (target.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        network = next(
            (name for name, data in networks.items() if data.get("IPAddress") == target_ip),
            None,
        )
        expected_prefix = f"nidavellir-{self._short(instance_id)}"
        if network is None or not network.startswith(expected_prefix):
            return {"success": False, "error": "target IP is not attached to this arena"}

        wait_ms = max(0, min(int(wait_ms), 5000))
        query = urllib.parse.urlencode(params or {})
        url = f"{scheme}://{target_ip}:{port}{path}" + (f"?{query}" if query else "")
        helper_id = uuid.uuid4().hex[:12]
        helper_network_name = f"nv-browser-{self._short(instance_id)}-{helper_id}"
        command = [
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-background-networking",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--disable-quic",
            "--ignore-certificate-errors",
            "--proxy-bypass-list=<-loopback>",
            "--user-data-dir=/run/nidavellir-browser/profile",
            f"--virtual-time-budget={wait_ms}",
            "--dump-dom",
            url,
        ]
        runner = proxy = helper_network = None
        job_labels = {LABEL_POC_JOB: job_id} if job_id else {}
        try:
            helper_network = self.client.networks.create(
                helper_network_name,
                driver="bridge",
                internal=True,
                labels={LABEL_LAB_ID: instance_id, LABEL_ROLE: "browser-network", **job_labels},
            )
            proxy = self.client.containers.create(
                image=config.POC_RUNNER_IMAGE,
                entrypoint="python3",
                command=[
                    "-E", "/opt/nidavellir/proxy.py",
                    "--host", target_ip, "--port", str(port),
                    "--scheme", scheme,
                    "--timeout", str(config.HEADLESS_BROWSER_TIMEOUT_SECONDS),
                ],
                name=f"nv-browser-proxy-{helper_id}", detach=True,
                network=helper_network_name,
                labels={LABEL_LAB_ID: instance_id, LABEL_ROLE: "browser-proxy", **job_labels},
                user="65532:65532", cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"], read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,nodev,size=1m"},  # nosec B108 - private container tmpfs
                environment={}, mem_limit="32m", nano_cpus=250_000_000,
                pids_limit=16,
            )
            self.client.networks.get(network).connect(proxy)
            proxy.start()
            proxy.reload()
            proxy_networks = (proxy.attrs.get("NetworkSettings") or {}).get("Networks") or {}
            proxy_ip = (proxy_networks.get(helper_network_name) or {}).get("IPAddress")
            if not proxy_ip:
                raise RuntimeError("browser proxy did not receive an isolated address")
            # Starting a container does not mean its listener is accepting yet.
            # Chrome retries a refused proxy for long enough to consume the
            # entire synchronous API budget, so establish readiness from inside
            # the trusted proxy container before launching the untrusted page.
            proxy_ready_deadline = time.monotonic() + 8
            while time.monotonic() < proxy_ready_deadline:
                probe = proxy.exec_run([
                    "python3", "-E", "-c",
                    (
                        "import socket; s=socket.create_connection("
                        "('127.0.0.1',8080),.2); s.close()"
                    ),
                ])
                probe_code = probe.exit_code if hasattr(probe, "exit_code") else probe[0]
                if probe_code == 0:
                    break
                proxy.reload()
                proxy_state = (proxy.attrs.get("State") or {}).get("Status")
                if proxy_state in {"exited", "dead"}:
                    raise RuntimeError("browser proxy exited before becoming ready")
                time.sleep(0.05)
            else:
                raise RuntimeError("browser proxy did not become ready")
            command.insert(-2, f"--proxy-server=http://{proxy_ip}:8080")
            runner = self.client.containers.run(
                image=config.HEADLESS_BROWSER_IMAGE,
                entrypoint="chromium-browser",
                command=command,
                detach=True,
                network=helper_network_name,
                labels={LABEL_LAB_ID: instance_id, LABEL_ROLE: "browser", **job_labels},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                read_only=True,
                tmpfs={
                    "/run/nidavellir-browser": "rw,noexec,nosuid,mode=1777,size=128m"
                },
                environment={
                    "HOME": "/run/nidavellir-browser",
                    "TMPDIR": "/run/nidavellir-browser",
                },
                mem_limit=config.HEADLESS_BROWSER_MEMORY,
                nano_cpus=1_000_000_000,
                pids_limit=256,
            )
            result = runner.wait(timeout=config.HEADLESS_BROWSER_TIMEOUT_SECONDS)
            status = int((result or {}).get("StatusCode", 1))
            raw = runner.logs(stdout=True, stderr=False)
            raw = raw if isinstance(raw, bytes) else str(raw or "").encode()
            if status != 0:
                stderr = runner.logs(stdout=False, stderr=True)
                stderr = (
                    stderr.decode("utf-8", "replace")
                    if isinstance(stderr, bytes) else str(stderr or "")
                )
                return {
                    "success": False,
                    "error": stderr[:1000] or f"browser exited {status}",
                }
            dom_bytes = len(raw)
            dom = raw[:config.HEADLESS_BROWSER_MAX_OUTPUT_BYTES].decode("utf-8", "replace")
            title_match = re.search(r"<title[^>]*>(.*?)</title>", dom, re.I | re.S)
            marker = (
                f'{_BROWSER_MARKER_ATTR}="{execution_marker}"'
                if execution_marker else None
            )
            return {
                "success": True,
                "url": url,
                "title": re.sub(r"\s+", " ", title_match.group(1)).strip()[:512]
                if title_match else "",
                "rendered_dom": dom,
                "dom_bytes": dom_bytes,
                "dom_sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}",
                "truncated": dom_bytes > config.HEADLESS_BROWSER_MAX_OUTPUT_BYTES,
                "executed": (marker in dom) if marker else None,
            }
        except Exception as exc:  # noqa: BLE001 - provider errors are returned, not leaked
            return {"success": False, "error": f"headless browser failed: {exc}"}
        finally:
            if runner is not None:
                try:
                    runner.remove(force=True)
                except Exception as cleanup_error:  # noqa: BLE001 - best-effort cleanup
                    logger.warning(
                        f"[{instance_id}] could not remove browser runner: {cleanup_error}"
                    )
            if proxy is not None:
                try:
                    proxy.remove(force=True)
                except Exception as cleanup_error:  # noqa: BLE001
                    logger.warning(
                        f"[{instance_id}] could not remove browser proxy: {cleanup_error}"
                    )
            if helper_network is not None:
                try:
                    helper_network.remove()
                except Exception as cleanup_error:  # noqa: BLE001
                    logger.warning(
                        f"[{instance_id}] could not remove browser network: {cleanup_error}"
                    )

    @staticmethod
    def _validated_http_headers(headers):
        """Normalize caller headers into an argv-safe list, or return an error.

        Framing headers are dropped (curl computes its own Content-Length /
        Transfer-Encoding); everything else must be a plain token with no line
        breaks so the value can never split into extra runner arguments.
        """
        cleaned: list[tuple[str, str]] = []
        for name, value in (headers or {}).items():
            name = str(name).strip()
            value = str(value)
            if not _HTTP_HEADER_NAME_RE.match(name):
                return None, f"invalid header name {name!r}"
            if "\r" in value or "\n" in value:
                return None, f"header {name!r} contains a line break"
            if len(value) > _HTTP_MAX_HEADER_VALUE_CHARS:
                return None, f"header {name!r} exceeds the value limit"
            if name.lower() in _HTTP_FRAMING_HEADERS:
                continue
            cleaned.append((name, value))
        if len(cleaned) > _HTTP_MAX_HEADERS:
            return None, "too many request headers"
        return cleaned, None

    def http_request(
        self, instance_id, node, target_ip, port, scheme, path, params=None,
        *, method="GET", headers=None, body=None, job_id=None,
    ):
        """Perform one arena-bound HTTP request in a disposable curl runner.

        Mirrors browser_visit's containment: the target IP must match the
        selected node's Docker attachment, the runner joins only that arena
        network, and resources/time/output are bounded. Redirects are never
        followed — a redirect surfaces as ``redirect_location`` metadata, so
        the primitive can never be walked off the resolved target.
        """
        if scheme not in ("http", "https"):
            return {"success": False, "error": "http scheme must be http or https"}
        if not isinstance(method, str) or not _HTTP_METHOD_RE.match(method):
            return {"success": False, "error": "invalid HTTP method"}
        method = method.upper()
        if not path.startswith("/") or path.startswith("//") or "\x00" in path:
            return {"success": False, "error": "http path must be relative to the target"}
        try:
            port = int(port)
        except (TypeError, ValueError):
            return {"success": False, "error": "invalid http target port"}
        if not 1 <= port <= 65535:
            return {"success": False, "error": "invalid http target port"}

        header_list, header_error = self._validated_http_headers(headers)
        if header_error:
            return {"success": False, "error": header_error}

        body_bytes = b""
        if body is not None:
            if not isinstance(body, str):
                return {"success": False, "error": "http request body must be text"}
            if "\x00" in body:
                return {"success": False, "error": "http request body must not contain NUL"}
            body_bytes = body.encode("utf-8")
            if len(body_bytes) > config.HTTP_MAX_REQUEST_BYTES:
                return {
                    "success": False,
                    "error": "http request body exceeds the configured limit",
                }

        target = self._find_node_container(instance_id, node)
        if target is None:
            return {"success": False, "error": f"node {node!r} not found in arena {instance_id}"}
        target.reload()
        networks = (target.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        network = next(
            (name for name, data in networks.items() if data.get("IPAddress") == target_ip),
            None,
        )
        expected_prefix = f"nidavellir-{self._short(instance_id)}"
        if network is None or not network.startswith(expected_prefix):
            return {"success": False, "error": "target IP is not attached to this arena"}

        query = urllib.parse.urlencode(params or {})
        url = f"{scheme}://{target_ip}:{port}{path}" + (f"?{query}" if query else "")
        command = [
            "-s", "-S", "-i",
            "--max-time", str(config.HTTP_TIMEOUT_SECONDS),
            "--connect-timeout", "5",
            "-X", method,
        ]
        for header_name, header_value in header_list:
            command += ["-H", f"{header_name}: {header_value}"]
        if body_bytes:
            command += ["--data-binary", body]
        command.append(url)

        runner = None
        started = time.monotonic()
        try:
            runner = self.client.containers.run(
                image=config.HTTP_RUNNER_IMAGE,
                entrypoint="curl",
                command=command,
                detach=True,
                network=network,
                labels={LABEL_LAB_ID: instance_id, LABEL_ROLE: "http",
                        **({LABEL_POC_JOB: job_id} if job_id else {})},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                read_only=True,
                tmpfs={"/run/nidavellir-http": "rw,noexec,nosuid,size=1m"},
                environment={"HOME": "/run/nidavellir-http"},
                mem_limit=config.HTTP_RUNNER_MEMORY,
                nano_cpus=500_000_000,
                pids_limit=64,
            )
            result = runner.wait(timeout=config.HTTP_TIMEOUT_SECONDS + 5)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            status_code = int((result or {}).get("StatusCode", 1))
            raw = runner.logs(stdout=True, stderr=False)
            raw = raw if isinstance(raw, bytes) else str(raw or "").encode()
            if status_code != 0:
                stderr = runner.logs(stdout=False, stderr=True)
                stderr = (
                    stderr.decode("utf-8", "replace")
                    if isinstance(stderr, bytes) else str(stderr or "")
                )
                detail = stderr[:1000] or f"curl exited {status_code}"
                if status_code == 28:
                    detail = f"request timed out after {config.HTTP_TIMEOUT_SECONDS}s"
                return {"success": False, "error": detail}
            return self._parse_http_transaction(url, raw, elapsed_ms)
        except Exception as exc:  # noqa: BLE001 - provider errors are returned, not leaked
            return {"success": False, "error": f"http request failed: {exc}"}
        finally:
            if runner is not None:
                try:
                    runner.remove(force=True)
                except Exception as cleanup_error:  # noqa: BLE001 - best-effort cleanup
                    logger.warning(
                        f"[{instance_id}] could not remove http runner: {cleanup_error}"
                    )

    @staticmethod
    def _parse_http_transaction(url, raw, elapsed_ms):
        """Split one raw ``curl -i`` response into bounded, hashed output.

        The digest always covers the FULL body even when truncation keeps only
        the leading bytes, so evidence stays verifiable against the wire.
        """
        head, separator, body_bytes = raw.partition(b"\r\n\r\n")
        if not separator:
            head, body_bytes = raw, b""
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ", 2) if lines else []
        try:
            status = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            status = 0
        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            name = name.strip().lower()
            if not name:
                continue
            value = value.strip()
            headers[name] = f"{headers[name]}, {value}" if name in headers else value
        full_len = len(body_bytes)
        truncated = full_len > config.HTTP_MAX_RESPONSE_BYTES
        kept = body_bytes[: config.HTTP_MAX_RESPONSE_BYTES]
        return {
            "success": True,
            "url": url,
            "status": status,
            "reason": (parts[2] if len(parts) > 2 else "")[:128],
            "http_version": (parts[0] if parts else "")[:32],
            "headers": headers,
            "header_count": len(headers),
            "redirect_location": headers.get("location"),
            "body": kept.decode("utf-8", "replace"),
            "body_bytes": full_len,
            "body_sha256": f"sha256:{hashlib.sha256(body_bytes).hexdigest()}",
            "truncated": truncated,
            "elapsed_ms": elapsed_ms,
        }

    @staticmethod
    def _poc_input_archive(payload: dict) -> bytes:
        """Build the exact bounded workspace transferred through the Docker API."""
        archive_bytes = io.BytesIO()
        entries = [("main.py", payload["source"].encode("utf-8"))]
        for item in payload.get("files") or []:
            import base64
            entries.append((f"input/{item['path']}", base64.b64decode(item["content_b64"])))
        entries.append((".ready", b""))
        with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
            for name, content in entries:
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o400
                info.uid = 65532
                info.gid = 65532
                info.mtime = 0
                archive.addfile(info, io.BytesIO(content))
        return archive_bytes.getvalue()

    def _copy_poc_input(self, container, payload: dict) -> None:
        """Stream the safe archive through a fixed tar exec into writable tmpfs.

        Docker rejects ``put_archive`` for a read-only-root container even when
        the destination is tmpfs. Exec keeps the root read-only and gives only
        this trusted, shell-free extractor write access to /workspace.
        """
        created = self.client.api.exec_create(
            container.id,
            ["tar", "-x", "-f", "-", "-C", "/workspace"],
            stdin=True,
            stdout=True,
            stderr=True,
            user="65532:65532",
        )
        exec_id = created["Id"]
        stream = self.client.api.exec_start(exec_id, socket=True, tty=False)
        raw_socket = getattr(stream, "_sock", stream)
        try:
            raw_socket.sendall(self._poc_input_archive(payload))
            raw_socket.shutdown(socket.SHUT_WR)
            while raw_socket.recv(65536):
                pass
        finally:
            stream.close()
        if self._poc_exec_exit_code(exec_id) != 0:
            raise RuntimeError("trusted PoC input extraction failed")

    def _poc_exec_exit_code(self, exec_id):
        # Stream EOF can precede the daemon publishing the process exit code.
        deadline = time.monotonic() + 2
        while True:
            inspected = self.client.api.exec_inspect(exec_id)
            code = inspected.get("ExitCode")
            if code is not None or time.monotonic() >= deadline:
                return code
            time.sleep(0.02)

    def _poc_artifacts(self, container) -> tuple[list[dict], str | None]:
        """Collect bounded regular artifacts; links and special files are refused.

        Docker's archive endpoint reads the container layer and cannot see a
        tmpfs mount.  Use the immutable image's tar binary through a fixed exec
        instead; the command and source path are never supplied by the PoC.
        """
        import base64
        artifacts = []
        total = 0
        try:
            created = self.client.api.exec_create(
                container.id,
                ["/bin/tar", "-c", "-f", "-", "-C", "/workspace", "artifacts"],
                stdout=True,
                stderr=True,
                user="65532:65532",
            )
            exec_id = created["Id"]
            chunks = self.client.api.exec_start(
                exec_id, stream=True, demux=True, tty=False,
            )
            raw_parts = []
            archive_bytes = 0
            stderr_parts = []
            stderr_bytes = 0
            # A tar adds headers/padding. Bound the daemon stream itself so a
            # malicious sparse/archive response is never buffered without limit.
            archive_cap = config.POC_MAX_ARTIFACT_BYTES + (config.POC_MAX_ARTIFACTS + 4) * 1024
            for chunk in chunks:
                if isinstance(chunk, tuple):
                    stdout_chunk, stderr_chunk = chunk
                else:  # compatibility with Docker clients lacking demux tuples
                    stdout_chunk, stderr_chunk = chunk, None
                stdout_chunk = stdout_chunk or b""
                stderr_chunk = stderr_chunk or b""
                archive_bytes += len(stdout_chunk)
                if archive_bytes > archive_cap:
                    return [], "artifact archive exceeds the configured limit"
                raw_parts.append(stdout_chunk)
                if stderr_bytes < 4096:
                    remaining = 4096 - stderr_bytes
                    stderr_parts.append(stderr_chunk[:remaining])
                    stderr_bytes += len(stderr_chunk[:remaining])
            if self._poc_exec_exit_code(exec_id) != 0:
                message = b"".join(stderr_parts).decode("utf-8", "replace")
                if "no such file" in message.lower():
                    return [], None
                return [], f"artifact collection failed: {message or 'trusted tar failed'}"
            raw = b"".join(raw_parts)
        except Exception as exc:
            return [], f"artifact collection failed: {exc}"
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
                for member in archive:
                    if member.isdir():
                        continue
                    if not member.isfile() or member.issym() or member.islnk():
                        return [], "artifact output contains a link or special file"
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts:
                        return [], "artifact output contains an unsafe path"
                    if len(artifacts) >= config.POC_MAX_ARTIFACTS:
                        return [], "artifact count exceeds the configured limit"
                    extracted = archive.extractfile(member)
                    content = extracted.read(config.POC_MAX_ARTIFACT_BYTES + 1) if extracted else b""
                    total += len(content)
                    if (
                        len(content) > config.POC_MAX_ARTIFACT_BYTES
                        or total > config.POC_MAX_ARTIFACT_BYTES
                    ):
                        return [], "artifact bytes exceed the configured limit"
                    artifacts.append({
                        "path": str(path), "bytes": len(content),
                        "sha256": f"sha256:{hashlib.sha256(content).hexdigest()}",
                        "content_b64": base64.b64encode(content).decode("ascii"),
                    })
        except (tarfile.TarError, OSError) as exc:
            return [], f"artifact archive is invalid: {exc}"
        return artifacts, None

    def _cleanup_poc_resources(self, job_id: str) -> dict:
        label = {"label": f"{LABEL_POC_JOB}={job_id}"}
        errors = []
        try:
            for container in self.client.containers.list(all=True, filters=label):
                try:
                    container.remove(force=True)
                except Exception as exc:  # noqa: BLE001
                    if not _already_absent(exc):
                        errors.append(f"container cleanup failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"container enumeration failed: {exc}")
        try:
            for volume in self.client.volumes.list(filters=label):
                try:
                    volume.remove(force=True)
                except Exception as exc:  # noqa: BLE001
                    if not _already_absent(exc):
                        errors.append(f"volume cleanup failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"volume enumeration failed: {exc}")
        try:
            for network in self.client.networks.list(filters=label):
                try:
                    network.remove()
                except Exception as exc:  # noqa: BLE001
                    if not _already_absent(exc):
                        errors.append(f"network cleanup failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"network enumeration failed: {exc}")
        remaining = {"containers": 0, "volumes": 0, "networks": 0}
        try:
            remaining["containers"] = len(self.client.containers.list(all=True, filters=label))
            remaining["volumes"] = len(self.client.volumes.list(filters=label))
            remaining["networks"] = len(self.client.networks.list(filters=label))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cleanup verification failed: {exc}")
        if any(remaining.values()):
            errors.append(f"PoC resources remain: {remaining}")
        return {"success": not errors, "error": "; ".join(errors) or None,
                "remaining": remaining}

    def cleanup_poc_job(self, job_id: str) -> dict:
        return self._cleanup_poc_resources(job_id)

    def run_poc(
        self, instance_id, job_id, payload, target_policy, limits, cancel_check=None,
    ):
        """Run untrusted Python without an IP network and with a fixed HTTP relay."""
        labels = {
            LABEL_LAB_ID: instance_id,
            LABEL_POC_JOB: job_id,
        }
        runner = relay = None
        outcome = {"success": False, "error": "PoC helper did not start"}
        cleanup = {"success": False, "error": "cleanup did not run"}
        try:
            from docker.types import LogConfig

            # Refuse implicit pulls. The operator prebuilds this trusted image.
            image = self.client.images.get(config.POC_RUNNER_IMAGE)
            image_id = getattr(image, "id", None)
            attrs = getattr(image, "attrs", {}) or {}
            platform = f"{attrs.get('Os', 'unknown')}/{attrs.get('Architecture', 'unknown')}"
            if cancel_check and cancel_check():
                return {
                    "success": False,
                    "state": "cancelled",
                    "cancelled": True,
                    "cleanup": {"success": True},
                }

            relay_volume_name = f"nv-poc-{job_id[:12]}"
            self.client.volumes.create(name=relay_volume_name, labels=labels)
            volumes = {relay_volume_name: {"bind": "/run/nidavellir", "mode": "ro"}}
            if target_policy:
                target = self._find_node_container(instance_id, target_policy["node"])
                if target is None:
                    raise ValueError("selected target node is unavailable")
                target.reload()
                networks = (target.attrs.get("NetworkSettings") or {}).get("Networks") or {}
                network = next((name for name, data in networks.items()
                                if data.get("IPAddress") == target_policy["ip"]), None)
                if network is None or not network.startswith(
                    f"nidavellir-{self._short(instance_id)}"
                ):
                    raise ValueError("selected target address is not owned by this arena")
                relay = self.client.containers.create(
                    image=image_id,
                    entrypoint="python3",
                    command=[
                        "-E", "/opt/nidavellir/relay.py",
                        "--socket", "/run/nidavellir/relay.sock",
                        "--host", target_policy["ip"],
                        "--port", str(target_policy["port"]),
                        "--scheme", target_policy["scheme"],
                        "--timeout", str(min(int(limits["timeout_seconds"]), 15)),
                    ],
                    name=f"nv-poc-relay-{job_id[:12]}", detach=True, network=network,
                    labels={**labels, LABEL_ROLE: "poc-relay"},
                    volumes={relay_volume_name: {"bind": "/run/nidavellir", "mode": "rw"}},
                    user="65532:65532", cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"], read_only=True,
                    tmpfs={"/tmp": "rw,noexec,nosuid,nodev,size=1m"},  # nosec B108 - private container tmpfs
                    environment={}, mem_limit="32m", nano_cpus=250_000_000,
                    pids_limit=16, network_disabled=False,
                    log_config=LogConfig(
                        type=LogConfig.types.JSON,
                        config={"max-size": "64k", "max-file": "1"},
                    ),
                )
                relay.start()

            runner = self.client.containers.create(
                image=image_id,
                name=f"nv-poc-runner-{job_id[:12]}", detach=True,
                network_mode="none", network_disabled=True,
                labels={**labels, LABEL_ROLE: "poc-runner"}, volumes=volumes,
                user="65532:65532", cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"], read_only=True,
                tmpfs={
                    "/workspace": (
                        f"rw,nosuid,nodev,size={int(limits['workspace_bytes'])},uid=65532,gid=65532"
                    ),
                    "/tmp": "rw,noexec,nosuid,nodev,size=8m,uid=65532,gid=65532",  # nosec B108 - private container tmpfs
                },
                environment={"PYTHONDONTWRITEBYTECODE": "1"},
                mem_limit=f"{int(limits['memory_mb'])}m",
                nano_cpus=int(limits["cpu_millis"]) * 1_000_000,
                pids_limit=int(limits["pids"]),
                log_config=LogConfig(
                    type=LogConfig.types.JSON,
                    config={"max-size": "128k", "max-file": "1"},
                ),
            )
            runner.start()
            self._copy_poc_input(runner, payload)

            deadline = time.monotonic() + int(limits["timeout_seconds"])
            terminal_reason = None
            child_exit_code = None
            state = {}
            while time.monotonic() < deadline:
                if cancel_check and cancel_check():
                    terminal_reason = "cancelled"
                    break
                runner.reload()
                state = (runner.attrs or {}).get("State") or {}
                if state.get("Status") in {"exited", "dead"}:
                    break
                probe = runner.exec_run(["cat", "/workspace/.nidavellir-exit"])
                if hasattr(probe, "exit_code"):
                    probe_code, probe_output = probe.exit_code, probe.output
                else:
                    probe_code, probe_output = probe
                if probe_code == 0:
                    child_exit_code = int(bytes(probe_output).decode().strip())
                    break
                time.sleep(0.1)
            else:
                terminal_reason = "timed_out"
            # A completed child leaves its parent alive specifically so tmpfs
            # artifacts can be collected below. Timeouts/cancellation also end
            # the whole cgroup before collection.
            if terminal_reason:
                try:
                    runner.kill()
                except Exception:  # noqa: BLE001
                    pass
                runner.reload()
                state = (runner.attrs or {}).get("State") or state

            stdout_raw = runner.logs(stdout=True, stderr=False) or b""
            stderr_raw = runner.logs(stdout=False, stderr=True) or b""
            if not isinstance(stdout_raw, bytes):
                stdout_raw = str(stdout_raw).encode()
            if not isinstance(stderr_raw, bytes):
                stderr_raw = str(stderr_raw).encode()
            artifacts, artifact_error = self._poc_artifacts(runner)
            if child_exit_code is not None:
                try:
                    runner.kill()
                except Exception:  # noqa: BLE001
                    pass
            cap = config.POC_MAX_OUTPUT_BYTES
            exit_code = child_exit_code if child_exit_code is not None else state.get("ExitCode")
            outcome = {
                "success": terminal_reason is None and exit_code == 0 and not artifact_error,
                "state": terminal_reason or ("succeeded" if exit_code == 0 else "failed"),
                "exit_code": exit_code,
                "stdout": stdout_raw[:cap].decode("utf-8", "replace"),
                "stderr": stderr_raw[:cap].decode("utf-8", "replace"),
                "stdout_bytes": len(stdout_raw), "stderr_bytes": len(stderr_raw),
                "stdout_sha256": f"sha256:{hashlib.sha256(stdout_raw).hexdigest()}",
                "stderr_sha256": f"sha256:{hashlib.sha256(stderr_raw).hexdigest()}",
                "output_truncated": len(stdout_raw) > cap or len(stderr_raw) > cap,
                "oom_killed": bool(state.get("OOMKilled")),
                "artifacts": artifacts, "artifact_error": artifact_error,
                "runner_image_id": image_id, "runner_platform": platform,
                "network_mode": "none", "target_transport": "unix-http-relay" if relay else "none",
            }
            if terminal_reason == "cancelled":
                outcome["cancelled"] = True
            if terminal_reason == "timed_out":
                outcome["timed_out"] = True
        except Exception as exc:  # noqa: BLE001
            outcome = {"success": False, "state": "failed", "error": str(exc)[:2000]}
        finally:
            cleanup = self._cleanup_poc_resources(job_id)
        outcome["cleanup"] = cleanup
        return outcome

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
            cleanup = self.destroy(instance_id)
            import docker  # lazy: the SDK is present here (we used self.client above)
            if isinstance(e, (docker.errors.ImageNotFound, docker.errors.NotFound)):
                msg = (
                    f"image could not be pulled — not found on the registry "
                    f"(phase: {phase}): {e}. Use a known logical image "
                    f"(GET /catalog) or fix the tag."
                )
                logger.error(f"[{instance_id}] docker-local deploy failed: {msg}")
                return {"success": False, "error": msg, "phase": phase,
                        "error_kind": "image_not_found", "cleanup": cleanup}
            logger.error(f"[{instance_id}] docker-local deploy failed (phase: {phase}): {e}")
            return {"success": False, "error": str(e), "phase": phase,
                    "error_kind": type(e).__name__, "cleanup": cleanup}

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
        if node.get("platform"):
            run_kwargs["platform"] = node["platform"]

        command = node.get("command")
        if command is None and self._is_foothold(node):
            command = DEFAULT_ATTACKER_COMMAND
        if command is not None:
            run_kwargs["command"] = command
        elif not node.get("needs_build") and not node.get("native_startup"):
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

        # Mount white-box source as a writable *research copy* in the foothold.
        # This dedicated volume is not used by the victim service: the agent can
        # instrument or patch it and get a meaningful diff without changing the
        # actual target under test.
        if whitebox and self._is_foothold(node):
            run_kwargs["volumes"] = {
                vol: {"bind": f"{_WHITEBOX_MOUNT_BASE}/{victim}", "mode": "rw"}
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
        """Clone each white-box node's source into a per-arena research volume.

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
        to mount. Unlike the white-box research copy on the foothold, the SUT
        source is mounted **into the victim itself** so the configurator
        builds/runs it in place. `git clone` runs nothing from the repo (read,
        not execution), so the clone itself is ungated."""
        mounts: dict[str, tuple[str, str]] = {}
        for node in nodes:
            clone = node.get("sut_clone")
            bundle = node.get("sut_bundle")
            if clone and bundle:
                raise ValueError(
                    f"node {node['name']!r} cannot declare both sut_clone and sut_bundle"
                )
            if not clone and not bundle:
                continue
            vol_name = f"nv-{self._short(instance_id)}-sut-{node['name']}"
            if clone:
                if not clone.get("repo"):
                    raise ValueError(f"node {node['name']!r} has no SUT clone repository")
                self._clone_source_into_volume(
                    instance_id, vol_name,
                    {"repo": clone["repo"], "ref": clone.get("ref")}, labels,
                )
                path = clone.get("path") or f"/opt/{node['name']}"
            else:
                self._bundle_source_into_volume(
                    instance_id, vol_name, bundle, labels
                )
                path = bundle.get("path") or f"/opt/{node['name']}"
            mounts[node["name"]] = (vol_name, path)
        return mounts

    def _bundle_source_into_volume(self, instance_id, vol_name, bundle, labels):
        """Materialize a verified canonical tar into an arena-owned volume.

        Bytes cross the Docker API via put_archive, avoiding a host bind path
        mismatch when the worker itself runs in a container. The networkless
        helper initializes a clean Git baseline for shared change intelligence.
        """
        digest = bundle.get("digest")
        payload_digest = bundle.get("payload_digest")
        payload = source_bundle.read_payload(digest, payload_digest)
        logger.info(
            "[%s] Materializing source bundle %s into volume %s",
            instance_id,
            digest,
            vol_name,
        )
        self.client.volumes.create(name=vol_name, labels=dict(labels))
        helper = self.client.containers.run(
            image=_GIT_HELPER_IMAGE,
            entrypoint="/bin/sh",
            command=["-c", "sleep 300"],
            volumes={vol_name: {"bind": "/src", "mode": "rw"}},
            network_mode="none",
            labels=dict(labels),
            detach=True,
            remove=False,
        )
        try:
            if not helper.put_archive("/src", payload):
                raise RuntimeError("Docker rejected the source-bundle archive")
            commands = (
                ["git", "-C", "/src", "init", "--quiet"],
                [
                    "git", "-c", "safe.directory=/src",
                    "-c", "core.hooksPath=/dev/null",
                    "-C", "/src", "add", "--force", "--all",
                ],
                [
                    "git", "-c", "safe.directory=/src",
                    "-c", "core.hooksPath=/dev/null",
                    "-c", "user.name=Nidavellir Intake",
                    "-c", "user.email=intake@localhost",
                    "-C", "/src", "commit", "--quiet", "-m", "Immutable intake baseline",
                ],
            )
            for command in commands:
                result = helper.exec_run(command)
                exit_code = result[0] if isinstance(result, tuple) else result.exit_code
                if exit_code != 0:
                    raise RuntimeError(
                        f"source-bundle baseline command failed with exit {exit_code}"
                    )
        finally:
            helper.remove(force=True)

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
            if node.get("sut_clone") or node.get("sut_bundle"):
                source = node.get("sut_clone") or node["sut_bundle"]
                outputs[f"node_{name}_sut_source"] = source.get("path") or f"/opt/{name}"
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

    @staticmethod
    def _validate_workspace_path(path: str | None) -> str | None:
        """Validate a caller-supplied pathspec without resolving it on the host.

        The path is interpreted relative to the provider-discovered repository.
        A leading dash is safe after Git's ``--`` separator, but absolute paths,
        parent traversal and NUL bytes are not.
        """
        if path is None or path == "":
            return None
        if "\x00" in path:
            raise ValueError("workspace path contains a NUL byte")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("workspace path must stay inside the workspace")
        normalized = str(parsed)
        if normalized in ("", "."):
            return None
        return normalized

    @staticmethod
    def _workspace_exec(container, argv: list[str]) -> tuple[int, str, str]:
        """Run fixed argv in a container and normalize Docker SDK result shapes."""
        result = container.exec_run(
            argv,
            demux=True,
            environment=[
                "GIT_OPTIONAL_LOCKS=0",
                "GIT_CONFIG_NOSYSTEM=1",
                "GIT_CONFIG_GLOBAL=/dev/null",
            ],
        )
        if hasattr(result, "exit_code"):
            exit_code, output = result.exit_code, result.output
        else:
            exit_code, output = result
        stdout, stderr = output if isinstance(output, tuple) else (output, None)

        def decode(raw) -> str:
            if not raw:
                return ""
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            return text[:_WORKSPACE_RAW_CAP]

        return int(exit_code), decode(stdout), decode(stderr)

    def _workspace_helper_exec(
        self, container, argv: list[str], source_path: str
    ) -> tuple[int, str, str]:
        """Run Git from the provider helper when the target image has no Git.

        Arbitrary SUT images should not need to carry our inspection tooling.
        Locate the provider-created Docker volume mounted at ``source_path`` and
        remount it read-only into a networkless short-lived git helper. Bind
        mounts are intentionally refused so a deployment output cannot make the
        helper read an arbitrary host path.
        """
        try:
            container.reload()
            mounts = (container.attrs or {}).get("Mounts") or []
            mount = next(
                (
                    item for item in mounts
                    if item.get("Destination") == source_path
                    and item.get("Type") == "volume"
                    and item.get("Name")
                ),
                None,
            )
            if mount is None:
                return 127, "", (
                    "git is unavailable in the target and its workspace is not "
                    "a provider-managed Docker volume"
                )
            helper_path = "/workspace"
            helper_argv = [
                helper_path if token == source_path else token
                for token in argv[1:]
            ]
            # Insert a helper-specific safe.directory after the existing config
            # options. It is command-line configuration, never repository-owned.
            helper_argv = [
                "-c", f"safe.directory={helper_path}", *helper_argv
            ]
            raw = self.client.containers.run(
                image=_GIT_HELPER_IMAGE,
                entrypoint="git",
                command=helper_argv,
                volumes={mount["Name"]: {"bind": helper_path, "mode": "ro"}},
                network_mode="none",
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
                environment={
                    "GIT_OPTIONAL_LOCKS": "0",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                },
            )
            text = (
                raw.decode("utf-8", "replace")
                if isinstance(raw, bytes) else str(raw or "")
            )
            return 0, text[:_WORKSPACE_RAW_CAP], ""
        except Exception as e:
            raw_stderr = getattr(e, "stderr", None)
            stderr = (
                raw_stderr.decode("utf-8", "replace")
                if isinstance(raw_stderr, bytes)
                else str(raw_stderr or e)
            )
            return int(getattr(e, "exit_status", 1) or 1), "", stderr[:_WORKSPACE_RAW_CAP]

    def _workspace_git_exec(
        self, container, argv: list[str], source_path: str
    ) -> tuple[int, str, str]:
        result = self._workspace_exec(container, argv)
        if result[0] not in (126, 127):
            return result
        return self._workspace_helper_exec(container, argv, source_path)

    @staticmethod
    def _parse_porcelain_status(raw: str) -> list[dict]:
        """Parse ``git status --porcelain=v1 -z`` into a stable bounded summary."""
        fields = raw.split("\x00")
        changed: list[dict] = []
        idx = 0
        while idx < len(fields):
            entry = fields[idx]
            idx += 1
            if not entry:
                continue
            if len(entry) < 4:
                continue
            code, path = entry[:2], entry[3:]
            old_path = None
            if "R" in code or "C" in code:
                if idx < len(fields):
                    old_path = fields[idx] or None
                    idx += 1
            item = {
                "path": path,
                "index": code[0],
                "worktree": code[1],
                "untracked": code == "??",
            }
            if old_path:
                item["old_path"] = old_path
            changed.append(item)
            if len(changed) >= 1000:
                break
        return changed

    def workspace_diff(
        self,
        instance_id,
        node,
        source_path,
        *,
        base="HEAD",
        path=None,
        context_lines=3,
        start_line=0,
        max_lines=300,
    ):
        """Return status plus a paginated tracked diff for an arena workspace.

        Untracked file names are included in ``changed_files`` but their content
        is not read: an untrusted repository can make an untracked symlink point
        outside the workspace.  Once a file is tracked, Git reads its index/work
        tree state under the normal repository boundary.
        """
        container = self._find_node_container(instance_id, node)
        if container is None:
            return {"success": False, "error": f"node {node!r} not found in arena {instance_id}"}
        if (
            not isinstance(source_path, str)
            or not source_path.startswith("/")
            or "\x00" in source_path
        ):
            return {"success": False, "error": "invalid provider workspace path"}
        if not isinstance(base, str) or not _WORKSPACE_BASE_RE.fullmatch(base):
            return {
                "success": False,
                "error": "base must be HEAD, a HEAD ancestor, or a 7-40 digit commit hash",
            }
        try:
            path = self._validate_workspace_path(path)
            context_lines = max(0, min(int(context_lines), _WORKSPACE_MAX_CONTEXT))
            start_line = max(0, int(start_line))
            max_lines = max(1, min(int(max_lines), _WORKSPACE_MAX_LINES))
        except (TypeError, ValueError) as e:
            return {"success": False, "error": str(e)}

        git = [
            "git",
            "-c", "core.hooksPath=/dev/null",
            "-c", "core.pager=cat",
            "-c", "pager.diff=false",
            "-c", "core.fsmonitor=false",
            "-c", "core.untrackedCache=false",
            "-C", source_path,
        ]
        pathspec = ["--", path] if path else []
        try:
            code, resolved, stderr = self._workspace_git_exec(
                container,
                git + ["rev-parse", "--verify", f"{base}^{{commit}}"],
                source_path,
            )
            if code != 0:
                return {
                    "success": False,
                    "error": f"cannot resolve workspace baseline: {stderr.strip() or base}",
                }
            baseline = resolved.strip().splitlines()[0] if resolved.strip() else ""

            code, status_raw, stderr = self._workspace_git_exec(
                container,
                git + ["status", "--porcelain=v1", "-z", "--untracked-files=all"] + pathspec,
                source_path,
            )
            if code != 0:
                return {
                    "success": False,
                    "error": f"cannot inspect workspace status: {stderr.strip() or 'git failed'}",
                }
            changed = self._parse_porcelain_status(status_raw)

            code, diff_raw, stderr = self._workspace_git_exec(
                container,
                git + [
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    f"--unified={context_lines}",
                    baseline,
                ] + pathspec,
                source_path,
            )
            if code != 0:
                return {
                    "success": False,
                    "error": f"cannot inspect workspace diff: {stderr.strip() or 'git failed'}",
                }
        except Exception as e:
            logger.error("[%s] workspace diff on %s failed: %s", instance_id, node, e)
            return {"success": False, "error": str(e)}

        lines = diff_raw.splitlines()
        end = min(len(lines), start_line + max_lines)
        untracked = sum(1 for item in changed if item["untracked"])
        groups = {
            "staged": [item for item in changed if item["index"] not in (" ", "?")],
            "unstaged": [item for item in changed if item["worktree"] not in (" ", "?")],
            "untracked": [item for item in changed if item["untracked"]],
        }
        return {
            "success": True,
            "node": node,
            "source_path": source_path,
            "base": base,
            "baseline": baseline,
            "path": path,
            "context_lines": context_lines,
            "changed_files": changed,
            "changed_file_count": len(changed),
            "untracked_file_count": untracked,
            "groups": groups,
            "diff": "\n".join(lines[start_line:end]),
            "start_line": start_line,
            "returned_lines": max(0, end - start_line),
            "total_lines": len(lines),
            "next_start_line": end if end < len(lines) else None,
            "truncated": end < len(lines) or len(diff_raw) >= _WORKSPACE_RAW_CAP,
            "note": (
                "Untracked file names are reported, but untracked content is "
                "not rendered until it is added to Git."
                if untracked else None
            ),
        }

    def workspace_untracked_file(self, instance_id, node, source_path, path):
        """Read an opted-in untracked regular file without following links."""
        container = self._find_node_container(instance_id, node)
        if container is None:
            raise ValueError(f"node {node!r} not found in arena {instance_id}")
        path = self._validate_workspace_path(path)
        if not path:
            raise ValueError("an untracked file path is required")
        summary = self.workspace_diff(
            instance_id, node, source_path, path=path, max_lines=1
        )
        if not summary.get("success"):
            raise ValueError(summary.get("error", "workspace inspection failed"))
        selected = [
            item for item in summary.get("changed_files", [])
            if item.get("path") == path and item.get("untracked")
        ]
        if not selected:
            raise ValueError("selected path is not an untracked file")
        archive_stream, stat = container.get_archive(
            str(PurePosixPath(source_path) / PurePosixPath(path))
        )
        if stat.get("linkTarget"):
            raise ValueError("untracked links cannot be exported")
        size = int(stat.get("size") or 0)
        if size > config.EVIDENCE_UNTRACKED_FILE_MAX_BYTES:
            raise ValueError("untracked file exceeds the configured evidence limit")
        archive_chunks = []
        archive_bytes = 0
        archive_cap = config.EVIDENCE_UNTRACKED_FILE_MAX_BYTES + 1024 * 1024
        for chunk in archive_stream:
            archive_bytes += len(chunk)
            if archive_bytes > archive_cap:
                raise ValueError("untracked archive exceeds the configured evidence limit")
            archive_chunks.append(chunk)
        raw_archive = b"".join(archive_chunks)
        try:
            with tarfile.open(fileobj=io.BytesIO(raw_archive), mode="r:*") as archive:
                members = archive.getmembers()
                if len(members) != 1 or not members[0].isreg():
                    raise ValueError("untracked evidence must be one regular file")
                handle = archive.extractfile(members[0])
                content = handle.read(config.EVIDENCE_UNTRACKED_FILE_MAX_BYTES + 1)
        except (tarfile.TarError, OSError) as exc:
            raise ValueError("could not read untracked evidence file") from exc
        if len(content) > config.EVIDENCE_UNTRACKED_FILE_MAX_BYTES:
            raise ValueError("untracked file exceeds the configured evidence limit")
        return content

    @staticmethod
    def _validate_transfer_path(path: str) -> PurePosixPath:
        if not isinstance(path, str) or not path or "\x00" in path:
            raise ValueError("transfer path must be a non-empty relative path")
        clean = PurePosixPath(path)
        if clean.is_absolute() or any(part in ("", ".", "..") for part in clean.parts):
            raise ValueError("transfer path must stay below the transfer root")
        if len(clean.parts) > 16 or len(str(clean).encode("utf-8")) > 512:
            raise ValueError("transfer path is too deep or long")
        return clean

    def write_transfer_file(self, instance_id, node, path, content):
        container = self._find_node_container(instance_id, node)
        if container is None:
            return {"success": False, "error": f"node {node!r} not found"}
        try:
            clean = self._validate_transfer_path(path)
            if len(content) > config.TRANSFER_MAX_FILE_BYTES:
                raise ValueError("transfer file exceeds the configured limit")
            archive_bytes = io.BytesIO()
            with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
                current = PurePosixPath("nidavellir-transfer")
                root_info = tarfile.TarInfo(str(current))
                root_info.type = tarfile.DIRTYPE
                root_info.mode = 0o700
                archive.addfile(root_info)
                for part in clean.parts[:-1]:
                    current /= part
                    info = tarfile.TarInfo(str(current))
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o700
                    archive.addfile(info)
                info = tarfile.TarInfo(str(PurePosixPath("nidavellir-transfer") / clean))
                info.size = len(content)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(content))
            if not container.put_archive("/opt", archive_bytes.getvalue()):
                return {"success": False, "error": "provider rejected transfer archive"}
            return {
                "success": True,
                "path": str(clean),
                "container_path": str(_TRANSFER_ROOT / clean),
                "bytes": len(content),
            }
        except (OSError, tarfile.TarError, ValueError) as exc:
            return {"success": False, "error": str(exc)}

    def read_transfer_file(self, instance_id, node, path):
        container = self._find_node_container(instance_id, node)
        if container is None:
            raise ValueError(f"node {node!r} not found")
        clean = self._validate_transfer_path(path)
        stream, stat = container.get_archive(str(_TRANSFER_ROOT / clean))
        if stat.get("linkTarget"):
            raise ValueError("transfer links cannot be downloaded")
        if int(stat.get("size") or 0) > config.TRANSFER_MAX_FILE_BYTES:
            raise ValueError("transfer file exceeds the configured limit")
        chunks = []
        seen = 0
        cap = config.TRANSFER_MAX_FILE_BYTES + 1024 * 1024
        for chunk in stream:
            seen += len(chunk)
            if seen > cap:
                raise ValueError("transfer archive exceeds the configured limit")
            chunks.append(chunk)
        try:
            with tarfile.open(fileobj=io.BytesIO(b"".join(chunks)), mode="r:*") as archive:
                members = archive.getmembers()
                if len(members) != 1 or not members[0].isreg():
                    raise ValueError("download target must be one regular file")
                handle = archive.extractfile(members[0])
                content = handle.read(config.TRANSFER_MAX_FILE_BYTES + 1)
        except (OSError, tarfile.TarError) as exc:
            raise ValueError("could not read transfer file") from exc
        if len(content) > config.TRANSFER_MAX_FILE_BYTES:
            raise ValueError("transfer file exceeds the configured limit")
        return content

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

    def observe_lifecycle(self, instance_id):
        label_filter = {"label": f"{LABEL_LAB_ID}={instance_id}"}
        nodes = []
        for container in self.client.containers.list(all=True, filters=label_filter):
            if (container.labels or {}).get(LABEL_ROLE) in {"browser", "http"}:
                continue
            container.reload()
            attrs = container.attrs or {}
            image_id = attrs.get("Image") or getattr(getattr(container, "image", None), "id", None)
            image_attrs = getattr(getattr(container, "image", None), "attrs", {}) or {}
            nodes.append({
                "node": (container.labels or {}).get(LABEL_NODE),
                "role": (container.labels or {}).get(LABEL_ROLE),
                "image_id": image_id,
                "os": image_attrs.get("Os"),
                "architecture": image_attrs.get("Architecture"),
                "state": (attrs.get("State") or {}).get("Status"),
            })
        nodes.sort(key=lambda item: (item.get("node") or "", item.get("role") or ""))
        return {"provider": self.name, "nodes": nodes}

    def check_readiness(self, instance_id, outputs, policy):
        if not isinstance(policy, dict) or policy.get("type") != "http":
            return {"ready": False, "status": "unsupported", "error": "bounded HTTP policy required"}
        node = policy.get("node")
        port = policy.get("port")
        path = policy.get("path", "/health")
        scheme = policy.get("scheme", "http")
        if not isinstance(node, str) or not isinstance(port, int):
            return {"ready": False, "status": "invalid", "error": "readiness node and port required"}
        ip = outputs.get(f"node_{node}_private_ip")
        if not ip:
            return {"ready": False, "status": "unavailable", "error": "readiness node unavailable"}
        response = self.http_request(instance_id, node, ip, port, scheme, path)
        if not response.get("success"):
            return {"ready": False, "status": "transport_failure", "error": response.get("error")}
        expected = int(policy.get("expected_status", 200))
        ready = response.get("status") == expected and not response.get("redirect_location")
        body = response.get("body", "")
        try:
            state = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            state = body
        expected_state = policy.get("expected_state")
        if expected_state is not None and state != expected_state:
            ready = False
        return {
            "ready": ready,
            "status": "passed" if ready else "failed",
            "http_status": response.get("status"),
            "state_digest": lifecycle_manifest.digest(state),
            "body_digest": response.get("body_sha256"),
        }

    def destroy(self, instance_id):
        label_filter = {"label": f"{LABEL_LAB_ID}={instance_id}"}
        errors = []
        mounted_volumes = set()

        try:
            containers = self.client.containers.list(all=True, filters=label_filter)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"could not enumerate owned containers: {exc}"}
        for container in containers:
            try:
                container.reload()
                for mount in (container.attrs or {}).get("Mounts") or []:
                    if mount.get("Type") == "volume" and mount.get("Name"):
                        mounted_volumes.add(mount["Name"])
                logger.info(f"[{instance_id}] Removing container {container.name}")
                container.remove(force=True)
            except Exception as exc:  # noqa: BLE001
                if not _already_absent(exc):
                    errors.append(f"container {getattr(container, 'name', '?')}: {exc}")

        try:
            networks = self.client.networks.list(filters=label_filter)
        except Exception as exc:  # noqa: BLE001
            networks = []
            errors.append(f"could not enumerate owned networks: {exc}")
        for network in networks:
            try:
                logger.info(f"[{instance_id}] Removing network {network.name}")
                network.remove()
            except Exception as exc:  # noqa: BLE001
                if not _already_absent(exc):
                    errors.append(f"network {getattr(network, 'name', '?')}: {exc}")

        # Images are arena-built and labeled. Refuse to conceal an in-use error;
        # the operation remains retryable and shared/unlabelled images are untouched.
        try:
            images = self.client.images.list(filters=label_filter)
        except Exception as exc:  # noqa: BLE001
            images = []
            errors.append(f"could not enumerate owned images: {exc}")
        for image in images:
            image_id = getattr(image, "id", None)
            try:
                self.client.images.remove(image_id, force=False)
                logger.info(f"[{instance_id}] Removing built image {image_id}")
            except Exception as exc:  # noqa: BLE001
                if not _already_absent(exc):
                    errors.append(f"image {image_id}: {exc}")

        try:
            volumes = self.client.volumes.list(filters=label_filter)
        except Exception as exc:  # noqa: BLE001
            volumes = []
            errors.append(f"could not enumerate owned volumes: {exc}")
        owned_volumes = {
            getattr(volume, "name", None): volume
            for volume in volumes
        }
        # Anonymous volumes have no arena labels, but their ownership is proven by
        # the mount of an arena-labelled container observed before its removal.
        for name in mounted_volumes:
            if name in owned_volumes:
                continue
            try:
                volume = self.client.volumes.get(name)
            except Exception as exc:  # noqa: BLE001
                if not _already_absent(exc):
                    errors.append(f"volume {name}: lookup failed: {exc}")
                continue
            if not (getattr(volume, "attrs", {}) or {}).get("Labels"):
                owned_volumes[name] = volume
        for name, volume in owned_volumes.items():
            try:
                volume.remove(force=True)
                logger.info(f"[{instance_id}] Removing volume {name}")
            except Exception as exc:  # noqa: BLE001
                if not _already_absent(exc):
                    errors.append(f"volume {name}: {exc}")

        remaining = {}
        enumerators = {
            "containers": lambda: self.client.containers.list(all=True, filters=label_filter),
            "networks": lambda: self.client.networks.list(filters=label_filter),
            "images": lambda: self.client.images.list(filters=label_filter),
            "volumes": lambda: self.client.volumes.list(filters=label_filter),
        }
        for kind, enumerate_owned in enumerators.items():
            try:
                remaining[kind] = len(enumerate_owned())
            except Exception as exc:  # noqa: BLE001
                remaining[kind] = -1
                errors.append(f"could not verify owned {kind}: {exc}")
        if any(remaining.values()):
            errors.append(f"owned resources remain: {remaining}")
        if errors:
            error = "; ".join(errors)
            logger.error(f"[{instance_id}] docker-local destroy incomplete: {error}")
            return {"success": False, "error": error, "remaining": remaining}
        return {"success": True}
