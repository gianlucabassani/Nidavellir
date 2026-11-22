#!/usr/bin/env python3
"""Fail if the public tree would carry local or private material.

Checks every tracked file (or the paths given on the command line, as pre-commit
does) for:

* absolute home-directory paths that leak a contributor's machine layout
  (``/home/<user>/``, ``/Users/<name>/``, ``C:\\Users\\<name>\\``);
* files that must never be published (``.env``, private keys, Terraform state,
  operator notes, verification evidence, runtime state);
* binaries larger than ``MAX_BYTES``.

Secrets themselves are gitleaks' job (see ``.gitleaks.toml``); this script covers
what a secret scanner does not. A line containing ``public-tree: allow`` is exempt
from the path rule, for the rare case where an absolute path is the point.
"""

from __future__ import annotations

import fnmatch
import re
# subprocess runs one fixed git argv, never a shell.
import subprocess  # nosec B404
import sys
from pathlib import Path

MAX_BYTES = 1024 * 1024
ALLOW_MARKER = "public-tree: allow"

# Account names that are part of a public image or a documented convention,
# not anyone's workstation.
GENERIC_USERS = (
    "ubuntu|kali|debian|ec2-user|vagrant|runner|user|app|appuser|node|nonroot|"
    "nobody|postgres|redis|www-data|jovyan|USER|USERNAME|you|me|example"
)
HOME_PATH = re.compile(
    r"(?<![\w.$-])("
    rf"/home/(?!(?:{GENERIC_USERS})/)[A-Za-z0-9._-]+/"
    r"|/Users/(?!(?:Shared|USER|USERNAME|you|example)/)[A-Za-z0-9._-]+/"
    r"|[A-Za-z]:\\+Users\\+(?!(?:Public|USER|USERNAME|you|example)\\)[A-Za-z0-9._-]+\\"
    r")"
)

# Glob patterns matched against the repository-relative POSIX path.
FORBIDDEN = (
    ".env",
    "*/.env",
    ".env.*",
    "*/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "*/id_rsa*",
    "id_ed25519*",
    "*/id_ed25519*",
    "*.tfstate",
    "*.tfstate.*",
    "*.tfvars",
    "ISSUES.md",
    "docs/JOURNAL.md",
    "docs/verification/*",
    "docs/operator-notes/*",
    "docs/reviews/*",
    "docs/research/*",
    "data/*",
    "keys/*",
    "runs/*",
    "traces/*",
    "deployments/*",
    "cyber-range/data/*",
)
FORBIDDEN_EXCEPTIONS = (".env.example", "*/.env.example", "*.env.example")


def tracked_files() -> list[str]:
    out = subprocess.run(  # nosec B603 B607
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    return [p for p in out.decode().split("\0") if p]


def is_forbidden(path: str) -> bool:
    if any(fnmatch.fnmatch(path, pat) for pat in FORBIDDEN_EXCEPTIONS):
        return False
    return any(fnmatch.fnmatch(path, pat) for pat in FORBIDDEN)


def check(paths: list[str]) -> list[str]:
    problems: list[str] = []
    for rel in paths:
        path = Path(rel)
        if not path.is_file():
            continue  # deleted in the working tree, or a submodule
        if is_forbidden(rel):
            problems.append(f"{rel}: must not be published (see FORBIDDEN in {__file__})")
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            if len(data) > MAX_BYTES:
                problems.append(
                    f"{rel}: binary is {len(data) // 1024} KiB (limit {MAX_BYTES // 1024} KiB)"
                )
            continue
        for lineno, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            if ALLOW_MARKER in line:
                continue
            match = HOME_PATH.search(line)
            if match:
                problems.append(f"{rel}:{lineno}: absolute local path {match.group(1)!r}")
    return problems


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--self-test":
        return self_test()
    problems = check(argv or tracked_files())
    for problem in problems:
        print(problem)
    if problems:
        print(f"\npublic-tree check: {len(problems)} problem(s). Use relative or "
              "placeholder paths, and keep local material out of git.")
        return 1
    return 0


def self_test() -> int:
    leaks = [
        "/home/alice/Projects/x", "see /Users/bob/code", r"C:\Users\carol\repo",
        r"C:\\Users\\dave\\repo",
    ]
    clean = [
        "/home/ubuntu/.bashrc", "/home/kali/.bashrc", "/home/runner/work",
        "/Users/Shared/x", "$HOME/x", "~/x", "/home/$USER/x", "https://x.io/home/a/b",
    ]
    bad = [s for s in leaks if not HOME_PATH.search(s)]
    bad += [s for s in clean if HOME_PATH.search(s)]
    forbidden = [".env", "keys/k", "docs/verification/x.md", "a/id_rsa", "x.pem"]
    allowed = [".env.example", "scripts/ui.env.example", "docs/API.md"]
    bad += [p for p in forbidden if not is_forbidden(p)]
    bad += [p for p in allowed if is_forbidden(p)]
    for item in bad:
        print(f"self-test: misclassified {item!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
