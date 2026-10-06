"""Read-only code-intel for the research lane (variant-hunt collect+derive).

Answer-shaped tools over a server-side pinned git checkout: fix lookup,
permission-layer diff, and sibling/call-site search with composition
status. Never a raw diff blob; every output is bounded, digest-bound,
and reports truncation instead of truncating silently.

Read-only contract: the repository is operator-provisioned out of band
at RESEARCH_REPO_DIR. This module never clones, fetches, pulls or
pushes (no egress); git verbs are allowlisted to read-only ones with a
timeout and a byte cap. Nothing is written to the repository.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

READONLY_VERBS = frozenset({
    "log", "show", "grep", "diff", "diff-tree", "blame", "rev-parse",
    "describe", "ls-tree", "cat-file", "merge-base",
})
FORBIDDEN_TOKENS = ("upload-pack", "receive-pack", "--exec", "clone",
                    "fetch", "pull", "push", "remote", "submodule")
GIT_TIMEOUT = 30
MAX_BYTES = 65536
MAX_SITES = 50
MAX_HUNKS = 10
MAX_DIFF_SITES = 20
MAX_FILE_BYTES = 262144

# Permission-call vocabulary extracted from added lines (deterministic,
# no language-model judgment — the "classification" is this match set).
PERM_CALLS = re.compile(
    r"\b(has_perms_owner_aware|get_objects_for_user_owner_aware|permitted_object_ids"
    r"|has_perm\(|permission_classes|Paperless\w*Permissions"
    r"|def validate_\w+|is_superuser|is_staff)\b"
)
REF_RE = re.compile(r"\A[0-9a-fA-F]{4,64}\Z")
TAG_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,63}([~^][0-9]*)?\Z")


class ResearchCodeError(ValueError):
    """A bounded, operator-actionable research-code failure (maps to 422)."""


def repo_root() -> Path:
    root = Path(os.getenv("RESEARCH_REPO_DIR", "") or "")
    if not root.is_dir() or not (root / ".git").exists():
        raise ResearchCodeError(
            "research repository is not provisioned "
            "(operator clones the pinned repo to RESEARCH_REPO_DIR out of band)")
    return root


def _digest(data) -> str:
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()


def run_git(repo: Path, *args: str, ok_codes: tuple[int, ...] = (0,)) -> str:
    """Run one allowlisted read-only git command, byte-capped."""
    if not args or args[0] not in READONLY_VERBS:
        raise ResearchCodeError(f"refusing non-read git verb: {args[0] if args else None}")
    for token in args:
        if any(forbidden in token for forbidden in FORBIDDEN_TOKENS):
            raise ResearchCodeError(f"refusing git argument: {token[:60]}")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResearchCodeError(f"git failed to run: {type(exc).__name__}") from exc
    if result.returncode not in ok_codes:
        raise ResearchCodeError(
            f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def resolve_ref(repo: Path, ref: str) -> str:
    """Validate a ref string and resolve it to a SHA (provenance)."""
    ref = (ref or "").strip()
    if not (REF_RE.fullmatch(ref) or TAG_RE.fullmatch(ref)):
        raise ResearchCodeError(f"invalid ref: {ref[:60]}")
    return run_git(repo, "rev-parse", "--verify", ref).strip()


def _check_paths(paths: list[str] | None, default: list[str]) -> list[str]:
    chosen = list(default if not paths else paths)
    if len(chosen) > 8:
        raise ResearchCodeError("at most 8 paths per call")
    for path in chosen:
        if not path or path.startswith(("/", "~")) or ".." in path.split("/"):
            raise ResearchCodeError(f"invalid path scope: {path[:60]}")
    return chosen


def _envelope(data: dict, provenance: dict, truncated: bool, note: str = "") -> dict:
    body = {"data": data, "truncation": {"truncated": truncated, "note": note},
            "provenance": provenance}
    return {**body, "digest": _digest(body)}


def _hunk_func(header: str) -> str:
    text = header.split("@@")[-1].strip()
    if text.startswith("def ") or text.startswith("class "):
        return text[:120]
    return "(file scope)"


def fix_lookup(repo: Path, fix_ref: str, advisory_id: str | None = None) -> dict:
    """Advisory fix commit -> patch facts + deterministic one-line check."""
    sha = resolve_ref(repo, fix_ref)
    subject = run_git(repo, "log", "-1", "--format=%s", sha).strip()
    files = [line for line in run_git(
        repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
        if line.strip()]
    py_files = [f for f in files if f.endswith(".py")]
    hunks, truncated = [], False
    for path in py_files[:MAX_HUNKS]:
        try:
            diff = run_git(repo, "show", "--format=", sha, "--", path)
        except ResearchCodeError:
            truncated = True
            continue
        if len(diff) > MAX_BYTES:
            diff = diff[:MAX_BYTES]
            truncated = True
        func, calls = "(file scope)", []
        for line in diff.splitlines():
            if line.startswith("@@"):
                func = _hunk_func(line)
            elif line.startswith("+") and not line.startswith("+++"):
                for match in PERM_CALLS.findall(line[1:]):
                    calls.append({"call": match, "context": func,
                                  "line": line[1:].strip()[:160]})
        hunks.append({"file": path, "added_perm_calls": calls})
    if len(py_files) > MAX_HUNKS:
        truncated = True
    flat = [(h["file"], c) for h in hunks for c in h["added_perm_calls"]]
    if flat:
        first_file = flat[0][0]
        defined = sorted({match.split()[1].split("(")[0]
                          for _, c in flat
                          for match in [c["call"]] if match.startswith("def ")})

        def _short(context: str) -> str:
            text = context.strip()
            match = re.match(r"class\s+(\w+)", text)
            if match:
                return match.group(1)
            return text[:80]

        calls = sorted({c["call"] for _, c in flat
                        if not (c["call"].startswith("def ") and
                                c["call"].split()[1].split("(")[0] in defined)})
        where = (defined[0] if defined else None) or _short(next(
            (c["context"] for _, c in flat if c["context"] != "(file scope)"),
            first_file))
        check = f"added {', '.join(calls[:4])} gate in {where} ({first_file})" \
            if calls else f"added {where} ({first_file})"
    else:
        check = "no permission-call change detected (non-permission fix or docs/test-only)"
    data = {"advisory_id": advisory_id, "fix_ref": sha, "subject": subject,
            "files_changed": files, "hunks": hunks, "check_line": check}
    note = "" if not truncated else \
        f"hunk output capped ({len(py_files)} python files, first {MAX_HUNKS} shown)"
    return _envelope(data, {"repo": str(repo), "ref": sha}, truncated, note)


def layer_diff(repo: Path, from_ref: str, to_ref: str,
               paths: list[str] | None = None) -> dict:
    """Permission-call delta between two pins over a bounded path set."""
    default = ["src/documents/permissions.py", "src/documents/views.py",
               "src/documents/serialisers.py", "src/paperless_mail/views.py",
               "src/paperless/views.py"]
    chosen = _check_paths(paths, default)
    old = resolve_ref(repo, from_ref)
    new = resolve_ref(repo, to_ref)
    try:
        diff = run_git(repo, "diff", "--unified=0", old, new, "--", *chosen)
    except ResearchCodeError as exc:
        raise ResearchCodeError(f"diff failed (bad ref or path?): {exc}") from exc
    if len(diff) > MAX_BYTES:
        diff = diff[:MAX_BYTES]
    files: dict[str, dict] = {}
    current, func = None, "(file scope)"
    sites, capped = [], False
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            current = parts[1] if len(parts) > 1 else None
            if current:
                files.setdefault(current, {"added": 0, "removed": 0})
            func = "(file scope)"
        elif line.startswith("@@"):
            func = _hunk_func(line)
        elif current and (line.startswith("+") and not line.startswith("+++")):
            hits = PERM_CALLS.findall(line[1:])
            if hits:
                files[current]["added"] += len(hits)
                if len(sites) < MAX_DIFF_SITES:
                    sites.append({"file": current, "side": "added",
                                  "context": func,
                                  "calls": sorted(set(hits))})
                else:
                    capped = True
        elif current and line.startswith("-") and not line.startswith("---"):
            hits = PERM_CALLS.findall(line[1:])
            if hits:
                files[current]["removed"] += len(hits)
    truncated = capped or len(sites) >= MAX_DIFF_SITES
    data = {"from_ref": old, "to_ref": new, "paths": chosen,
            "files": files, "sites": sites}
    note = "" if not truncated else \
        f"site list capped at {MAX_DIFF_SITES}; per-file counts are complete"
    return _envelope(data, {"repo": str(repo), "from_ref": old, "to_ref": new},
                     truncated, note)


def _show_file(repo: Path, ref: str, path: str) -> str:
    try:
        text = run_git(repo, "show", f"{ref}:{path}")
    except ResearchCodeError as exc:
        raise ResearchCodeError(f"cannot read {path} at {ref[:12]}: {exc}") from exc
    if len(text) > MAX_FILE_BYTES:
        raise ResearchCodeError(f"{path} exceeds the readable size cap")
    return text


def _function_calls(tree: ast.AST) -> dict[str, set[str]]:
    """Map function name -> dotted call names used inside it."""
    found: dict[str, set[str]] = {}
    spans: dict[str, tuple[int, int]] = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []

        def visit_FunctionDef(self, node):  # noqa: N802 - ast hook
            self.stack.append(node.name)
            found.setdefault(node.name, set())
            spans[node.name] = (node.lineno, node.end_lineno or node.lineno)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):  # noqa: N802 - ast hook
            if self.stack:
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else \
                    (func.id if isinstance(func, ast.Name) else "?")
                found[self.stack[-1]].add(name)
            self.generic_visit(node)

    Visitor().visit(tree)
    return found, spans


def _enclosing(calls: dict[str, set[str]], spans: dict[str, tuple[int, int]],
               lineno: int | None) -> set[str] | None:
    """Call set of the innermost function enclosing a line, else None."""
    if lineno is None:
        return None
    best, best_span = None, None
    for name, (start, end) in spans.items():
        if start <= lineno <= end and (best_span is None or
                                       (end - start) < (best_span[1] - best_span[0])):
            best, best_span = name, (start, end)
    return calls.get(best) if best else None


def _grep(repo: Path, ref: str, pattern: str, scope: list[str]) -> list[str]:
    # Exit 1 means no match, not failure.
    out = run_git(repo, "grep", "-n", pattern, ref, "--", *scope, ok_codes=(0, 1))
    return [line for line in out.splitlines() if line.strip()]


def sibling_search(repo: Path, ref: str, pattern: str,
                   path_scope: list[str] | None = None) -> dict:
    """Named-pattern call-site search with per-site composition status."""
    sha = resolve_ref(repo, ref) if ref else resolve_ref(repo, "HEAD")
    scope = _check_paths(path_scope, ["src/documents/", "src/paperless_mail/"])
    if pattern == "unscoped-queryset":
        return _pattern_unscoped_queryset(repo, sha, scope)
    if pattern == "bare-auth-view":
        return _pattern_bare_auth_view(repo, sha, scope)
    if pattern == "bulk-permission":
        return _pattern_bulk_permission(repo, sha, scope)
    raise ResearchCodeError(
        "unknown pattern (known: unscoped-queryset, bare-auth-view, bulk-permission)")


def _evidence(repo: Path, sha: str, scope: list[str], needle: str,
              status_fn) -> dict:
    raw = _grep(repo, sha, needle, scope)
    truncated = len(raw) > MAX_SITES
    sites = []
    for entry in raw[:MAX_SITES]:
        # git grep with a rev prints rev:path:lineno:text.
        parts = entry.split(":", 3)
        if len(parts) != 4:
            continue
        _, path, lineno, text = parts
        sites.append({"line": int(lineno) if lineno.isdigit() else None,
                      "status": None, "evidence": text.strip()[:160],
                      "_file": path})
    by_file: dict[str, list[dict]] = {}
    for site in sites:
        by_file.setdefault(site.pop("_file"), []).append(site)
    out, shown = [], 0
    for path, group in sorted(by_file.items()):
        try:
            tree = ast.parse(_show_file(repo, sha, path))
            calls, spans = _function_calls(tree)
        except (ResearchCodeError, SyntaxError):
            for site in group:
                site["status"] = "unparsed"
            out.extend({**s, "file": path} for s in group)
            continue
        for site in group:
            used = _enclosing(calls, spans, site["line"])
            site["status"] = status_fn(used, site["evidence"])
            shown += 1
            out.append({**site, "file": path})
    data = {"pattern_status": "heuristic function-scope analysis; "
            "uncovered means candidate, not finding",
            "sites": [{k: v for k, v in site.items()} for site in out]}
    return _envelope(data, {"repo": str(repo), "ref": sha}, truncated,
                     "" if not truncated else
                     f"site list capped at {MAX_SITES}; refine path_scope")


def _pattern_unscoped_queryset(repo, sha, scope):
    def status(used, _evidence):
        if used is None:
            return "review"
        bare = "filter" in used or "all" in used
        aware = any("owner_aware" in name or "permitted_" in name for name in used)
        if bare and not aware:
            return "uncovered"
        if aware:
            return "covered"
        return "review"

    return _evidence(repo, sha, scope, r"\.objects\.filter(", status)


def _pattern_bare_auth_view(repo, sha, scope):
    def status(_used, _evidence):
        return "review"

    return _evidence(repo, sha, scope,
                     "permission_classes = (IsAuthenticated,)", status)


def _pattern_bulk_permission(repo, sha, scope):
    def status(used, evidence):
        rhs = evidence.split("=", 1)[-1]
        if "has_perms" not in rhs:
            return "review"  # initializer, not a composition decision
        if " and " in rhs:
            return "covered"
        return "uncovered"

    return _evidence(repo, sha, scope, r"has_perms\s*=", status)
