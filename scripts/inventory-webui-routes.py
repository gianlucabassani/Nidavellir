"""Regenerate the first-pass WebUI route/action matrix from Flask decorators.

This is an inventory, not parity evidence. Browser actions, outcome states and
per-route tests still need manual review before a legacy route can retire.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "cyber-range/webui/app.py"
OUTPUT = ROOT / "docs/UI_ROUTE_ACTION_MATRIX.md"


def classify(path):
    if path in ("/favicon.ico", "/api/health"):
        return "Public support", "current path", "Keep"
    if path.startswith("/console") or path.startswith("/api/console"):
        return "New console", "/console", "Implemented projection/shell"
    if path == "/" or path == "/arenas":
        return "Research / home", "/console?workspace=research", "Legacy page retained"
    if path in ("/login", "/logout"):
        return "Session", path, "Keep (Forge-styled Flask page)"
    if path.startswith(("/evaluations", "/api/model-connection")):
        return "Benchmark / settings", "/console?workspace=benchmark", "Legacy action linked"
    if path.startswith(("/api/targets/", "/api/setup/")):
        return "Research / intake", "/console?workspace=research", "Legacy action linked"
    if path.startswith(("/scenarios", "/library/challenges", "/api/scenarios", "/launch", "/build-custom", "/create")):
        return "Cyber Range", "/console?workspace=range", "Legacy action linked"
    if path.startswith(("/arena/", "/api/arenas/", "/engagements", "/wizard", "/build-sut", "/reset/", "/destroy/", "/api/destroy/")):
        return "Research / arena", "/console?workspace=research", "Legacy action linked"
    return "Shared resources", "/console profile menu / legacy page", "Legacy action linked"


def route_rows():
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "route" and decorator.args):
                continue
            try:
                path = ast.literal_eval(decorator.args[0])
            except (ValueError, TypeError):
                continue
            methods = ["GET"]
            for keyword in decorator.keywords:
                if keyword.arg == "methods":
                    methods = ast.literal_eval(keyword.value)
            for method in methods:
                yield path, method, node.name


def main():
    rows = list(route_rows())
    lines = [
        "# WebUI route and action inventory",
        "",
        "Generated from `cyber-range/webui/app.py` by `scripts/inventory-webui-routes.py`.",
        "This is the first pass of phase 0. It records every Flask route and HTTP",
        "method; it does **not** prove React action/state parity. The status column",
        "states the present migration boundary, not a completed replacement.",
        "",
        f"**Current inventory:** {len(rows)} route/method operations. Re-run the script after route changes.",
        "",
        "| Current URL | Method | Handler | Workspace / destination | Auth | CSRF | Contract | Deep link | Migration status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for path, method, handler in rows:
        owner, destination, status = classify(path)
        csrf = "Required" if method not in ("GET", "HEAD", "OPTIONS") else "—"
        auth = "Public" if path in ("/favicon.ico", "/api/health", "/login") else "Operator session"
        contract = "JSON / stream proxy" if path.startswith("/api/") else "Flask page / form"
        deep_link = "Preserve current URL" if not path.startswith(("/console", "/api/console")) else "New route"
        lines.append(
            f"| `{path}` | {method} | `{handler}` | {owner} → `{destination}` | "
            f"{auth} | {csrf} | {contract} | {deep_link} | {status} |"
        )
    lines.extend([
        "",
        "## State and contract review still required",
        "",
        "For each row, inspect role/ownership checks, validation and denial states,",
        "old page/JavaScript caller, new component and exact BFF request/response.",
        "Record protected downloads, upload bounds, SSE resume and the old deep",
        "link/fragment mapping. A legacy route retires only after its mutation and",
        "read-only paths have browser tests at 1440, 1024, 390 and 320 px.",
        "",
        "Current React coverage: authenticated Research, Benchmark and Cyber Range",
        "indexes; Git, OCI and source-bundle intake; arena overview, setup, agent",
        "bindings, HTTP, isolated browser visits, foothold transfer, PoC, findings,",
        "evidence, infrastructure, score/challenges, run attribution, service",
        "forwards and the agent connect recipe; All arenas (destroy, remove and",
        "clear archive) and All evaluations; comparison creation, build/challenge/suite",
        "registration and evaluation results; scenario library, spec/Vulhub/model",
        "preview and import, launch and arena lifecycle; shared Targets, Agents,",
        "Activity (verdict/source filters), capacity, Settings and Profile views.",
        "Still legacy-only: setup command output, custom topology builder and",
        "non-Docker-local launches. These use narrow BFF projections and",
        "keep `/console` opt-in. The operation rows remain an inventory, not proof",
        "of old action/state parity. Exact old deep links, protected downloads,",
        "full live journeys and accessibility review remain open.",
        "",
    ])
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
