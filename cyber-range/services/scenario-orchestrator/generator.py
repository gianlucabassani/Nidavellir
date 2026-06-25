"""
Zero-to-prompt scenario generator (ROADMAP Phase 3 / Track D).

Turns an operator's natural-language brief into a candidate v3 topology spec by
prompting the **operator's own connected model** (the dashboard model bubble);
the platform never supplies the AI — it builds the prompt, calls the operator's
model through the existing ``model_chat`` plumbing, and parses a JSON spec out of
the reply. Validation + the topology preview + the never-auto-deploy review gate
live in the API on top of this module (reusing ``ScenarioSpec`` and the same
``/scenarios/preview`` path), so this file is pure prompt-building + extraction
and has no network or DB dependency of its own (the model call is injected).

Scope boundary ([[cyberguard-ai-scope-boundary]]): the model + key are the
operator's; generation is operator-only; nothing here deploys or persists.
"""
from __future__ import annotations

import json

# A concise, accurate description of the v3 schema. The embedded real example
# below is the strongest signal; this guide names the fields the model may use
# so it does not invent unsupported keys (extras are ignored by the validator,
# but naming the real ones keeps generations valid + compilable).
_SCHEMA_GUIDE = """\
A Nidavellir v3 scenario is a provider-agnostic topology. Top-level fields:
- schema: must be the string "nidavellir/v3"
- name, title: short human names (title defaults to name)
- difficulty: one of "easy", "medium", "hard"
- description: 1-3 sentences on the arena
- requires.provider_class: "container" (Docker, the default + only locally
  runnable class), "vm" (OpenStack/AWS), or "any"
- network.segments: a list of {name, description} isolated network segments
- nodes: the machines. Each node has:
    - name: unique slug
    - role: "attacker" (the offensive foothold), "victim" (a target), or
      "host" (a neutral box)
    - image: a LOGICAL image name resolved per-provider. Prefer the known
      logical names: "kali" (attacker tooling), "dvwa", "juice-shop", "ubuntu",
      "nginx". A concrete registry image (e.g. "vulhub/solr:8.11.0") is also
      allowed for victims.
    - segments: list of segment names this node attaches to
    - ports: list of container ports to expose (victims), e.g. [80, 8080]
    - entrypoint: true on the attacker node the operator/agent attaches to
    - command: optional container command; tool containers use "sleep infinity"
    - environment: optional {KEY: value} env vars for the container
- agents: list of {stance, node} — stance is "attacker" | "defender" | "mitm";
  bind the attacker stance to the entrypoint node
- objectives: list of {description}
- vulnerabilities: OPTIONAL ground-truth manifest (operator-only, never shown to
  a tester). Each: {id, title, cwe (e.g. "CWE-89"), node, severity (low|medium|
  high|critical)}. Include it only when you can name real, specific weaknesses
  of the chosen target; omit it otherwise rather than inventing CWEs.

Rules: every node's segments must exist in network.segments; include exactly one
attacker entrypoint node bound to the attacker stance unless the brief says
otherwise; for a locally-runnable arena use requires.provider_class: container.
"""

# A real built-in pack (container_web_pentest) as the worked example.
_EXAMPLE = """\
{
  "schema": "nidavellir/v3",
  "name": "Web Pentest Lab (Containers)",
  "title": "Web Pentest Lab (Containers)",
  "difficulty": "easy",
  "description": "A DVWA victim and a Kali foothold on an isolated bridge network.",
  "requires": {"provider_class": "container"},
  "network": {"segments": [{"name": "lab", "description": "flat isolated bridge"}]},
  "nodes": [
    {"name": "victim", "role": "victim", "image": "dvwa", "segments": ["lab"], "ports": [80]},
    {"name": "attacker", "role": "attacker", "image": "kali", "segments": ["lab"],
     "entrypoint": true, "command": "sleep infinity"}
  ],
  "agents": [{"stance": "attacker", "node": "attacker"}],
  "objectives": [{"description": "Recon and exploit the DVWA web application"}],
  "vulnerabilities": [
    {"id": "sqli-login", "title": "SQL injection in the DVWA SQLi module",
     "cwe": "CWE-89", "node": "victim", "severity": "high"}
  ]
}"""

_SYSTEM = (
    "You are the Nidavellir scenario generator. You translate an operator's brief "
    "into a SINGLE valid Nidavellir v3 topology spec.\n\n"
    "Output ONLY the JSON object — no markdown fences, no commentary, no prose "
    "before or after. The very first character of your reply must be '{' and the "
    "last must be '}'.\n\n"
    + _SCHEMA_GUIDE
    + "\n\nWorked example (study the shape, then write a NEW spec for the brief):\n"
    + _EXAMPLE
)

# Provider classes the operator may pin via the request.
PROVIDER_CLASSES = ("container", "vm", "any")


class GeneratorError(Exception):
    """The model did not return a usable JSON spec. ``raw`` carries the model's
    reply (truncated by the caller) so the operator can see what came back."""

    def __init__(self, message: str, raw: str | None = None):
        super().__init__(message)
        self.raw = raw


def build_messages(brief: str, provider_class: str | None = None) -> tuple[str, list[dict]]:
    """Return (system_prompt, messages) for a generation request. A
    ``provider_class`` hint is appended as a hard constraint when supplied."""
    user = brief.strip()
    if provider_class:
        user += (
            f"\n\nConstraint: requires.provider_class MUST be \"{provider_class}\"."
        )
    return _SYSTEM, [{"role": "user", "content": user}]


def extract_spec_json(text: str) -> dict:
    """Pull a single JSON object out of a model reply. Tolerates ```json fences
    and leading/trailing prose by taking the outermost ``{ … }`` span. Raises
    GeneratorError (carrying the raw text) when no JSON object can be parsed."""
    if not text or not text.strip():
        raise GeneratorError("the model returned an empty reply", raw=text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GeneratorError(
            "the model reply did not contain a JSON object", raw=text
        )
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except ValueError as e:
        raise GeneratorError(f"the model reply was not valid JSON: {e}", raw=text) from e
    if not isinstance(parsed, dict):
        raise GeneratorError("the generated spec was not a JSON object", raw=text)
    return parsed


def generate_scenario_spec(complete_fn, brief: str, provider_class: str | None = None) -> dict:
    """Generate a raw (unvalidated) v3 spec dict from a brief.

    ``complete_fn(system, messages) -> str`` performs the single model
    completion — injected so this stays network-free and unit-testable; the API
    passes a closure over the operator's decrypted ``model_chat.complete_chat``.
    Returns the parsed spec dict; the caller validates it via ``ScenarioSpec``
    and renders the topology preview (the review gate). Raises GeneratorError if
    the model produced no usable JSON."""
    if provider_class and provider_class not in PROVIDER_CLASSES:
        raise GeneratorError(f"unknown provider_class {provider_class!r}")
    system, messages = build_messages(brief, provider_class)
    reply = complete_fn(system, messages)
    return extract_spec_json(reply)
