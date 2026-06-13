"""
Secrets redaction for logs and surfaced errors (audit #14 / SECURITY gap #6).

OpenTofu shells out with OpenStack credentials in its environment and happily
echoes them (and other secrets) into stderr on failure — which we log and also
return in API-visible error strings. This module masks secrets in two layers:

1. **Known-value masking** — the literal values of known secret env vars
   (OpenStack password, bootstrap API key, the WebUI secret key, the outputs
   encryption key, the DB-URL password) are replaced wherever they appear.
   Resolved live so rotation and tests are picked up.
2. **Pattern masking** — `key=value` / `"key": "value"` pairs whose key looks
   sensitive (password/secret/token/api_key/credential) get their value
   masked, catching secrets whose literal value we don't know.

Use `redact()` on any free text headed for a log or an API-visible error
(e.g. OpenTofu stderr), and `redact_mapping()` on dicts of variables.
"""
import os
import re
from urllib.parse import urlsplit

MASK = "***REDACTED***"  # noqa: S105 - placeholder, not a secret

# Env vars whose VALUES are secrets and must be masked verbatim wherever they
# appear in text (e.g. echoed by a subprocess).
_SECRET_ENV_VARS = (
    "OS_PASSWORD",
    "BOOTSTRAP_API_KEY",
    "SECRET_KEY",
    "SECRETS_ENCRYPTION_KEY",
)

# Tokens that make a key name "sensitive". Deliberately excludes the bare word
# "auth" (too greedy — would mask auth URLs and "authentication failed" prose).
_SENSITIVE_TOKENS = r"(?:password|passwd|secret|token|api[_-]?key|apikey|credential)"

_SENSITIVE_KEY_RE = re.compile(_SENSITIVE_TOKENS, re.IGNORECASE)

# key = value  /  "key": "value"  /  key: value  — the value run stops at the
# usual delimiters so only the secret is masked, not the rest of the line. An
# optional closing quote after the key handles JSON-style `"password": "x"`.
_KV_RE = re.compile(
    r"""(?ix)
    ( [\w.\-]* """ + _SENSITIVE_TOKENS + r""" [\w.\-]* )   # 1: key (may contain the token)
    ( ["']? \s* [=:] \s* )                                 # 2: optional close-quote + separator
    ( "[^"]*" | '[^']*' | [^\s,;}'"]+ )                    # 3: value
    """,
)

# Below this length a "secret" value is too short to mask without risking
# clobbering unrelated text (and an empty default is not a secret at all).
_MIN_SECRET_LEN = 4


def _secret_values() -> set[str]:
    values: set[str] = set()
    for name in _SECRET_ENV_VARS:
        value = os.getenv(name)
        if value and len(value) >= _MIN_SECRET_LEN:
            values.add(value)
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            password = urlsplit(db_url).password
        except ValueError:
            password = None
        if password and len(password) >= _MIN_SECRET_LEN:
            values.add(password)
    return values


def redact(text):
    """Mask known secret values and sensitive key=value pairs in free text.

    Non-strings are stringified; None passes through unchanged.
    """
    if text is None:
        return text
    if not isinstance(text, str):
        text = str(text)
    for secret in _secret_values():
        if secret in text:
            text = text.replace(secret, MASK)
    text = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    return text


def redact_mapping(mapping):
    """Return a shallow copy of a dict with sensitive-looking keys' values masked.

    Non-dicts pass through unchanged. Used for safely logging variable dicts
    (scenario vars, user_vars) that may carry caller-supplied secrets.
    """
    if not isinstance(mapping, dict):
        return mapping
    return {
        key: (MASK if _SENSITIVE_KEY_RE.search(str(key)) else value)
        for key, value in mapping.items()
    }
