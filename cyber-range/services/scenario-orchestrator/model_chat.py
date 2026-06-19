"""
Co-pilot chat: stream a reply from the operator's connected BYO model.

The console's *co-pilot* lets an operator converse with their own connected model
(the model-bubble's provider + Fernet-stored key) with the current arena's context
injected by the caller. This module is the **streaming client only** — it speaks the
provider's HTTP streaming API with `requests` (no SDK dependency) and yields text
deltas. It is **advise-only**: plain text in, plain text out, no tools.

Scope boundary: the model + key are the operator's; CyberGuard provides the channel
and the context, never its own AI. The plaintext key is passed in by the caller
(decrypted in-process) and is never logged here.
"""
import json
import logging

import requests

from model_verify import ANTHROPIC_BASE, OPENAI_COMPAT_BASE

logger = logging.getLogger("API")

_CHAT_TIMEOUT = (10, 120)   # (connect, read) — streaming can be slow between tokens
_MAX_TOKENS = 1024


def stream_chat(provider, model, api_key, system, messages, max_tokens=_MAX_TOKENS):
    """Yield text chunks of the model's reply. Errors are yielded as a final
    ``[co-pilot] …`` line rather than raised, so a partial chat still renders."""
    provider = (provider or "").lower()
    try:
        if provider == "anthropic":
            yield from _stream_anthropic(model, api_key, system, messages, max_tokens)
        elif provider in OPENAI_COMPAT_BASE:
            base = OPENAI_COMPAT_BASE[provider]
            if not base:
                yield "[co-pilot] this provider has no server-side endpoint configured."
                return
            yield from _stream_openai(base, model, api_key, system, messages, max_tokens)
        else:
            yield f"[co-pilot] unknown provider '{provider}'."
    except requests.RequestException as e:
        logger.info("co-pilot stream to %s failed: %s", provider, type(e).__name__)
        yield "\n[co-pilot] couldn't reach the provider (no egress?)."


def _stream_anthropic(model, api_key, system, messages, max_tokens):
    with requests.post(
        f"{ANTHROPIC_BASE}/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "system": system,
              "messages": messages, "stream": True},
        stream=True, timeout=_CHAT_TIMEOUT,
    ) as r:
        if r.status_code != 200:
            yield f"[co-pilot] provider rejected the request (HTTP {r.status_code})."
            return
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


def _stream_openai(base, model, api_key, system, messages, max_tokens):
    msgs = [{"role": "system", "content": system}, *messages]
    with requests.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={"model": model, "messages": msgs, "max_tokens": max_tokens, "stream": True},
        stream=True, timeout=_CHAT_TIMEOUT,
    ) as r:
        if r.status_code != 200:
            yield f"[co-pilot] provider rejected the request (HTTP {r.status_code})."
            return
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
