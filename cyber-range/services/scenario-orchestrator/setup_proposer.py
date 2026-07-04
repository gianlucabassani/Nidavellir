"""
Operator-model-driven SUT setup proposals (Field-C).

In HITL setup the proposal queue is empty unless a configurator-stance BYO agent
calls `propose_setup_step` — and the operator's connected dashboard model is
advise-only, so nothing is proposed for the operator to approve. This module lets
the operator's OWN connected model draft setup steps from the SUT brief, which the
API records as normal `setup_proposal` events; the operator still approves/rejects
each one (the gate is unchanged). Scope boundary holds: the model + key are the
operator's, the drafts are advisory, and nothing runs without operator approval.

Pure prompt-building + parsing (the model call is injected) — network-free and
unit-testable, mirroring `generator.py`.
"""
from __future__ import annotations

import json

_SYSTEM = (
    "You are a setup assistant for a security arena. Before an engagement, an "
    "operator must bring a software-under-test (SUT) service UP on the victim "
    "node(s). The victim is a fresh Linux box (e.g. Ubuntu); when the brief gives a "
    "node's `sut_source` path, the project's source is ALREADY CLONED there.\n\n"
    "Propose concrete, ordered, idempotent SHELL commands that BUILD AND RUN THAT "
    "PROJECT following its own documented build/run steps (its README / Dockerfile "
    "/ package manifest at the sut_source path). Internet is available during "
    "setup, so installing the project's real dependencies is expected.\n\n"
    "When the brief carries a `repo_introspection` block, it is GROUND TRUTH read "
    "from the actual repository — trust it over any assumption. Use its detected "
    "`language`/`base_runtime` to pick the right toolchain (do NOT guess "
    "npm/python3/go), its `build_system` to decide how to build (an existing "
    "Dockerfile/compose/devcontainer is the project's own build — prefer it), its "
    "`declared_ports` for the service port (a port tagged `guessed-language-default` "
    "is a fallback, so confirm it against the README before relying on it), and its "
    "`run_hints`/`readme_excerpt` for the real start command.\n\n"
    "Output ONLY a JSON object of this exact shape — no prose, no fences:\n"
    '{"steps": [{"node": "<victim node name>", "command": "<shell command>", '
    '"rationale": "<one short line why>"}]}\n\n'
    "HARD RULES:\n"
    "- Operate on the cloned source at its sut_source path (cd there first).\n"
    "- Use the project's OWN language/runtime (apt/pip/npm/go/etc. as it needs). "
    "Do NOT install Docker and do NOT use docker-in-docker (the victim is itself a "
    "container/VM).\n"
    "- Use ONLY real, existing packages and commands — NEVER invent an image name, "
    "package, or tag. If you don't know the run command, inspect files first "
    "(e.g. `cat <path>/README.md`).\n"
    "- One shell command per step; non-interactive flags (e.g. apt-get -y); keep "
    "within the step budget; the final step should start the service (it may need "
    "`&`/nohup to background it). No destructive or network-escape commands."
)


class ProposerError(Exception):
    """The model returned no usable JSON list of steps. ``raw`` carries the reply."""

    def __init__(self, message: str, raw: str | None = None):
        super().__init__(message)
        self.raw = raw


def build_messages(brief: dict) -> tuple[str, list[dict]]:
    return _SYSTEM, [{"role": "user", "content": "Setup brief:\n" + json.dumps(brief, indent=2)}]


def extract_steps(reply: str) -> list[dict]:
    """Pull the ``steps`` list out of a model reply (tolerates fences/prose by
    taking the outermost ``{ … }``). Raises ProposerError when unparseable."""
    if not reply or not reply.strip():
        raise ProposerError("the model returned an empty reply", raw=reply)
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end <= start:
        raise ProposerError("the model reply did not contain a JSON object", raw=reply)
    try:
        obj = json.loads(reply[start : end + 1])
    except ValueError as e:
        raise ProposerError(f"the model reply was not valid JSON: {e}", raw=reply) from e
    steps = obj.get("steps") if isinstance(obj, dict) else None
    if not isinstance(steps, list):
        raise ProposerError("the reply had no 'steps' list", raw=reply)
    return steps


def generate_proposals(complete_fn, brief: dict, valid_nodes, max_steps: int) -> list[dict]:
    """Draft setup proposals from the brief. ``complete_fn(system, messages) -> str``
    is injected (the API passes the operator's decrypted model). Returns a list of
    ``{node, command, rationale}`` filtered to the victim scope and capped at
    ``max_steps`` (the remaining step budget). Raises ProposerError on no usable JSON."""
    valid = set(valid_nodes)
    system, messages = build_messages(brief)
    steps = extract_steps(complete_fn(system, messages))
    out: list[dict] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        node = str(s.get("node") or "").strip()
        cmd = str(s.get("command") or "").strip()
        if not cmd or node not in valid:
            continue  # silently drop out-of-scope / empty steps (the gate still applies)
        out.append({
            "node": node,
            "command": cmd[:1024],
            "rationale": str(s.get("rationale") or "")[:1024],
        })
        if len(out) >= max_steps:
            break
    return out
