"""Bounded comparison of stored transactions; never sends an arena request."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import urllib.parse

PREVIEW_CHARS = 8192
DIFF_CHARS = 16384
# Everything else is inherited server-side during replay, not exported to the editor.
EDITABLE_HEADERS = {"accept", "content-type", "x-request-id"}


RESPONSE_HEADERS = {"content-type", "content-length", "location", "www-authenticate",
                    "cache-control", "vary", "etag", "content-security-policy",
                    "strict-transport-security", "x-content-type-options", "x-frame-options",
                    "referrer-policy", "access-control-allow-origin", "access-control-allow-credentials",
                    "access-control-allow-headers", "access-control-allow-methods", "set-cookie"}


def _response_headers(headers: dict) -> dict:
    selected = {}
    for name, value in headers.items():
        if name.lower() not in RESPONSE_HEADERS or not isinstance(value, str):
            continue
        if name.lower() == "set-cookie":
            pieces = value.split(";")
            cookie_name, separator, _ = pieces[0].partition("=")
            cookie_name = cookie_name.strip()
            cookie_name = cookie_name if separator and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cookie_name) else "cookie"
            retained = [cookie_name + "=[withheld]"]
            for piece in pieces[1:]:
                key, _, flag = piece.strip().partition("=")
                if key.lower() in {"httponly", "secure"}:
                    retained.append(key)
                elif key.lower() == "samesite" and flag.lower() in {"lax", "strict", "none"}:
                    retained.append(key + "=" + flag)
            value = "; ".join(retained)
        if name.lower() == "location":
            try:
                parts = urllib.parse.urlsplit(value)
                query = urllib.parse.urlencode([(key, "[withheld]") for key, _ in
                                                 urllib.parse.parse_qsl(parts.query, keep_blank_values=True)])
                value = urllib.parse.urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1],
                                                 parts.path, query, "[withheld]" if parts.fragment else ""))
            except ValueError:
                value = "[unparseable redirect withheld]"
        selected[name] = value
    return selected


def view(manifest: dict, envelope: dict) -> dict:
    request = envelope.get("request") or {}
    response = envelope.get("response") or {}
    headers = request.get("headers") or {}
    body = response.get("body")
    preview = body[:PREVIEW_CHARS] if isinstance(body, str) else None
    return {
        "digest": manifest["digest"], "actor": manifest.get("actor"),
        "created_at": manifest.get("created_at"), "replay_of": manifest.get("replay_of"),
        "request": {**{key: request.get(key) for key in ("node", "method", "path", "params", "body")},
                    "headers": {k: v for k, v in headers.items() if k.lower() in EDITABLE_HEADERS},
                    "withheld_headers": sorted(k for k in headers if k.lower() not in EDITABLE_HEADERS)},
        "response": {**{key: response.get(key) for key in (
            "status", "reason", "body_bytes", "body_sha256", "truncated")}, "body": preview,
            "headers": _response_headers(response.get("headers") or {}),
            "captured_body_sha256": "sha256:" + hashlib.sha256(body.encode()).hexdigest()
            if isinstance(body, str) else None},
        "preview_clipped": isinstance(body, str) and len(body) > PREVIEW_CHARS,
    }


def compare(left: tuple[dict, dict], right: tuple[dict, dict]) -> dict:
    a, b = view(*left), view(*right)
    bodies = [item[1].get("response", {}).get("body") for item in (left, right)]
    known = all(isinstance(body, str) for body in bodies)
    unresolved = []
    if not known:
        unresolved.append("A captured response body is unavailable.")
    if any(item["response"]["truncated"] is not False for item in (a, b)):
        unresolved.append("A response capture was truncated or its completeness is unknown.")
    if any(item["preview_clipped"] for item in (a, b)):
        unresolved.append("Response previews are limited to 8192 characters per side.")
    diff = "".join(difflib.unified_diff(
        ((a['response']['body'] or '') + '\n').splitlines(keepends=True),
        ((b['response']['body'] or '') + '\n').splitlines(keepends=True),
        fromfile="A", tofile="B", n=3)) if known else ""
    if len(diff) > DIFF_CHARS:
        unresolved.append("The response diff was clipped at 16384 characters.")
    header_diff = "".join(difflib.unified_diff(
        (json.dumps(a['response']['headers'], sort_keys=True, indent=2) + '\n').splitlines(keepends=True),
        (json.dumps(b['response']['headers'], sort_keys=True, indent=2) + '\n').splitlines(keepends=True),
        fromfile="A headers", tofile="B headers"))
    if len(header_diff) > DIFF_CHARS:
        unresolved.append("The projected response-header diff was clipped.")
    return {"schema": "nidavellir/http-comparison/v1", "left": a, "right": b,
            "captured_body_equal": bodies[0] == bodies[1] if known else None,
            "body_diff": diff[:DIFF_CHARS], "response_headers_diff": header_diff[:DIFF_CHARS],
            "complete": not unresolved,
            "unresolved": unresolved,
            "interpretation": "Response differences are observations, not a vulnerability verdict. Review prerequisites and effects separately."}
