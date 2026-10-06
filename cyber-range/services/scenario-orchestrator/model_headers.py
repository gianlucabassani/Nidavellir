"""Operator-approved static headers for BYO model connections (MODEL-R1).

Some OpenAI-compatible gateways reject the platform's default request shape:
opencode-go answers 403 without ``User-Agent: opencode*`` and 400 without
``x-opencode-session``. A model connection may therefore carry a small set of
static extra headers that are merged into every provider call (verify probe and
durable ``model-mcp/v1`` trial requests).

Security rules (enforced here, shared by the API, verify and driver paths):

- ``Authorization`` (and the other DENY entries below) can never be supplied
  as an extra header — the driver's own ``Authorization: Bearer <key>``
  (or Anthropic ``x-api-key``) credential always wins. Attempts are rejected
  with 422 at the API boundary.
- Header *values* are secret-adjacent: they are Fernet-encrypted at rest and
  never returned over the API. Only sorted ``header_names`` and a
  ``headers_digest`` (pinned into agent builds for trial-match) leave the
  database.
"""
from __future__ import annotations

import hashlib
import json
import re

# Lowercase names that may never appear in extra_headers. ``authorization``
# and ``x-api-key`` are rejected so driver-managed credentials cannot be
# overridden; the rest are hop-by-hop / framing headers that must stay under
# the HTTP client's control.
DENY = frozenset({
    "authorization",
    "x-api-key",
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "proxy-authorization",
})

MAX_HEADERS = 16
MAX_NAME_LENGTH = 64
MAX_VALUE_LENGTH = 1024
_NAME_RE = re.compile(r"[A-Za-z0-9-]{1,64}\Z")


def normalize_extra_headers(headers: dict | None) -> dict:
    """Validate an operator-supplied header map; return it as supplied.

    Raises ``ValueError`` naming the problem when the map exceeds 16
    headers, a name is not ``[A-Za-z0-9-]{1,64}``, a name is denied or
    case-insensitively duplicated, or a value is not a short single-line
    string. ``None`` maps to ``{}`` (callers map "absent" to keep-stored
    before reaching here).
    """
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise ValueError("extra_headers must be an object")
    if len(headers) > MAX_HEADERS:
        raise ValueError(f"at most {MAX_HEADERS} extra headers are allowed")
    seen: set[str] = set()
    for name, value in headers.items():
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(f"invalid header name: {name!r}")
        lowered = name.lower()
        if lowered in DENY:
            raise ValueError(
                f"header {name!r} is reserved and cannot be supplied "
                "(driver credentials always win)"
            )
        if lowered in seen:
            raise ValueError(f"duplicate header (case-insensitive): {name!r}")
        seen.add(lowered)
        if not isinstance(value, str):
            raise ValueError(f"header {name!r} value must be a string")
        if len(value) > MAX_VALUE_LENGTH:
            raise ValueError(f"header {name!r} value exceeds 1024 characters")
        if "\r" in value or "\n" in value:
            raise ValueError(f"header {name!r} value must not contain CR or LF")
    return dict(headers)


def extra_headers_digest(headers: dict | None) -> str | None:
    """Stable sha256 hex over the canonical (sorted-keys) JSON of the map.

    Returns ``None`` when the map is empty so "no headers" pins as NULL
    rather than as the hash of ``{}``. Agent builds pin this digest; the
    trial-match names it when it drifts.
    """
    if not headers:
        return None
    canonical = json.dumps(headers, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
