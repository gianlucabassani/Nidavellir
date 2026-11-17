"""
Deterministic build-tier planner (ROADMAP M1 / backlog M1-2; ADR-0008).

Maps a repo introspection (`repo_introspect.summarize_for_prompt` shape) to a
**build plan**: which deterministic strategy stands the repo up, with what
parameters. Deterministic-first — honor what the repo already ships (a Dockerfile,
a compose file, a devcontainer) before reaching for a zero-config buildpack, and
fall back to `none` (→ the configurator / LLM-synthesis path, M1-3) when nothing
deterministic applies.

Pure and network-free (like `repo_introspect.analyze` / `generator.build_messages`)
so it is fully unit-testable. It only *decides*; execution lives in the provider
(`docker_local._build_service_image`) via the existing `service.source` seam.

Only the **dockerfile** strategy is executable this increment (it reuses the
existing single-Dockerfile builder). `compose`, `devcontainer`, and `buildpack`
are classified with a reason but not yet executed — each needs infra M1-2 does not
add (compose runtime model, the `devcontainer` CLI, the `pack` binary). See ADR-0008.
"""
from __future__ import annotations

# Strategies the planner can emit.
DOCKERFILE = "dockerfile"
COMPOSE = "compose"
DEVCONTAINER = "devcontainer"
BUILDPACK = "buildpack"
NONE = "none"

# Which strategies this increment can actually execute (ADR-0008 increment
# boundary). The rest are classified so the operator sees the plan, but the wizard
# will keep the bare-box + configurator fallback for them.
EXECUTABLE = frozenset({DOCKERFILE})

# Languages a buildpack engine (Paketo / Railpack) can stand up with no Dockerfile.
_BUILDPACK_LANGS = frozenset({"node", "python", "go", "java", "ruby", "php"})


class BuildPlan:
    """The chosen build strategy + parameters. ``executable`` says whether this
    increment can run it (dockerfile only); ``deterministic`` says whether the
    strategy is grounded in what the repo ships (everything but ``none``)."""

    __slots__ = ("strategy", "dockerfile", "context", "ports", "reason")

    def __init__(self, strategy, *, dockerfile=None, context=None, ports=None, reason=""):
        self.strategy = strategy
        self.dockerfile = dockerfile          # path within the repo (tier-1)
        self.context = context                # build-context subdir, if any
        self.ports = list(ports or [])        # ports to publish on the built service
        self.reason = reason

    @property
    def deterministic(self) -> bool:
        return self.strategy != NONE

    @property
    def executable(self) -> bool:
        return self.strategy in EXECUTABLE

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "dockerfile": self.dockerfile,
            "context": self.context,
            "ports": self.ports,
            "deterministic": self.deterministic,
            "executable": self.executable,
            "reason": self.reason,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"BuildPlan({self.to_dict()!r})"


def _detected(intro: dict) -> set:
    return set(intro.get("detected_files") or intro.get("indicators") or [])


def plan_build(introspection: dict | None) -> BuildPlan:
    """Choose the deterministic build strategy for a repo from its introspection.

    Priority mirrors ADR-0008 tier-1: an existing **Dockerfile** (the repo's own
    build) wins; then **compose**, then **devcontainer** (both classified, not yet
    executed); then a **buildpack** for a recognized language with no shipped build
    file; else **none** (→ configurator / LLM synthesis fallback). ``build_system``
    from introspection is the primary signal, cross-checked against the detected
    files so a stale/absent field still yields a sane plan."""
    intro = introspection or {}
    if intro.get("error"):
        return BuildPlan(NONE, reason=f"introspection failed: {intro['error']}")

    detected = _detected(intro)
    build_system = intro.get("build_system")
    ports = list(intro.get("declared_ports") or [])

    has_dockerfile = any(f in detected for f in ("Dockerfile", "dockerfile")) \
        or build_system == DOCKERFILE
    has_compose = build_system == COMPOSE or any(
        f in detected for f in
        ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"))
    has_devcontainer = build_system == DEVCONTAINER or any(
        f in detected for f in (".devcontainer/devcontainer.json", "devcontainer.json"))

    # Tier-1: honor a shipped Dockerfile — the repo's own build, most faithful.
    if has_dockerfile:
        df = "Dockerfile" if "Dockerfile" in detected or "dockerfile" not in detected else "dockerfile"
        return BuildPlan(
            DOCKERFILE, dockerfile=df, ports=ports,
            reason="repo ships a Dockerfile — build it directly (BuildKit)",
        )

    # Tier-1: compose / devcontainer — classified, execution deferred (ADR-0008).
    if has_compose:
        return BuildPlan(
            COMPOSE, ports=ports,
            reason="repo ships a compose file — compose runtime not yet wired; "
                   "using the configurator fallback",
        )
    if has_devcontainer:
        return BuildPlan(
            DEVCONTAINER, ports=ports,
            reason="repo ships a devcontainer — the devcontainer CLI is not yet in "
                   "the orchestrator image; using the configurator fallback",
        )

    # Tier-2: zero-config buildpack for a recognized language — classified,
    # execution deferred until `pack` (Paketo) ships in the orchestrator image.
    if intro.get("language") in _BUILDPACK_LANGS:
        return BuildPlan(
            BUILDPACK, ports=ports,
            reason=f"no build file, but {intro['language']} is buildpack-detectable; "
                   "the pack binary is not yet in the orchestrator image — using "
                   "the configurator fallback",
        )

    # Tier-3 handoff: nothing deterministic — the configurator / LLM-synthesis path.
    return BuildPlan(
        NONE,
        reason="no Dockerfile / compose / devcontainer and no buildpack-detectable "
               "language — falling back to the configurator (LLM synthesis is M1-3)",
    )
