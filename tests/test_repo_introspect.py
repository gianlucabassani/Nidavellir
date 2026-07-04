"""
Repo introspection (M1-1). The analysis core is pure + network-free, so it is
tested directly over synthetic file maps; the fetcher is tested by pointing
`read_repo_dir` at a fixture directory and `introspect`'s error path is exercised
by monkeypatching the (network-touching) `fetch_repo_files`.
"""
import subprocess

import pytest

import repo_introspect as ri


# --- language detection -------------------------------------------------------

@pytest.mark.parametrize("files,expected", [
    ({"package.json": "{}"}, "node"),
    ({"go.mod": "module x\ngo 1.21\n"}, "go"),
    ({"requirements.txt": "flask\n"}, "python"),
    ({"pyproject.toml": "[project]\n"}, "python"),
    ({"pom.xml": "<project/>"}, "java"),
    ({"Gemfile": "source 'x'"}, "ruby"),
    ({"composer.json": "{}"}, "php"),
    ({"Cargo.toml": "[package]"}, "rust"),
])
def test_language_from_manifest(files, expected):
    assert ri.analyze(files)["language"] == expected


def test_language_manifest_precedence_over_extensions():
    # a python manifest wins even if there are more .js files lying around
    out = ri.analyze({"requirements.txt": "flask"}, ["a.js", "b.js", "c.js", "app.py"])
    assert out["language"] == "python"


def test_language_from_extension_histogram_fallback():
    out = ri.analyze({}, ["main.go", "util.go", "one.py"])
    assert out["language"] == "go"
    assert any("inferred from source extensions" in n for n in out["notes"])


def test_language_none_when_unknown():
    assert ri.analyze({}, ["data.csv", "notes.txt"])["language"] is None


# --- build system tiers -------------------------------------------------------

def test_build_system_compose_beats_dockerfile():
    out = ri.analyze({"docker-compose.yml": "services: {}", "Dockerfile": "FROM x"})
    assert out["build_system"] == "compose"


def test_build_system_dockerfile():
    assert ri.analyze({"Dockerfile": "FROM node:20"})["build_system"] == "dockerfile"


def test_build_system_devcontainer():
    out = ri.analyze({}, [".devcontainer/devcontainer.json"])
    assert out["build_system"] == "devcontainer"


def test_build_system_language_native_then_make_then_unknown():
    assert ri.analyze({"go.mod": "go 1.21"})["build_system"] == "language-native"
    assert ri.analyze({"Makefile": "run:\n\tgo run ."})["build_system"] == "make"
    assert ri.analyze({})["build_system"] == "unknown"


# --- ports: declared beats guessed --------------------------------------------

def test_ports_from_dockerfile_expose():
    out = ri.analyze({"Dockerfile": "FROM x\nEXPOSE 8080/tcp 9000\n"})
    assert out["declared_ports"] == [8080, 9000]
    assert out["port_source"] == "dockerfile-expose"


def test_ports_from_compose_yaml_and_shorthand():
    compose = "services:\n  web:\n    ports:\n      - '8080:80'\n      - 5000\n"
    out = ri.analyze({"docker-compose.yml": compose})
    assert 80 in out["declared_ports"] and 5000 in out["declared_ports"]
    assert out["port_source"] == "compose"


def test_ports_from_readme_prose():
    out = ri.analyze({
        "requirements.txt": "flask",
        "README.md": "Run it and open http://localhost:5000 in your browser.",
    })
    assert out["declared_ports"] == [5000]
    assert out["port_source"] == "readme"


def test_ports_guessed_language_default_is_flagged():
    out = ri.analyze({"package.json": "{}"})
    assert out["declared_ports"] == [3000]
    assert out["port_source"] == "guessed-language-default"
    assert any("verify" in n for n in out["notes"])


def test_declared_dockerfile_wins_over_readme_and_default():
    out = ri.analyze({
        "Dockerfile": "FROM node:20\nEXPOSE 4000\n",
        "package.json": "{}",
        "README.md": "listens on :9999",
    })
    assert out["declared_ports"] == [4000]
    assert out["port_source"] == "dockerfile-expose"


# --- base runtime -------------------------------------------------------------

def test_runtime_from_dockerfile_from():
    out = ri.analyze({"Dockerfile": "FROM python:3.11-slim\n"})
    assert out["base_runtime"] == {"image": "python:3.11-slim", "base": "python", "version": "3.11"}


def test_runtime_from_go_mod():
    out = ri.analyze({"go.mod": "module x\n\ngo 1.21\n"})
    assert out["base_runtime"] == {"kind": "go", "version": "1.21"}


def test_runtime_from_pin_files():
    assert ri.analyze({"requirements.txt": "flask", ".python-version": "3.12.1\n"})["base_runtime"] == {
        "kind": "python", "version": "3.12.1"}
    assert ri.analyze({"package.json": "{}", ".nvmrc": "v20\n"})["base_runtime"] == {
        "kind": "node", "version": "20"}


def test_runtime_from_node_engines():
    out = ri.analyze({"package.json": '{"engines": {"node": ">=18"}}'})
    assert out["base_runtime"] == {"kind": "node", "version": ">=18"}


# --- run hints + readme -------------------------------------------------------

def test_node_run_hints():
    out = ri.analyze({"package.json": '{"scripts": {"start": "node .", "dev": "vite"}}'})
    assert "npm start" in out["run_hints"] and "npm run dev" in out["run_hints"]


def test_procfile_and_make_hints():
    assert "gunicorn app:app" in ri.analyze({"Procfile": "web: gunicorn app:app"})["run_hints"]
    assert "make serve" in ri.analyze({"Makefile": "serve:\n\tpython -m http.server"})["run_hints"]


def test_readme_excerpt_truncated():
    out = ri.analyze({"README.md": "x" * (ri.README_EXCERPT_CHARS + 500)})
    assert out["readme_file"] == "README.md"
    assert out["readme_excerpt"].endswith("(truncated)")
    assert len(out["readme_excerpt"]) <= ri.README_EXCERPT_CHARS + 20


def test_malformed_json_and_compose_do_not_raise():
    out = ri.analyze({"package.json": "{ not json", "docker-compose.yml": ": : bad"})
    assert out["language"] == "node"  # indicator presence still detects language


# --- summarize_for_prompt -----------------------------------------------------

def test_summarize_for_prompt_shape():
    intro = ri.analyze({"Dockerfile": "FROM python:3.11\nEXPOSE 8000\n", "README.md": "hi"})
    s = ri.summarize_for_prompt(intro)
    assert set(s) >= {"language", "build_system", "declared_ports", "readme_excerpt"}
    assert s["declared_ports"] == [8000]
    assert ri.summarize_for_prompt({}) == {}


# --- fetcher I/O (fixture dir) + best-effort introspect -----------------------

def test_read_repo_dir_reads_indicators_and_walks(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM node:20\nEXPOSE 3000\n")
    (tmp_path / "package.json").write_text('{"scripts": {"start": "node ."}}')
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "index.js").write_text("console.log(1)")
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("[core]")
    files, all_paths = ri.read_repo_dir(str(tmp_path))
    assert "Dockerfile" in files and "package.json" in files
    assert "src/index.js" in all_paths
    assert not any(p.startswith(".git") for p in all_paths)  # .git pruned
    out = ri.analyze(files, all_paths)
    assert out["language"] == "node" and out["declared_ports"] == [3000]


def test_read_repo_dir_skips_oversize_files(tmp_path):
    (tmp_path / "README.md").write_text("x" * (ri.MAX_FILE_BYTES + 1))
    files, _ = ri.read_repo_dir(str(tmp_path))
    assert "README.md" not in files


def test_introspect_never_raises_on_unsafe_host(monkeypatch):
    out = ri.introspect("https://169.254.169.254/x/y")
    assert out["repo"].endswith("y") and "error" in out
    assert out["language"] is None  # analyze({}) shape still present


def test_introspect_never_raises_on_clone_failure(monkeypatch):
    def boom(repo, ref=None):
        raise subprocess.SubprocessError("clone exploded")

    monkeypatch.setattr(ri, "fetch_repo_files", boom)
    out = ri.introspect("https://github.com/org/repo")
    assert "error" in out and out["build_system"] == "unknown"


def test_introspect_success_path(monkeypatch):
    def fake_fetch(repo, ref=None):
        return {"go.mod": "module x\ngo 1.22\n"}, ["main.go"]

    monkeypatch.setattr(ri, "fetch_repo_files", fake_fetch)
    out = ri.introspect("https://github.com/org/repo", ref="v1")
    assert out["language"] == "go" and out["ref"] == "v1"
    assert out["base_runtime"] == {"kind": "go", "version": "1.22"}
