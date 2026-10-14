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
import selectors
import signal
import time
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
# Search captures a bounded inventory internally; each answer remains 64 KiB.
# Larger repositories still advertise a lower bound and require narrower scopes.
MAX_SEARCH_BYTES = 2 * 1024 * 1024
MAX_SITES = 50
MAX_HUNKS = 10
MAX_DIFF_SITES = 20
MAX_FILE_BYTES = 262144

# Permission-call vocabulary extracted from added lines (deterministic,
# no language-model judgment — the "classification" is this match set).
PERM_CALLS = re.compile(
    r"\b(has_perms_owner_aware|get_objects_for_user_owner_aware|permitted_object_ids"
    r"|has_perms?|permission_classes|Paperless\w*Permissions"
    r"|def validate_\w+|is_superuser|is_staff)\b"
)
REF_RE = re.compile(r"\A[0-9a-fA-F]{4,64}\Z")
TAG_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,63}([~^][0-9]*)?\Z")


class ResearchCodeError(ValueError):
    """A bounded, operator-actionable research-code failure (maps to 422)."""


def repo_root() -> Path:
    configured = os.getenv("RESEARCH_REPO_DIR")
    if not configured:
        raise ResearchCodeError("research repository is not provisioned (RESEARCH_REPO_DIR required)")
    root = Path(configured).resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise ResearchCodeError("research repository is not provisioned")
    return root


def _digest(data) -> str:
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()


class GitOutput(str):
    """Bounded UTF-8 output; callers must carry its truncation into results."""

    def __new__(cls, raw: bytes, truncated: bool):
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            truncated = True
        obj = super().__new__(cls, raw.decode("utf-8", "ignore"))
        obj.truncated = truncated
        return obj


def run_git(repo: Path, *args: str, ok_codes: tuple[int, ...] = (0,),
            max_bytes: int = MAX_BYTES) -> GitOutput:
    """No configured helpers/transports; retain at most max_bytes per pipe.

    Kill the process group on overflow/timeout rather than buffering or
    spilling unbounded output. Partial facts are explicitly labelled by
    the caller; identity/file reads reject partial output.
    """
    if not args or args[0] not in READONLY_VERBS:
        raise ResearchCodeError(f"refusing non-read git verb: {args[0] if args else None}")
    literal_paths = False
    for token in args:
        if token == "--":
            literal_paths = True
            continue
        # Git stops parsing options at --. Names such as remote_version.py
        # are paths, not transport commands; rejecting them loses inventory.
        if literal_paths:
            continue
        # Immutable tree-object lookups are likewise literal source names.
        # The SHA prefix prevents an option or transport from being parsed.
        if re.fullmatch(r"[0-9a-f]{40}:[^\x00\r\n]+", token):
            continue
        if any(forbidden in token for forbidden in FORBIDDEN_TOKENS) or token.startswith(
                ("--output", "--ext-diff", "--textconv", "--filters",
                 "--open-files-in-pager", "--help")):
            raise ResearchCodeError(f"refusing git argument: {token[:60]}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="",
               GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    command = ["git", "--no-pager", "--no-replace-objects", "-C", str(repo),
               "-c", "diff.external=", "-c", f"core.hooksPath={os.devnull}",
               "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
               "-c", "credential.helper="]
    command.extend(args)
    if args[0] in {"show", "diff", "log"}:
        command.insert(len(command) - len(args) + 1, "--no-ext-diff")
        command.insert(len(command) - len(args), "--no-textconv")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = False
    try:
        with subprocess.Popen(command, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, start_new_session=True) as process:  # nosec B603
            with selectors.DefaultSelector() as reader:
                for name in buffers:
                    reader.register(getattr(process, name), selectors.EVENT_READ, name)
                deadline = time.monotonic() + GIT_TIMEOUT
                try:
                    while reader.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ResearchCodeError("git failed to run: TimeoutExpired")
                        for key, _ in reader.select(min(remaining, 0.1)):
                            chunk = os.read(key.fileobj.fileno(), 8192)
                            if not chunk:
                                reader.unregister(key.fileobj)
                                continue
                            buffer = buffers[key.data]
                            room = max_bytes - len(buffer)
                            buffer.extend(chunk[:room])
                            if len(chunk) > room:
                                truncated = True
                                break
                        if truncated:
                            break
                finally:
                    if process.poll() is None and reader.get_map():
                        os.killpg(process.pid, signal.SIGKILL)
                    try:
                        process.wait(timeout=max(0.1, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired as exc:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        raise ResearchCodeError("git failed to run: TimeoutExpired") from exc
            if process.returncode not in ok_codes and not truncated:
                error = buffers["stderr"].decode("utf-8", "replace").strip()
                raise ResearchCodeError(f"git {args[0]} failed: {error[:200]}" +
                                        (" [error text shortened]" if len(error) > 200 else ""))
    except OSError as exc:
        raise ResearchCodeError(f"git failed to run: {type(exc).__name__}") from exc
    return GitOutput(bytes(buffers["stdout"]), truncated)


def _clip(text: str, limit: int, cuts: list[str], label: str) -> str:
    raw = text.encode()
    if len(raw) > limit:
        cuts.append(label)
        return raw[:limit].decode("utf-8", "ignore")
    return text


def resolve_ref(repo: Path, ref: str) -> str:
    """Validate a ref string and resolve it to a SHA (provenance)."""
    ref = (ref or "").strip()
    if not (REF_RE.fullmatch(ref) or TAG_RE.fullmatch(ref)):
        raise ResearchCodeError(f"invalid ref: {ref[:60]}")
    out = run_git(repo, "rev-parse", "--verify", ref + "^{commit}")
    if out.truncated:
        raise ResearchCodeError("ref resolution output truncated")
    return out.strip()


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
    # Bound the whole JSON envelope too, including multibyte evidence.
    while len(json.dumps({**body, "digest": "0" * 64}).encode()) > MAX_BYTES:
        lists = [value for value in data.values() if isinstance(value, list) and value]
        if lists:
            max(lists, key=lambda value: len(json.dumps(value))).pop()
        elif data.get("files"):
            data["files"].pop(next(reversed(data["files"])))
            data["counts_complete"] = False
        else:
            raise ResearchCodeError("output metadata exceeds JSON byte cap")
        body["truncation"] = {"truncated": True,
                              "note": (note + "; envelope byte cap; evidence omitted").strip("; ")}
    return {**body, "digest": _digest(body)}


def _hunk_func(header: str) -> str:
    text = header.split("@@")[-1].strip()
    if text.startswith("def ") or text.startswith("class "):
        return text
    return "(file scope)"


def fix_lookup(repo: Path, fix_ref: str, advisory_id: str | None = None) -> dict:
    """Advisory fix commit -> patch facts + deterministic one-line check."""
    sha = resolve_ref(repo, fix_ref)
    subject_out = run_git(repo, "log", "-1", "--format=%s", sha)
    subject = subject_out.strip()
    files_out = run_git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha)
    file_lines = files_out.splitlines()
    if files_out.truncated and file_lines:
        file_lines = file_lines[:-1]
    files = [line for line in file_lines
        if line.strip()]
    py_files = [f for f in files if f.endswith(".py")]
    hunks, truncated, cuts = [], files_out.truncated or subject_out.truncated, []
    counts_complete = not truncated and len(py_files) <= MAX_HUNKS
    for path in py_files[:MAX_HUNKS]:
        try:
            diff = run_git(repo, "show", "--format=", sha, "--", path)
        except ResearchCodeError:
            truncated = True
            counts_complete = False
            cuts.append("source diff unavailable")
            continue
        if diff.truncated:
            truncated = True
            counts_complete = False
            cuts.append("git diff byte cap")
        func, calls = "(file scope)", []
        for line in diff.splitlines():
            if line.startswith("@@"):
                func = _clip(_hunk_func(line), 120, cuts, "hunk context")
            elif line.startswith("+") and not line.startswith("+++"):
                for match in PERM_CALLS.findall(line[1:]):
                    calls.append({"call": match, "context": func,
                                  "line": _clip(line[1:].strip(), 160, cuts, "added-check evidence")})
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
            return _clip(text, 80, cuts, "check context")

        calls = sorted({c["call"] for _, c in flat
                        if not (c["call"].startswith("def ") and
                                c["call"].split()[1].split("(")[0] in defined)})
        where = (defined[0] if defined else None) or _short(next(
            (c["context"] for _, c in flat if c["context"] != "(file scope)"),
            first_file))
        check = f"added {', '.join(calls)} gate in {where} ({first_file})" \
            if calls else f"added {where} ({first_file})"
    else:
        check = ("no permission-call change detected in partial output; absence unverified"
                 if truncated else "no permission-call change detected in the named vocabulary")
    if cuts:
        truncated = True
    data = {"advisory_id": advisory_id, "fix_ref": sha, "subject": subject,
            "files_changed": files, "hunks": hunks, "check_line": check,
            "counts_complete": counts_complete}
    note = "" if not truncated else \
        f"hunk output capped ({len(py_files)} python files, first {MAX_HUNKS} shown)"
    return _envelope(data, {"repo": str(repo), "ref": sha}, truncated,
                     "; ".join(filter(None, [note, *sorted(set(cuts))])))


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
    input_truncated = diff.truncated
    cuts = []
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
            func = _clip(_hunk_func(line), 120, cuts, "diff context")
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
    truncated = input_truncated or capped or bool(cuts)
    data = {"from_ref": old, "to_ref": new, "paths": chosen,
            "files": files, "sites": sites, "counts_complete": not input_truncated}
    note = "" if not truncated else \
        ("git diff byte cap; per-file counts incomplete" if input_truncated else
         f"site/detail output capped at {MAX_DIFF_SITES}; per-file counts are complete")
    return _envelope(data, {"repo": str(repo), "from_ref": old, "to_ref": new},
                     truncated, note)


def _show_file(repo: Path, ref: str, path: str) -> str:
    try:
        text = run_git(repo, "show", f"{ref}:{path}", max_bytes=MAX_FILE_BYTES)
    except ResearchCodeError as exc:
        raise ResearchCodeError(f"cannot read {path} at {ref[:12]}: {exc}") from exc
    if text.truncated:
        raise ResearchCodeError(f"{path} exceeds the readable size cap")
    return text


def _local_nodes(node):
    """Walk a scope without attributing nested functions/classes to its owner."""
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from _local_nodes(child)


def _function_calls(tree: ast.AST):
    """Definitions indexed by qualified owner + method + definition line.

    A span resolves to exactly one definition, including free/nested functions;
    repeated method names cannot import another class's permission calls.
    """
    by_owner, spans = {}, []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.owners = []

        def visit_ClassDef(self, node):  # noqa: N802
            self.owners.append(node.name)
            self.generic_visit(node)
            self.owners.pop()

        def visit_FunctionDef(self, node):  # noqa: N802
            key = (".".join(self.owners), node.name, node.lineno)
            by_owner[key] = node
            spans.append((node.lineno, node.end_lineno, key))
            self.owners.append(node.name)
            self.generic_visit(node)
            self.owners.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    return by_owner, spans


def _enclosing(by_owner, spans, lineno):
    matches = [(end - start, key) for start, end, key in spans
               if start <= lineno <= end]
    return by_owner[min(matches)[1]] if matches else None


def _call_name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _permission_args(call):
    """Literal permission arguments; unknown/dynamic expressions stay unknown."""
    args = call.args[1:2] if _call_name(call) == "has_perms_owner_aware" else call.args[:1]
    if not args:
        return set()
    arg = args[0]
    values = arg.elts if isinstance(arg, (ast.List, ast.Tuple, ast.Set)) else [arg]
    if not all(isinstance(v, ast.Constant) and isinstance(v.value, str) for v in values):
        return set()
    return {v.value for v in values}


def _negative_guard_calls(test):
    # A disjunction denies if ANY branch rejects. A conjunction with another
    # condition can bypass that rejection and cannot establish this guard.
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Call):
        return [test.operand]
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return [call for value in test.values for call in _negative_guard_calls(value)]
    return []


def _guards(function):
    """Fail-closed condition checks, not discarded calls or call-name guesses.

    This proves only local syntactic guard presence, not dataflow dominance or
    framework/caller enforcement. Unknown control flow remains manual review.
    """
    guarded = []
    for node in function.body:
        if isinstance(node, (ast.Return, ast.Raise)):
            break
        if not isinstance(node, ast.If):
            continue
        # Recognize a negative test whose body denies/raises. A positive check
        # or an unrecognized denial shape is left for manual analysis.
        negative_calls = _negative_guard_calls(node.test)
        terminal = next((n for n in node.body if isinstance(n, (ast.Raise, ast.Return))), None)
        prefix = node.body[:node.body.index(terminal)] if terminal else node.body
        straightforward = all(isinstance(n, (ast.Expr, ast.Assign, ast.AnnAssign)) for n in prefix)
        denies = straightforward and (isinstance(terminal, ast.Raise) or
            (isinstance(terminal, ast.Return) and isinstance(terminal.value, ast.Call) and
             _call_name(terminal.value) in {"HttpResponseForbidden", "PermissionDenied"}))
        if denies:
            guarded.extend(negative_calls)
    return guarded


def _class_permissions(tree):
    permissions = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.owners = []

        def visit_ClassDef(self, node):  # noqa: N802
            self.owners.append(node.name)
            names = set()
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "permission_classes"
                        for t in stmt.targets):
                    names = {n.id for n in ast.walk(stmt.value) if isinstance(n, ast.Name)}
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    chosen = names
                    for deco in stmt.decorator_list:
                        if isinstance(deco, ast.Call):
                            for kw in deco.keywords:
                                if kw.arg == "permission_classes":
                                    chosen = {n.id for n in ast.walk(kw.value) if isinstance(n, ast.Name)}
                    permissions[(".".join(self.owners), stmt.name, stmt.lineno)] = chosen
            self.generic_visit(node)
            self.owners.pop()

    Visitor().visit(tree)
    return permissions


_OBJECT_PERM_MARKERS = {"PaperlessObjectPermissions", "ViewDocumentsPermissions", "TrashPermissions"}


def sibling_search(repo: Path, ref: str, pattern: str,
                   path_scope: list[str] | None = None, *, offset: int = 0) -> dict:
    """Bounded syntactic candidates. No status establishes vulnerability absence."""
    needles = {
        "unscoped-queryset": r"\.objects\.[[:alpha:]_][[:alnum:]_]*[[:space:]]*(",
        "bare-auth-view": "permission_classes",
        "bulk-permission": r"has_perms[[:space:]]*=",
        "half-composed-check": "has_perms_owner_aware(",
        "unguarded-verb": "@action",
        "field-validation": r"validate_\|get_serializer\|queryset[[:space:]]*=",
        "privilege-flags": r"is_superuser\|is_staff",
        "template-context": r"context\|SandboxedEnvironment",
        "mutation-order": r"\.delete(\|\.save(\|\.update(",
    }
    if pattern not in needles:
        raise ResearchCodeError("unknown pattern")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100000:
        raise ResearchCodeError("invalid site offset")
    sha = resolve_ref(repo, ref or "HEAD")
    scope = _check_paths(path_scope, ["src/documents/", "src/paperless_mail/", "src/paperless/"])
    raw = run_git(repo, "grep", "-n", needles[pattern], sha, "--", *scope,
                  ok_codes=(0, 1), max_bytes=MAX_SEARCH_BYTES)
    lines = raw.splitlines()
    if raw.truncated and lines:
        lines = lines[:-1]  # Never analyze an incomplete grep line.
    cuts = ["git grep byte cap; total_matches is a lower bound"] if raw.truncated else []
    candidates = []
    for entry in lines:
        parts = entry.split(":", 3)
        if len(parts) == 4 and parts[2].isdigit():
            candidates.append((parts[1], int(parts[2]), parts[3].strip()))
    # Filtering a bare-auth site needs the full class/action context. Do not
    # truncate before filtering or silently treat absent AST as no matches.
    cache, matches = {}, []
    for index, (path, lineno, evidence) in enumerate(candidates):
        # Only bare-auth needs syntax filtering before its count is known.
        # Other patterns classify exactly the requested page, avoiding a full
        # source analysis repeated for every continuation page.
        if pattern != "bare-auth-view" and not offset <= index < offset + MAX_SITES:
            continue
        if path not in cache:
            try:
                tree = ast.parse(_show_file(repo, sha, path))
                by_owner, spans = _function_calls(tree)
                cache[path] = (tree, by_owner, spans, _class_permissions(tree))
            except (ResearchCodeError, SyntaxError) as exc:
                cache[path] = str(exc)
        parsed = cache[path]
        if isinstance(parsed, str):
            status, classification = "manual-review", "unparsed-source"
            cuts.append("source unavailable or exceeds file byte cap")
        else:
            tree, by_owner, spans, permissions = parsed
            function = _enclosing(by_owner, spans, lineno)
            if pattern == "bare-auth-view":
                assignments = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                               and n.lineno == lineno]
                if not assignments:
                    continue
                names = {n.id for n in ast.walk(assignments[0].value) if isinstance(n, ast.Name)}
                if names != {"IsAuthenticated"}:
                    continue
                status, classification = "manual-review", (
                    "runtime-permission-override" if function else "bare-auth-class")
            elif pattern == "unguarded-verb":
                decorated = [f for f in by_owner.values() if any(
                    isinstance(d, ast.Call) and _call_name(d) == "action" and
                    d.lineno == lineno for d in f.decorator_list)]
                function = decorated[0] if decorated else None
                status, classification = _classify_guard(function, by_owner, permissions, None)
            elif pattern == "half-composed-check":
                calls = [n for n in _local_nodes(function) if isinstance(n, ast.Call) and
                         _call_name(n) == "has_perms_owner_aware" and n.lineno <= lineno <= n.end_lineno]                     if function else []
                expected = _permission_args(calls[0]) if calls else set()
                status, classification = _classify_guard(function, by_owner, permissions, expected)
            elif pattern == "bulk-permission":
                status, classification = _classify_accumulator(function, lineno)
            elif pattern in {"field-validation", "privilege-flags", "template-context", "mutation-order"}:
                # These fix shapes require framework, value parsing, context
                # contents or dominance analysis. Retain every syntactic site;
                # never promote textual check presence into a safety verdict.
                status, classification = "manual-review", {
                    "field-validation": "serializer-queryset-policy-unverified",
                    "privilege-flags": "privilege-value-parsing-unverified",
                    "template-context": "template-context-contents-unverified",
                    "mutation-order": "check-before-mutation-unverified",
                }[pattern]
            else:
                calls = list(_local_nodes(function)) if function else []
                aware = any(isinstance(n, ast.Call) and
                            ("owner_aware" in _call_name(n) or "permitted_" in _call_name(n))
                            for n in calls)
                status, classification = ("manual-review", "owner-check-dataflow-unverified") if aware else (
                    ("uncovered", "no-local-owner-check") if function else
                    ("manual-review", "framework-queryset-or-module-scope"))
        matches.append({"file": path, "line": lineno, "status": status,
                        "classification": classification,
                        "evidence": _clip(evidence, 160, cuts, "site evidence byte cap")})
    total = len(matches) if pattern == "bare-auth-view" else len(candidates)
    if total > offset + MAX_SITES:
        cuts.append(f"site page capped at {MAX_SITES}; follow next_offset")
    data = {"pattern_status": "heuristic local syntax; composed means matching guard presence only; "
            "class-covered and manual-review require caller/dataflow/framework analysis; "
            "uncovered/not composed are candidates, not findings",
            "total_matches": total, "total_matches_complete": not raw.truncated,
            "offset": offset, "next_offset": 100000,
            "sites": matches[offset:offset + MAX_SITES] if pattern == "bare-auth-view" else matches}
    # Envelope clipping may shorten a page further. Derive the continuation
    # from retained sites, never from the requested page size.
    result = _envelope(data, {"repo": str(repo), "ref": sha}, bool(cuts),
                       "; ".join(sorted(set(cuts))))
    next_offset = offset + len(data["sites"])
    data["next_offset"] = next_offset if next_offset < total else None
    result["digest"] = _digest({key: value for key, value in result.items() if key != "digest"})
    return result


def _classify_guard(function, by_owner, permissions, expected):
    if function is None:
        return "manual-review", "outside-recognized-function"
    used = _guards(function)
    globals_ = set().union(*(_permission_args(c) for c in used
                            if _call_name(c) in {"has_perm", "has_perms"}))
    dynamic = any(_call_name(c) in {"has_perm", "has_perms"} and not _permission_args(c)
                  for c in used)
    if expected is not None:
        if expected and expected <= globals_:
            return "composed", "matching-global-permission-guard"
        if not expected:
            return "manual-review", "object-permission-argument-unresolved"
    else:
        objects = set().union(*(_permission_args(c) for c in used
                                if _call_name(c) == "has_perms_owner_aware"))
        if objects and objects <= globals_:
            return "composed", "matching-global-and-object-guards"
    # Do not infer a namespace from the global call itself. Django object
    # helpers may add a model's app label; that model identity needs manual
    # resolution before an unqualified object permission can be compared.
    required = expected if expected is not None else objects
    if any("." not in value for value in required) and any("." in value for value in globals_):
        return "manual-review", "implicit-object-permission-namespace"
    ambiguous = any(isinstance(n, ast.If) and any(
        isinstance(c, ast.Call) and _call_name(c) in {"has_perm", "has_perms"}
        and _permission_args(c) & required and c not in used
        for c in ast.walk(n.test)) for n in _local_nodes(function))
    if ambiguous:
        return "manual-review", "ambiguous-permission-control-flow"
    key = next((key for key, value in by_owner.items() if value is function), None)
    names = permissions.get(key, set())
    if dynamic:
        return "manual-review", "dynamic-global-permission-argument"
    if names & _OBJECT_PERM_MARKERS:
        return "class-covered", "framework-permission-reference-unverified"
    if names == {"IsAuthenticated"}:
        return "not composed", "missing-matching-global-and-object-guards"
    return "manual-review", ("custom-permission-class" if names else "inherited-permission-policy")


def _classify_accumulator(function, lineno):
    if function is None:
        return "manual-review", "accumulator-outside-function"
    assignments = sorted((n for n in _local_nodes(function) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "has_perms" for t in n.targets)),
                         key=lambda n: n.lineno)
    current = next((n for n in assignments if n.lineno == lineno), None)
    if current is None:
        return "manual-review", "multiline-or-unrecognized-assignment"
    rhs = current.value
    if isinstance(rhs, ast.Constant) and rhs.value is False:
        return "deny-reset", "deny-reset"
    if isinstance(rhs, ast.BoolOp) and isinstance(rhs.op, ast.And) and any(
            isinstance(n, ast.Name) and n.id == "has_perms" for n in ast.walk(rhs)):
        return "covered", "and-composed"
    if current is assignments[0]:
        return "initializer", "initializer"
    return "uncovered", "overwrite"
