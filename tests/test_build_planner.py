"""
Deterministic build-tier planner (M1-2, ADR-0008). Pure selection logic over an
introspection dict — no network, no docker.
"""
import build_planner as bp
import repo_introspect as ri


def _intro(**kw):
    """A summarize_for_prompt-shaped introspection with sane defaults."""
    base = {"language": None, "build_system": "unknown", "declared_ports": [],
            "detected_files": []}
    base.update(kw)
    return base


# --- tier-1: honor a shipped Dockerfile --------------------------------------

def test_dockerfile_wins_and_is_executable():
    plan = bp.plan_build(_intro(build_system="dockerfile", detected_files=["Dockerfile"],
                                declared_ports=[8080]))
    assert plan.strategy == bp.DOCKERFILE
    assert plan.executable and plan.deterministic
    assert plan.dockerfile == "Dockerfile"
    assert plan.ports == [8080]


def test_dockerfile_detected_even_if_build_system_says_compose_but_no_compose_file():
    # build_system is the primary signal, but a detected Dockerfile still plans a
    # dockerfile build when no compose file is actually present.
    plan = bp.plan_build(_intro(build_system="dockerfile", detected_files=["Dockerfile", "README.md"]))
    assert plan.strategy == bp.DOCKERFILE


def test_lowercase_dockerfile_path():
    plan = bp.plan_build(_intro(build_system="dockerfile", detected_files=["dockerfile"]))
    assert plan.dockerfile == "dockerfile"


# --- classified-but-deferred tiers -------------------------------------------

def test_compose_is_deterministic_but_not_executable():
    plan = bp.plan_build(_intro(build_system="compose", detected_files=["compose.yml"]))
    assert plan.strategy == bp.COMPOSE
    assert plan.deterministic and not plan.executable
    assert "compose" in plan.reason


def test_compose_beats_devcontainer_and_buildpack():
    plan = bp.plan_build(_intro(
        build_system="compose", language="python",
        detected_files=["compose.yaml", ".devcontainer/devcontainer.json"]))
    assert plan.strategy == bp.COMPOSE


def test_devcontainer_classified():
    plan = bp.plan_build(_intro(build_system="devcontainer",
                                detected_files=[".devcontainer/devcontainer.json"]))
    assert plan.strategy == bp.DEVCONTAINER
    assert plan.deterministic and not plan.executable


def test_buildpack_for_language_without_build_file():
    plan = bp.plan_build(_intro(build_system="language-native", language="go",
                                detected_files=["go.mod"]))
    assert plan.strategy == bp.BUILDPACK
    assert plan.deterministic and not plan.executable
    assert "go" in plan.reason


def test_dockerfile_beats_buildpack_language():
    plan = bp.plan_build(_intro(build_system="dockerfile", language="python",
                                detected_files=["Dockerfile", "requirements.txt"]))
    assert plan.strategy == bp.DOCKERFILE


# --- tier-3 handoff (none) ----------------------------------------------------

def test_none_when_nothing_deterministic():
    plan = bp.plan_build(_intro(build_system="unknown", language=None,
                                detected_files=["data.csv"]))
    assert plan.strategy == bp.NONE
    assert not plan.deterministic and not plan.executable


def test_none_on_introspection_error():
    plan = bp.plan_build({"error": "could not read repo: boom"})
    assert plan.strategy == bp.NONE
    assert "introspection failed" in plan.reason


def test_none_on_empty_or_missing_introspection():
    assert bp.plan_build(None).strategy == bp.NONE
    assert bp.plan_build({}).strategy == bp.NONE


# --- to_dict + integration with real introspection ---------------------------

def test_to_dict_shape():
    d = bp.plan_build(_intro(build_system="dockerfile", detected_files=["Dockerfile"])).to_dict()
    assert set(d) == {"strategy", "dockerfile", "context", "ports",
                      "deterministic", "executable", "reason"}


def test_plans_from_real_analyze_output():
    # end-to-end with the analyze() core: a Dockerfile+EXPOSE repo → executable plan
    intro = ri.summarize_for_prompt(
        ri.analyze({"Dockerfile": "FROM node:20\nEXPOSE 3000\n", "package.json": "{}"}))
    plan = bp.plan_build(intro)
    assert plan.strategy == bp.DOCKERFILE and plan.ports == [3000]
    # a compose repo → classified compose
    intro2 = ri.summarize_for_prompt(
        ri.analyze({"docker-compose.yml": "services:\n  web:\n    ports: ['80:80']\n"}))
    assert bp.plan_build(intro2).strategy == bp.COMPOSE
