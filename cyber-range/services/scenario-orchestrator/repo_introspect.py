"""
Repo introspection (ROADMAP M1 / backlog M1-1).

Grounds the SUT flow in the *actual* repository instead of letting a model guess
the runtime, package manager, and port (the field-log failure: `npm`/`python3`/
port picked wrong on real repos). It detects the primary language, the build
system (an existing Dockerfile / compose / devcontainer, else a language-native
build), the declared listening ports, and the base runtime, and pulls a README
excerpt. Its output feeds three consumers:

  - `setup_proposer.py`  — the HITL setup drafter grounds each build/run step in it
  - `generator.py`       — an optional grounding block when a brief targets a repo
  - the build selector   — M1-2/3 (deterministic build tier + LLM synthesis) key
                            off `build_system` / `declared_ports` / `base_runtime`

Split like its sibling modules (`generator.py`, `setup_proposer.py`): a **pure,
network-free analysis core** (`analyze` over a mapping of file contents) that is
fully unit-testable, plus a thin **fetcher** (`fetch_repo_files`) that does the
one bit of I/O — a shallow, SSRF-guarded clone. `introspect` combines them and is
best-effort: it NEVER raises into the caller (a repo that can't be read yields an
introspection carrying an `error` note, so a deploy is never broken by it).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 — fixed argv (no shell), timeout + guarded host
import tempfile

import netguard

# --- bounds (introspection reads untrusted repos; keep every read bounded) ----
MAX_FILE_BYTES = 64 * 1024        # per indicator file we read into memory
MAX_TREE_ENTRIES = 4000           # cap the path walk (huge monorepos)
README_EXCERPT_CHARS = 2000       # README trimmed to this for a prompt
CLONE_TIMEOUT_SECONDS = 90        # a shallow clone should be quick; fail fast

# Top-level files worth reading in full (content parsed for ports/runtime/hints).
# Kept small + explicit so the fetcher reads a bounded, predictable set.
_READ_FILES = (
    "Dockerfile", "dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    ".devcontainer/devcontainer.json", "devcontainer.json",
    "package.json", "requirements.txt", "pyproject.toml", "setup.py",
    "Pipfile", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "Cargo.toml", "Makefile", "makefile",
    "Procfile", ".python-version", ".nvmrc", ".ruby-version", ".tool-versions",
    "runtime.txt",
    "README.md", "README.rst", "README.txt", "README", "readme.md",
)

# Language indicator files → language slug. First match (in this order) wins.
_LANG_INDICATORS = (
    ("package.json", "node"),
    ("go.mod", "go"),
    ("pyproject.toml", "python"),
    ("requirements.txt", "python"),
    ("Pipfile", "python"),
    ("setup.py", "python"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("build.gradle.kts", "java"),
    ("Gemfile", "ruby"),
    ("composer.json", "php"),
    ("Cargo.toml", "rust"),
)

# Fallback: source-extension histogram → language, when no manifest is present.
_EXT_LANG = {
    ".py": "python", ".js": "node", ".ts": "node", ".jsx": "node", ".tsx": "node",
    ".go": "go", ".java": "java", ".kt": "java", ".rb": "ruby", ".php": "php",
    ".rs": "rust",
}

# A language's conventional dev port, used only when nothing is declared (tagged
# `guessed` in the output so a consumer can tell a declared port from a default).
_LANG_DEFAULT_PORT = {
    "node": 3000, "python": 8000, "ruby": 3000, "php": 8080, "go": 8080, "java": 8080,
}

_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_FROM_RE = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE | re.MULTILINE)
# Ports mentioned in prose/config, e.g. "localhost:8080", ":3000", "port 5000".
_README_PORT_RE = re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|:)(?::)?(\d{2,5})\b")
_PORT_WORD_RE = re.compile(r"\bport[\s:=]+(\d{2,5})\b", re.IGNORECASE)


def _clip_port(value) -> int | None:
    try:
        p = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return p if 1 <= p <= 65535 else None


def _strip_jsonc(text: str) -> str:
    """devcontainer.json is JSONC — drop `// line` and `/* block */` comments so a
    plain json.loads can parse it. Best-effort; safe on strict JSON too."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)//.*$", "", text)
    return text


def _load_json(text: str) -> dict:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


# --- per-signal parsers (pure) ------------------------------------------------

def _dockerfile_ports(text: str) -> list[int]:
    ports: list[int] = []
    for m in _EXPOSE_RE.finditer(text):
        for tok in m.group(1).split():
            p = _clip_port(tok.split("/")[0])  # strip "/tcp"
            if p and p not in ports:
                ports.append(p)
    return ports


def _dockerfile_runtime(text: str) -> dict | None:
    m = _FROM_RE.search(text)
    if not m:
        return None
    ref = m.group(1)
    if ref.lower() == "scratch":
        return {"image": ref}
    name, _, tag = ref.partition(":")
    base = name.rsplit("/", 1)[-1]
    out: dict = {"image": ref, "base": base}
    if tag:
        out["version"] = tag.split("-")[0]
    return out


def _compose_ports(text: str) -> list[int]:
    """Container-side ports from a compose file. Tries YAML, falls back to a
    tolerant regex so a malformed/partial compose still yields something."""
    ports: list[int] = []
    try:
        import yaml  # declared dep; import lazily so the core has no hard dep

        doc = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — arbitrary repo content; never trust it to parse
        doc = None
    if isinstance(doc, dict):
        for svc in (doc.get("services") or {}).values():
            if not isinstance(svc, dict):
                continue
            for entry in svc.get("ports") or []:
                # "8080:80", "80", {target: 80, published: 8080}, "127.0.0.1:8080:80"
                if isinstance(entry, dict):
                    p = _clip_port(entry.get("target"))
                elif isinstance(entry, (str, int)):
                    parts = str(entry).split(":")
                    p = _clip_port(parts[-1].split("/")[0])
                else:
                    p = None
                if p and p not in ports:
                    ports.append(p)
        if ports:
            return ports
    # regex fallback: grab the right-hand (container) side of "a:b" port lines
    for m in re.finditer(r"-\s*[\"']?(?:\d[\d.]*:)?(\d{2,5}):(\d{2,5})", text):
        p = _clip_port(m.group(2))
        if p and p not in ports:
            ports.append(p)
    return ports


def _prose_ports(text: str) -> list[int]:
    ports: list[int] = []
    for rx in (_README_PORT_RE, _PORT_WORD_RE):
        for m in rx.finditer(text):
            p = _clip_port(m.group(1))
            # skip obvious non-ports (years, tiny numbers already excluded by \d{2,5})
            if p and p >= 80 and p not in ports:
                ports.append(p)
    return ports


def _node_hints(pkg: dict) -> tuple[list[str], dict | None]:
    hints: list[str] = []
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    for key in ("start", "serve", "dev"):
        if key in scripts:
            hints.append(f"npm run {key}" if key != "start" else "npm start")
    runtime = None
    engines = pkg.get("engines") if isinstance(pkg.get("engines"), dict) else {}
    if engines.get("node"):
        runtime = {"kind": "node", "version": str(engines["node"])}
    return hints, runtime


def _make_targets(text: str) -> list[str]:
    targets = []
    for m in re.finditer(r"(?m)^([a-zA-Z][\w-]*):", text):
        t = m.group(1)
        if t not in ("PHONY", ".PHONY") and t not in targets:
            targets.append(t)
    return [f"make {t}" for t in targets[:6]]


# --- the analysis core (pure, network-free, unit-tested) ----------------------

def analyze(files: dict[str, str], all_paths: list[str] | None = None) -> dict:
    """Analyse a repo from its already-read top-level ``files`` (path -> text) and
    an optional ``all_paths`` list (for the source-extension fallback). Pure and
    deterministic — this is the unit-tested heart. Returns the introspection dict:

        language, build_system, base_runtime, declared_ports, port_source,
        run_hints, readme_excerpt, indicators, notes
    """
    files = {k: v for k, v in (files or {}).items() if isinstance(v, str)}
    present = set(files) | set(all_paths or [])
    indicators = sorted(f for f in _READ_FILES if f in files)
    notes: list[str] = []

    # --- language ---------------------------------------------------------
    language = None
    for fname, lang in _LANG_INDICATORS:
        if fname in files:
            language = lang
            break
    if language is None and all_paths:
        counts: dict[str, int] = {}
        for path in all_paths:
            ext = os.path.splitext(path)[1].lower()
            if ext in _EXT_LANG:
                counts[_EXT_LANG[ext]] = counts.get(_EXT_LANG[ext], 0) + 1
        if counts:
            language = max(counts, key=counts.get)
            notes.append(f"language inferred from source extensions ({language})")

    # --- build system (deterministic tiers first — feeds M1-2/3) ----------
    has_dockerfile = "Dockerfile" in files or "dockerfile" in files
    compose_files = [f for f in files if f in (
        "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")]
    has_devcontainer = any(
        f in present for f in (".devcontainer/devcontainer.json", "devcontainer.json"))
    if compose_files:
        build_system = "compose"
    elif has_dockerfile:
        build_system = "dockerfile"
    elif has_devcontainer:
        build_system = "devcontainer"
    elif language:
        build_system = "language-native"
    elif "Makefile" in files or "makefile" in files:
        build_system = "make"
    else:
        build_system = "unknown"

    # --- ports (declared beats guessed) -----------------------------------
    declared: list[int] = []
    port_source = None
    df_text = files.get("Dockerfile") or files.get("dockerfile") or ""
    if df_text:
        declared = _dockerfile_ports(df_text)
        if declared:
            port_source = "dockerfile-expose"
    if not declared and compose_files:
        declared = _compose_ports(files[compose_files[0]])
        if declared:
            port_source = "compose"
    if not declared:
        readme_raw = _first_readme(files)[1]
        if readme_raw:
            declared = _prose_ports(readme_raw)
            if declared:
                port_source = "readme"
    if not declared and language in _LANG_DEFAULT_PORT:
        declared = [_LANG_DEFAULT_PORT[language]]
        port_source = "guessed-language-default"
        notes.append(
            f"no port declared; defaulting to {declared[0]} for {language} — verify"
        )

    # --- run hints --------------------------------------------------------
    run_hints: list[str] = []
    node_runtime = None
    if "package.json" in files:
        hints, node_runtime = _node_hints(_load_json(files["package.json"]))
        run_hints += hints
    if "Procfile" in files:
        for line in files["Procfile"].splitlines():
            if ":" in line:
                run_hints.append(line.split(":", 1)[1].strip())
    if not run_hints and ("Makefile" in files or "makefile" in files):
        run_hints += _make_targets(files.get("Makefile") or files.get("makefile") or "")

    # --- base runtime (most specific source wins) -------------------------
    # Dockerfile FROM > version-pin file / go.mod > package.json engines >
    # the generic {kind: language} last resort.
    base_runtime = None
    if df_text:
        base_runtime = _dockerfile_runtime(df_text)
    if base_runtime is None:
        base_runtime = _runtime_from_pins(files)
    if base_runtime is None and node_runtime:
        base_runtime = node_runtime
    if base_runtime is None and language:
        base_runtime = {"kind": language}

    # --- README excerpt ---------------------------------------------------
    readme_name, readme_text = _first_readme(files)
    readme_excerpt = ""
    if readme_text:
        readme_excerpt = readme_text.strip()[:README_EXCERPT_CHARS]
        if len(readme_text.strip()) > README_EXCERPT_CHARS:
            readme_excerpt += "\n…(truncated)"

    return {
        "language": language,
        "build_system": build_system,
        "base_runtime": base_runtime,
        "declared_ports": declared,
        "port_source": port_source,
        "run_hints": run_hints[:8],
        "readme_file": readme_name,
        "readme_excerpt": readme_excerpt,
        "indicators": indicators,
        "notes": notes,
    }


def _first_readme(files: dict[str, str]) -> tuple[str | None, str]:
    for name in ("README.md", "README.rst", "README.txt", "README", "readme.md"):
        if name in files:
            return name, files[name]
    return None, ""


def _runtime_from_pins(files: dict[str, str]) -> dict | None:
    """Base runtime from a version-pin file or a manifest declaration (specific
    signals only; the generic {kind: language} last resort is applied by the
    caller so it never masks these)."""
    if ".python-version" in files:
        return {"kind": "python", "version": files[".python-version"].strip().splitlines()[0]}
    if "runtime.txt" in files and files["runtime.txt"].strip().lower().startswith("python"):
        return {"kind": "python", "version": files["runtime.txt"].strip().split("-")[-1]}
    if ".nvmrc" in files:
        return {"kind": "node", "version": files[".nvmrc"].strip().lstrip("v").splitlines()[0]}
    if ".ruby-version" in files:
        return {"kind": "ruby", "version": files[".ruby-version"].strip().splitlines()[0]}
    if "go.mod" in files:
        m = re.search(r"(?m)^go\s+([\d.]+)", files["go.mod"])
        if m:
            return {"kind": "go", "version": m.group(1)}
    return None


def summarize_for_prompt(intro: dict) -> dict:
    """A compact, prompt-friendly subset for embedding in a brief/system prompt —
    the fields a model actually needs to stop guessing, without the full README."""
    if not intro:
        return {}
    readme = intro.get("readme_excerpt") or ""
    return {
        "language": intro.get("language"),
        "build_system": intro.get("build_system"),
        "base_runtime": intro.get("base_runtime"),
        "declared_ports": intro.get("declared_ports"),
        "port_source": intro.get("port_source"),
        "run_hints": intro.get("run_hints"),
        "detected_files": intro.get("indicators"),
        "readme_excerpt": readme[:1200] + ("…" if len(readme) > 1200 else ""),
        "notes": intro.get("notes"),
    }


# --- the fetcher (the one bit of I/O; guarded + bounded) ----------------------

def read_repo_dir(root: str) -> tuple[dict[str, str], list[str]]:
    """Read the indicator files (bounded) and walk the tree (path list, bounded)
    from an already-checked-out repo directory. Pure filesystem read — no network;
    unit-testable by pointing it at a fixture directory."""
    files: dict[str, str] = {}
    for rel in _READ_FILES:
        path = os.path.join(root, rel)
        try:
            if os.path.isfile(path) and os.path.getsize(path) <= MAX_FILE_BYTES:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    files[rel] = fh.read()
        except OSError:
            continue
    all_paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            all_paths.append(os.path.relpath(os.path.join(dirpath, fn), root))
            if len(all_paths) >= MAX_TREE_ENTRIES:
                return files, all_paths
    return files, all_paths


def fetch_repo_files(repo: str, ref: str | None = None) -> tuple[dict[str, str], list[str]]:
    """Shallow-clone ``repo`` (optionally at ``ref``) into a temp dir, read the
    indicator files + path list, and clean up. SSRF-guarded (authoritative resolve)
    and time-boxed. Raises on failure — callers use ``introspect`` for best-effort.
    """
    netguard.assert_public_host(repo)  # resolves the host — reject internal/metadata
    tmp = tempfile.mkdtemp(prefix="nv-introspect-")
    # GIT_TERMINAL_PROMPT=0: never block on a credential prompt for a private repo.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        subprocess.run(  # nosec B603 — fixed argv, no shell, timeout, guarded host
            ["git", "clone", "--quiet", "--depth", "1", "--no-tags", "--", repo, tmp],
            check=True, capture_output=True, timeout=CLONE_TIMEOUT_SECONDS, env=env,
        )
        if ref:
            # Best-effort pin: fetch the specific ref shallowly, then check it out.
            # A branch/tag/SHA all work via FETCH_HEAD; failure leaves the default
            # branch checked out (introspection is best-effort, not a build).
            fetch = subprocess.run(  # nosec B603
                ["git", "-C", tmp, "fetch", "--quiet", "--depth", "1", "origin", ref],
                capture_output=True, timeout=CLONE_TIMEOUT_SECONDS, env=env,
            )
            if fetch.returncode == 0:
                subprocess.run(  # nosec B603
                    ["git", "-C", tmp, "checkout", "--quiet", "FETCH_HEAD"],
                    capture_output=True, timeout=CLONE_TIMEOUT_SECONDS, env=env,
                )
        return read_repo_dir(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def introspect(repo: str, ref: str | None = None) -> dict:
    """Best-effort end-to-end introspection: fetch + analyse, echoing ``repo``/
    ``ref``. NEVER raises — on any failure it returns a minimal introspection with
    an ``error`` note so a caller (deploy, proposal drafting) is never broken by it.
    """
    base = {"repo": repo, "ref": ref}
    try:
        files, all_paths = fetch_repo_files(repo, ref)
    except netguard.UnsafeHostError as e:
        return {**base, "error": f"unsafe repo host: {e}", **analyze({})}
    except (subprocess.SubprocessError, OSError) as e:
        return {**base, "error": f"could not read repo: {e}", **analyze({})}
    return {**base, **analyze(files, all_paths)}
