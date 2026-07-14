"""
Co-pilot chat: stream a reply from the operator's connected BYO model.

The console's *co-pilot* lets an operator converse with their own connected model
(the model-bubble's provider + Fernet-stored key) with the current arena's context
injected by the caller. This module is the **streaming client only** — it speaks the
provider's HTTP streaming API with `requests` (no SDK dependency) and yields text
deltas. It is **advise-only**: plain text in, plain text out, no tools.

Scope boundary: the model + key are the operator's; Nidavellir provides the channel
and the context, never its own AI. The plaintext key is passed in by the caller
(decrypted in-process) and is never logged here.
"""
import json
import logging
import time

import requests

from model_verify import ANTHROPIC_BASE, OPENAI_COMPAT_BASE, openai_base

logger = logging.getLogger("API")

_CHAT_TIMEOUT = (10, 120)   # (connect, read) — streaming can be slow between tokens
_MAX_TOKENS = 1024

# Inline error lines (provider unreachable / rejected / rate-limited) are yielded
# as text rather than raised, so a partial co-pilot chat still renders. They all
# begin with this marker; non-chat callers (e.g. the scenario generator) match on
# it to detect a failed completion and surface a context-appropriate message.
ERROR_SENTINEL = "[co-pilot]"

# Transient upstream statuses worth a retry — chiefly 429 (provider rate limit;
# free-tier keys often allow only ~15 req/min) plus 5xx blips. A retry happens
# *before* any token has streamed (we gate on the status line), so it never
# duplicates partial output.
_RETRY_STATUSES = (429, 500, 502, 503, 504)
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.5         # seconds: 1.5, 2.25, …
_MAX_BACKOFF = 8.0          # cap a single wait so we stay under the webui read timeout


def stream_chat(provider, model, api_key, system, messages, max_tokens=_MAX_TOKENS,
                json_mode=False, base_url=None):
    """Yield text chunks of the model's reply. Errors are yielded as a final
    ``[co-pilot] …`` line rather than raised, so a partial chat still renders.

    ``json_mode`` asks the provider to return a single JSON object — used by the
    scenario generator so the reply is syntactically valid JSON by construction
    rather than by prompt-only persuasion. OpenAI-compatible providers (incl.
    Gemini's OpenAI endpoint) get ``response_format={"type":"json_object"}``;
    Anthropic has no such flag, so we prefill the assistant turn with ``{`` (the
    documented JSON-forcing technique) and re-emit that brace. Best-effort: a
    provider that ignores the hint still benefits from the prompt + the caller's
    tolerant extraction."""
    provider = (provider or "").lower()
    try:
        if provider == "anthropic":
            yield from _stream_anthropic(model, api_key, system, messages, max_tokens, json_mode)
        elif provider in OPENAI_COMPAT_BASE:
            # Per-connection base_url wins over the provider preset / env override.
            base = base_url or openai_base(provider)
            if not base:
                yield ("[co-pilot] no endpoint for this provider — set "
                       "NIDAVELLIR_MODEL_BASE_URL for a self-hosted/custom OpenAI-compatible host.")
                return
            yield from _stream_openai(base, model, api_key, system, messages, max_tokens, json_mode)
        else:
            yield f"[co-pilot] unknown provider '{provider}'."
    except requests.RequestException as e:
        logger.info("co-pilot stream to %s failed: %s", provider, type(e).__name__)
        yield "\n[co-pilot] couldn't reach the provider (no egress?)."


def complete_chat(provider, model, api_key, system, messages, max_tokens=_MAX_TOKENS,
                  json_mode=False, base_url=None):
    """Collect a full (non-streamed) reply as one string — for callers that need
    the whole completion rather than incremental deltas (e.g. the scenario
    generator, which parses a JSON document out of the reply). Reuses the same
    provider/SSE/retry plumbing as ``stream_chat`` by draining its generator; an
    upstream error arrives as the trailing ``[…]`` sentinel line, which the
    caller treats as a failed completion. ``json_mode`` requests provider-native
    JSON output (see ``stream_chat``)."""
    return "".join(
        stream_chat(provider, model, api_key, system, messages,
                    max_tokens=max_tokens, json_mode=json_mode, base_url=base_url)
    )


def _retry_wait_seconds(resp, attempt):
    """How long to back off before retrying a transient upstream error. Honor the
    provider's ``Retry-After`` header when present (capped), else exponential."""
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), _MAX_BACKOFF)
        except ValueError:
            pass  # HTTP-date form — fall through to exponential
    return min(_BACKOFF_BASE ** (attempt + 1), _MAX_BACKOFF)


def _status_message(status):
    """A friendly co-pilot line for a non-200 status the stream couldn't recover
    from — 429 in particular gets an explanation instead of a bare code."""
    if status == 429:
        return ("[co-pilot] the AI provider's rate limit was hit (HTTP 429) and "
                "didn't clear after a retry. Free-tier keys allow only a few "
                "requests per minute — wait a moment and send the message again.")
    if status in (401, 403):
        return (f"[co-pilot] the provider rejected the API key (HTTP {status}) — "
                "check the connected model's key in the model bubble.")
    return f"[co-pilot] provider rejected the request (HTTP {status})."


def _streaming_post(url, headers, body):
    """POST a streaming chat request, retrying transient statuses (429/5xx) with
    backoff. Yields ``('open', response)`` exactly once when the upstream returns
    200 (the caller parses it), or ``('error', message)`` when it gives up — so
    the SSE parsing stays provider-specific while retry/backoff is shared."""
    for attempt in range(_MAX_RETRIES + 1):
        resp = requests.post(url, headers=headers, json=body, stream=True, timeout=_CHAT_TIMEOUT)
        if resp.status_code == 200:
            yield "open", resp
            return
        if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            wait = _retry_wait_seconds(resp, attempt)
            resp.close()
            logger.info(
                "co-pilot upstream %s on attempt %d/%d — retrying in %.1fs",
                resp.status_code, attempt + 1, _MAX_RETRIES + 1, wait,
            )
            time.sleep(wait)
            continue
        message = _status_message(resp.status_code)
        resp.close()
        yield "error", message
        return


def _stream_anthropic(model, api_key, system, messages, max_tokens, json_mode=False):
    # Anthropic has no response_format flag; prefill the assistant turn with "{"
    # to force a JSON object (the reply continues from there, so we re-emit the
    # brace once the stream opens).
    msgs = [*messages, {"role": "assistant", "content": "{"}] if json_mode else messages
    for kind, payload in _streaming_post(
        f"{ANTHROPIC_BASE}/messages",
        {"x-api-key": api_key, "anthropic-version": "2023-06-01",
         "content-type": "application/json"},
        {"model": model, "max_tokens": max_tokens, "system": system,
         "messages": msgs, "stream": True},
    ):
        if kind == "error":
            yield payload
            return
        if json_mode:
            yield "{"
        with payload as r:
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if evt.get("type") == "content_block_delta":
                    text = (evt.get("delta") or {}).get("text")
                    if text:
                        yield text


def _stream_openai(base, model, api_key, system, messages, max_tokens, json_mode=False):
    msgs = [{"role": "system", "content": system}, *messages]
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens, "stream": True}
    if json_mode:
        # Supported by OpenAI, DeepSeek and Gemini's OpenAI-compatible endpoint;
        # the prompt mentions JSON (required by OpenAI's json_object mode).
        body["response_format"] = {"type": "json_object"}
    for kind, payload in _streaming_post(
        f"{base.rstrip('/')}/chat/completions",
        {"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        body,
    ):
        if kind == "error":
            yield payload
            return
        with payload as r:
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    evt = json.loads(data)
                except ValueError:
                    continue
                delta = ((evt.get("choices") or [{}])[0]).get("delta") or {}
                text = delta.get("content")
                if text:
                    yield text
