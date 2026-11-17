"""
LLM Dockerfile synthesis with a verified-build loop (ROADMAP M1 / backlog M1-3;
ADR-0008 tier-3, the Repo2Run pattern — arXiv:2502.13681).

The planner's `none` strategy means the repo ships no Dockerfile / compose /
devcontainer. Rather than let the model guess a build (a one-shot LLM Dockerfile
hallucinates packages ~20% of the time), this synthesizes a Dockerfile from the
repo introspection and **actually builds it**, feeding any build error back to the
model to fix, and only ever returns a Dockerfile that **built green**. A synthesis
that never builds returns `ok=False` with the attempt history — never an
unverified Dockerfile.

Split like its siblings (`generator.py`, `setup_proposer.py`): the prompt building
+ extraction are pure and network-free; the model call (`complete_fn`) and the
build (`build_fn`) are **injected**, so the loop is fully unit-testable and the
API/provider supply the real model + docker at the edges. Scope boundary holds:
the model + key are the operator's; Nidavellir provides the verified-build harness,
never the AI ([[cyberguard-ai-scope-boundary]]).
"""
from __future__ import annotations

import json
import re

DEFAULT_MAX_ATTEMPTS = 3
_MAX_ERR_CHARS = 3000  # build-log tail fed back to the model on a retry

_SYSTEM = (
    "You are a Dockerfile author. Given a repository introspection, write ONE "
    "minimal, correct Dockerfile that builds the project and runs its service in "
    "the FOREGROUND.\n\n"
    "Output ONLY the Dockerfile — no markdown fences, no commentary. The first line "
    "must be a `FROM` instruction.\n\n"
    "HARD RULES:\n"
    "- Use a REAL, official base image matching the detected runtime/version "
    "(e.g. python:3.12-slim, node:20-alpine, golang:1.22). Never invent an image.\n"
    "- Install the project's real dependencies non-interactively from its manifest "
    "(requirements.txt / package.json / go.mod / …).\n"
    "- COPY the source, build if needed, and end with a CMD/ENTRYPOINT that runs the "
    "service in the foreground (no bare `sleep`, no backgrounding).\n"
    "- EXPOSE the service's real listening port.\n"
    "- Do NOT install Docker and do NOT use docker-in-docker.\n"
    "- Keep it minimal and deterministic; pin versions where the introspection gives them."
)


class SynthError(Exception):
    """The model returned no usable Dockerfile. ``raw`` carries the reply."""

    def __init__(self, message: str, raw: str | None = None):
        super().__init__(message)
        self.raw = raw


def build_messages(introspection: dict, history: list[dict] | None = None) -> tuple[str, list[dict]]:
    """(system, messages) for a synthesis request. The user turn carries the
    introspection as ground truth; on a retry, ``history`` (prior
    ``{dockerfile, error}`` attempts) is appended so the model FIXES the specific
    build failure instead of guessing afresh."""
    user = (
        "Repository introspection (ground truth — build for THIS):\n"
        + json.dumps(introspection or {}, indent=2)
    )
    for i, att in enumerate(history or [], 1):
        user += (
            f"\n\n--- Attempt {i} FAILED to build. Dockerfile was:\n"
            + (att.get("dockerfile") or "")
            + "\n\nBuild error (tail):\n"
            + (att.get("error") or "")[-_MAX_ERR_CHARS:]
        )
    if history:
        user += (
            "\n\nFix the specific error above. Output ONLY the corrected Dockerfile."
        )
    return _SYSTEM, [{"role": "user", "content": user}]


def extract_dockerfile(reply: str) -> str:
    """Pull the Dockerfile out of a model reply. Tolerates ``` fences and leading/
    trailing prose by preferring a fenced block, else taking from the first `FROM`
    line onward. Raises SynthError when no plausible Dockerfile is present."""
    if not reply or not reply.strip():
        raise SynthError("the model returned an empty reply", raw=reply)
    fenced = re.search(r"```(?:dockerfile|docker)?\s*\n(.*?)```", reply, re.DOTALL | re.IGNORECASE)
    text = fenced.group(1) if fenced else reply
    # Anchor to the first FROM (case-insensitive) so any preamble prose is dropped.
    m = re.search(r"(?im)^\s*FROM\s+\S+", text)
    if not m:
        raise SynthError("the reply contained no FROM instruction", raw=reply)
    dockerfile = text[m.start():].strip()
    return dockerfile


def synthesize_verified_dockerfile(
    complete_fn,
    build_fn,
    introspection: dict,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict:
    """Repo2Run verified loop. ``complete_fn(system, messages) -> str`` is the
    model; ``build_fn(dockerfile_text) -> (ok: bool, logs: str)`` actually builds
    the candidate. Iterate up to ``max_attempts``: synthesize → build → on failure
    feed the error back and retry. Returns::

        {ok, dockerfile, attempts: [{dockerfile, ok, error}], error}

    ``ok=True`` ONLY when a build was confirmed green (``dockerfile`` is that
    verified one). ``ok=False`` returns the attempt history and never a Dockerfile
    claimed to work. A SynthError (unparseable reply) ends the loop as a failed
    attempt rather than raising, so the caller always gets a structured result."""
    attempts: list[dict] = []
    history: list[dict] = []
    for _ in range(max(1, max_attempts)):
        system, messages = build_messages(introspection, history)
        try:
            dockerfile = extract_dockerfile(complete_fn(system, messages))
        except SynthError as e:
            attempts.append({"dockerfile": None, "ok": False, "error": f"no usable Dockerfile: {e}"})
            break  # a non-Dockerfile reply won't improve by retrying the same way
        ok, logs = build_fn(dockerfile)
        attempts.append({"dockerfile": dockerfile, "ok": bool(ok), "error": None if ok else (logs or "")[-_MAX_ERR_CHARS:]})
        if ok:
            return {"ok": True, "dockerfile": dockerfile, "attempts": attempts, "error": None}
        history.append({"dockerfile": dockerfile, "error": logs or ""})
    return {
        "ok": False,
        "dockerfile": None,
        "attempts": attempts,
        "error": f"no Dockerfile built green in {len(attempts)} attempt(s)",
    }
