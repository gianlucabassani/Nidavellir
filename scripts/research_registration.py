"""Bound a committed registration to a standalone probe's executable definition.

No fixture import or target operation is allowed while deriving/checking a plan.
Definitions are canonical Python syntax, not interpretations of journal prose.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = "scripts/probe-paperless-variants.py"
FIXTURE = "cyber-range/fixtures/paperless/build_fixture.py"
FILES = (PROBE, FIXTURE, "scripts/research_registration.py",
         "cyber-range/services/scenario-orchestrator/research_code.py")
SCHEMA = "nidavellir/research-registration/v1"
MAX_BYTES = 262144
_spec = importlib.util.spec_from_file_location("registration_git", ROOT / FILES[-1])
git = importlib.util.module_from_spec(_spec)
_git_source = (ROOT / FILES[-1]).read_bytes()
exec(compile(_git_source, str(ROOT / FILES[-1]), "exec"),
     git.__dict__)  # nosec B102 - trusted local Git runner; bypass stale pyc
_LOADED_SOURCES = {
    FILES[-1]: hashlib.sha256(_git_source).hexdigest(),
}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def _tag(tag: str) -> None:
    if not isinstance(tag, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", tag):
        raise SystemExit("refusing to probe: --round-tag must match [a-z0-9-]{1,32}")


def source_bytes(root: Path, name: str) -> bytes:
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise SystemExit(f"refusing registration: source path is not owned: {name}")
    try:
        with path.open("rb") as handle:
            value = handle.read(MAX_BYTES + 1)
    except OSError as exc:
        raise SystemExit(f"refusing registration: source unavailable: {name}") from exc
    if len(value) > MAX_BYTES:
        raise SystemExit(f"refusing registration: source exceeds byte cap: {name}")
    return value


def _ids(node):
    """Extract result/record IDs, including setup-failure alternatives."""
    found = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not call.args:
            continue
        if isinstance(call.func, ast.Name) and call.func.id == "record":
            value = call.args[0]
        elif (isinstance(call.func, ast.Attribute) and call.func.attr == "append"
              and isinstance(call.func.value, ast.Name) and call.func.value.id == "results"
              and isinstance(call.args[0], ast.Dict)):
            value = next((v for k, v in zip(call.args[0].keys, call.args[0].values, strict=True)
                          if isinstance(k, ast.Constant) and k.value == "id"), None)
        else:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.append(value.value)
    return sorted(set(found))


def candidate(tag: str, root: Path = ROOT) -> dict:
    _tag(tag)
    return _candidate(tag, {name: source_bytes(root, name) for name in FILES})


def _candidate(tag: str, source: dict) -> dict:
    try:
        fixture = ast.parse(source[FIXTURE])
        constants = {n.targets[0].id: ast.literal_eval(n.value) for n in fixture.body
                     if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                     and n.targets[0].id in {"PINS", "VERSION", "ADMIN", "MEMBER", "MAILBOX"}}
        tree = ast.parse(source[PROBE])
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    except (SyntaxError, ValueError, StopIteration) as exc:
        raise SystemExit("refusing registration: cannot derive executable definitions") from exc
    pins = constants.get("PINS")
    version = constants.get("VERSION")
    if (not isinstance(version, str) or not 1 <= len(version) <= 64 or
            not isinstance(pins, dict) or not pins or any(
                not isinstance(name, str) or not isinstance(value, str) or
                not re.fullmatch(r".{1,512}@sha256:[0-9a-f]{64}", value)
                for name, value in pins.items())):
        raise SystemExit("refusing registration: immutable target identity required")
    secrets = {v["password"] for k, v in constants.items()
               if k in {"ADMIN", "MEMBER", "MAILBOX"}}

    class MaskSecrets(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802
            if isinstance(node.value, str) and node.value in secrets:
                return ast.copy_location(ast.Constant("sha256:" + hashlib.sha256(
                    node.value.encode()).hexdigest()), node)
            return node

    definitions = {}
    for statement in main.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        ids = _ids(statement)
        if not ids:
            continue
        definition = ast.unparse(MaskSecrets().visit(statement))
        for hid in ids:
            definitions.setdefault(hid, []).append(definition)
    hypotheses = [{"id": hid, "definitions": values} for hid, values in definitions.items()]
    if not hypotheses or len(hypotheses) > 100:
        raise SystemExit("refusing registration: no bounded hypothesis definitions")
    return {"schema": SCHEMA, "round_tag": tag,
            "target": {"version": constants["VERSION"], "pins": constants["PINS"]},
            "sources": {name: hashlib.sha256(value).hexdigest() for name, value in source.items()},
            "hypotheses": hypotheses}


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate registration key")
        result[key] = value
    return result


def check(prereg: str, tag: str, root: Path = ROOT, *, loaded_probe_digest: str,
          loaded_gate_digest: str, loaded_functions: dict) -> dict:
    _tag(tag)
    if not isinstance(prereg, str) or not re.fullmatch(r"[0-9a-fA-F]{4,40}", prereg):
        raise SystemExit("refusing registration: require a commit SHA")
    try:
        sha = git.resolve_ref(root, prereg)
    except git.ResearchCodeError as exc:
        raise SystemExit("refusing to probe: unknown pre-registration") from exc
    try:
        git.run_git(root, "merge-base", "--is-ancestor", sha, "HEAD")
    except git.ResearchCodeError as exc:
        raise SystemExit("refusing registration: commit is not an ancestor of HEAD") from exc
    path = f"docs/research/registrations/{tag}.json"
    try:
        raw = git.run_git(root, "show", f"{sha}:{path}", max_bytes=MAX_BYTES)
        if raw.truncated:
            raise ValueError("partial registration")
        registered = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except (git.ResearchCodeError, ValueError) as exc:
        raise SystemExit(f"refusing registration: committed structured manifest unavailable: {path}") from exc
    source = {name: source_bytes(root, name) for name in FILES}
    current = _candidate(tag, source)
    if not isinstance(registered, dict) or registered.keys() != current.keys():
        raise SystemExit("refusing registration: schema fields mismatch")
    mismatches = [key for key in current if registered[key] != current[key]]
    if mismatches:
        raise SystemExit("refusing registration: mismatch in " + ", ".join(mismatches))
    loaded = {**_LOADED_SOURCES, PROBE: loaded_probe_digest,
              "scripts/research_registration.py": loaded_gate_digest}
    if any(current["sources"][name] != value for name, value in loaded.items()):
        raise SystemExit("refusing registration: loaded executable differs from registered source")
    # A stale timestamp-based pyc may compute a fresh file hash at startup.
    # Compare the actual loaded functions to compilation of the checked bytes.
    required = {"main", "status_of", "finalize_results", "registration_candidate", "check_prereg"}
    if set(loaded_functions) != required:
        raise SystemExit("refusing registration: loaded executable function set differs")
    filename = loaded_functions["main"].co_filename
    compiled = compile(source[PROBE], filename, "exec", dont_inherit=True)
    expected_functions = {code.co_name: code for code in compiled.co_consts
                          if isinstance(code, types.CodeType)}
    if any(expected_functions.get(name) != code for name, code in loaded_functions.items()):
        raise SystemExit("refusing registration: loaded executable code differs from source")
    # Keep the old marker as an advisory hint only; never an admission condition.
    hint = False
    try:
        journal = git.run_git(root, "show", sha, "--", "docs/JOURNAL.md")
        added = "\n".join(line[1:] for line in journal.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        hint = not journal.truncated and tag in added and "hypothes" in added.lower()
    except git.ResearchCodeError:
        pass
    return {"schema": "nidavellir/research-registration-receipt/v1",
            "registration_commit": sha, "registration_path": path,
            "registration_digest": digest(registered), "execution_digest": digest(current),
            "target": current["target"], "sources": current["sources"],
            "hypothesis_ids": [h["id"] for h in current["hypotheses"]],
            "definition_digests": {h["id"]: digest(h) for h in current["hypotheses"]},
            "journal_marker_hint": hint}


def finalize(results: list[dict], receipt: dict) -> dict:
    ids = [row.get("id") for row in results]
    if ids != receipt["hypothesis_ids"]:
        raise SystemExit("refusing result: recorded hypothesis IDs differ from registration")
    return {"schema": "nidavellir/research-probe-results/v2", "registration": receipt,
            "recorded_hypothesis_ids": ids,
            "hypotheses": [{**row, "definition_digest": receipt["definition_digests"][row["id"]]}
                           for row in results]}
