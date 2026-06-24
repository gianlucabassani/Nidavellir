"""
Best-effort verification that a bring-your-own model credential actually works.

A lightweight **auth check** — list the provider's models (`GET .../models`) with
the supplied key. It validates the credential without spending any inference
tokens, and is deliberately *not* an agent run (scope boundary: Nidavellir never
operates the model, it only confirms the connection).

This is best-effort by design: the orchestrator may have no egress to the
provider (locked deployment), so a network failure is reported as **unverified**
("couldn't reach the provider"), distinct from an **invalid** key (HTTP 401/403).
Callers must never *block* storing a key on the result.

Base URLs mirror the reference harness presets (examples/agent-harness/backends.py)
so the console and the harness agree on where each provider lives.
"""
import logging

import requests

logger = logging.getLogger("API")

_VERIFY_TIMEOUT = 6  # seconds — fail fast; this is a liveness ping, not a job

# provider -> base_url for OpenAI-compatible providers. None => host not known to
# the orchestrator (generic local/self-hosted). Shared with model_chat so verify
# and chat agree on where each provider lives. Mirrors the harness presets.
OPENAI_COMPAT_BASE = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "ollama": "http://localhost:11434/v1",
    "local": None,
}
ANTHROPIC_BASE = "https://api.anthropic.com/v1"


def _result(verified, detail, *, checked=True):
    return {"verified": bool(verified), "detail": detail, "checked": checked}


def _classify_status(code: int):
    if code == 200:
        return _result(True, "key accepted by the provider")
    if code in (401, 403):
        return _result(False, f"provider rejected the key (HTTP {code})")
    return _result(False, f"unexpected provider response (HTTP {code})", checked=False)


def verify_credential(provider: str, model: str, api_key: str) -> dict:
    """Confirm a credential by listing the provider's models. Returns
    {verified: bool, detail: str, checked: bool}. ``checked=False`` means we
    could not reach a verdict (network blocked / host unknown) — treat as
    "unverified", not "invalid"."""
    provider = (provider or "").lower()
    try:
        if provider == "anthropic":
            return _classify_status(
                requests.get(
                    f"{ANTHROPIC_BASE}/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    timeout=_VERIFY_TIMEOUT,
                ).status_code
            )
        if provider in OPENAI_COMPAT_BASE:
            base = OPENAI_COMPAT_BASE[provider]
            if not base:  # generic local: base url isn't known server-side
                return _result(
                    False, "local/self-hosted endpoint — not checked here", checked=False
                )
            return _classify_status(
                requests.get(
                    f"{base.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=_VERIFY_TIMEOUT,
                ).status_code
            )
        return _result(False, f"unknown provider '{provider}'", checked=False)
    except requests.RequestException as e:
        # Network/timeout — likely no egress from the orchestrator. NOT an
        # invalid key. Don't leak the key if it ever appeared in the message.
        logger.info("model verify could not reach %s: %s", provider, type(e).__name__)
        return _result(False, "couldn't reach the provider (no egress?)", checked=False)
