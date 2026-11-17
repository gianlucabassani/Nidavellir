#!/usr/bin/env python3
"""Retain paged candidate inventories and affected/fixed patch evidence.

Read-only, offline, operator-provisioned source. This verifies inventory coverage,
not vulnerability absence or the semantic correctness of a third-party fix.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cyber-range/services/scenario-orchestrator"))
import research_code  # noqa: E402

PATTERNS = ("unscoped-queryset", "bare-auth-view", "bulk-permission",
            "half-composed-check", "unguarded-verb", "field-validation",
            "privilege-flags", "template-context", "mutation-order")
FIXES = (
    ("F1", "b010f65ae", ("field-validation", "half-composed-check")),
    ("F2", "9e9fc6213", ("unscoped-queryset",)),
    ("F3", "06b2d5102", ("privilege-flags",)),
    ("F4", "afaf39e43", ("field-validation", "template-context")),
    ("F5", "65ca78e9e", ("half-composed-check", "mutation-order")),
    ("F6", "8aab34ea7", ("half-composed-check", "unguarded-verb")),
    ("F7", "8aab34ea7", ("bulk-permission",)),
    ("F8", "c28c532be", ("mutation-order",)),
    ("F9", "81795bc93", ("bare-auth-view",)),
)


def inventory(repo: Path, ref: str, pattern: str, scope=None) -> dict:
    pages, seen, offset = [], set(), 0
    sha = research_code.resolve_ref(repo, ref)
    while True:
        page = research_code.sibling_search(repo, sha, pattern, scope, offset=offset)
        data = page["data"]
        if not data["total_matches_complete"]:
            # Paging cannot recover bytes omitted by grep. Narrow the immutable
            # inventory to disjoint files instead of treating a lower bound as all.
            if scope and len(scope) == 1 and not scope[0].endswith("/"):
                raise RuntimeError(f"single-file grep still incomplete: {scope[0]}")
            paths = research_code.run_git(repo, "ls-tree", "-r", "--name-only", sha, "--",
                *(scope or ["src/documents/", "src/paperless_mail/", "src/paperless/"]))
            if paths.truncated:
                raise RuntimeError("file inventory incomplete; narrow the source scope")
            partitions = [inventory(repo, sha, pattern, [path]) for path in paths.splitlines()]
            return {"ref": sha, "pattern": pattern, "scope": scope,
                    "retained_sites": sum(item["retained_sites"] for item in partitions),
                    "total_matches_complete": all(item["total_matches_complete"] for item in partitions),
                    "partitions": [item for item in partitions if item["retained_sites"]],
                    "partial_scope_preview": page,
                    "conclusion": "Complete per-file inventory; candidates remain unresolved."}
        for site in data["sites"]:
            key = (site["file"], site["line"])
            if key in seen:
                raise RuntimeError("duplicate paged candidate")
            seen.add(key)
        pages.append(page)
        continuation = data["next_offset"]
        if continuation is None:
            break
        if continuation <= offset:
            raise RuntimeError("inventory pagination made no progress")
        offset = continuation
    if len(seen) != data["total_matches"]:
        raise RuntimeError("retained inventory count differs from reported total")
    return {"ref": sha, "pattern": pattern, "scope": scope, "retained_sites": len(seen),
            "total_matches_complete": data["total_matches_complete"], "pages": pages,
            "conclusion": "Candidates remain unresolved; no absence inference."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("evidence already exists; choose a new output path")
    repo = args.repo.resolve()
    # The historical five-pattern inventory used these two directories.
    historical_scope = ["src/documents/", "src/paperless_mail/"]
    current = []
    for pattern in PATTERNS:
        current.append(inventory(repo, "v3.3.0", pattern,
                                 historical_scope if pattern in PATTERNS[:5] else None))
        print(f"retained current {pattern}: {current[-1]['retained_sites']}", file=sys.stderr)
    fixes = []
    for fid, ref, patterns in FIXES:
        patch = research_code.fix_lookup(repo, ref)
        changed = research_code.run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
                                         research_code.resolve_ref(repo, ref))
        if changed.truncated:
            raise RuntimeError("fix path inventory incomplete")
        # Fix calibration covers all changed source files; current residuals
        # above still cover the full documented directories. Do not repeatedly
        # scan unrelated test/migration modules at every historical revision.
        paths = [path for path in changed.splitlines() if path.startswith("src/")]
        scopes = [paths[i:i + 8] for i in range(0, len(paths), 8)]
        if not scopes:
            raise RuntimeError(f"fix has no retained source paths: {fid}")
        fixes.append({"id": fid, "patch": patch, "source_paths": paths,
                      "affected": [inventory(repo, ref + "^", pattern, scope)
                                   for pattern in patterns for scope in scopes],
                      "fixed": [inventory(repo, ref, pattern, scope)
                                for pattern in patterns for scope in scopes],
                      "semantic_review": "Unresolved: syntax inventories and patch facts are not proof of enforcement."})
        print(f"retained affected/fixed shape {fid}", file=sys.stderr)
    evidence = {"schema": "nidavellir/research-inventory/v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "current": current, "fix_shapes": fixes,
                "absence_established": False}
    with args.output.open("x") as output:
        output.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "counts": {
        item["pattern"]: item["retained_sites"] for item in current},
        "fix_shapes": len(fixes), "absence_established": False}))


if __name__ == "__main__":
    main()
