"""UX-25: the structured finding write-up, written by the reporting agent.

One module for the API (agent submissions and patches, operator edits), the
readiness checklist and the console, so they never disagree on what a
report-ready finding is. Markdown is a rendering of this schema, not a
second source of truth.

Schema ``nidavellir.finding-writeup.v1``:

    summary            str   one paragraph usable as a CVE description
    impact             str   two or three lines; no reproduction details
    description        str   vulnerable component, trust boundary, root cause
    remediation        str   the concrete change at the right layer
    affected_assets    [{kind, value, note?}]   host|url|endpoint|parameter|component|file
    cwes               [{id: "CWE-NNN", name}]
    reproduction       {prerequisites, auth_role, steps: [{action, expected?,
                        evidence: [digest]}], cleanup?}
    references         [{url, title?}]   https, public documentation hosts
    http_exception     {reason}   only for an issue no HTTP exchange can prove
    severity           critical|high|medium|low|info
    vendor, product, affected_versions, fixed_versions, discoverer   str
    attack_type        remote|adjacent|local|physical
    impact_type        code_execution|information_disclosure|denial_of_service|
                       privilege_escalation|other
    cvss_vector        CVSS:3.x vector

An incomplete write-up is always storable: completeness is checked by
``readiness()`` when the finding is reported onward, never at discovery.
Prose never verifies a finding.

Ownership: the reporting agent writes every section; a section an operator
saves becomes the operator's, and the agent can no longer overwrite it.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "nidavellir.finding-writeup.v1"
TEXT_SECTIONS = {"summary": 2000, "impact": 1200, "description": 8000, "remediation": 8000}
SHORT_SECTIONS = {"vendor": 200, "product": 200, "affected_versions": 200,
                  "fixed_versions": 200, "discoverer": 200}
ENUMS = {
    "severity": ("critical", "high", "medium", "low", "info"),
    "attack_type": ("remote", "adjacent", "local", "physical"),
    "impact_type": ("code_execution", "information_disclosure", "denial_of_service",
                    "privilege_escalation", "other"),
}
SECTIONS = (*TEXT_SECTIONS, "affected_assets", "cwes", "reproduction", "references",
            "http_exception", *ENUMS, *SHORT_SECTIONS, "cvss_vector")
ASSET_KINDS = ("host", "url", "endpoint", "parameter", "component", "file")
MIN_REFERENCES = 3
TRUSTED_REFERENCE_PREFIXES = ("https://cheatsheetseries.owasp.org/",
                              "https://portswigger.net/web-security",
                              "https://owasp.org/", "https://cwe.mitre.org/")

_CWE = re.compile(r"^CWE-[1-9][0-9]{0,4}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CVSS = re.compile(r"^CVSS:3\.[01]/AV:[NALP]/AC:[LH]/PR:[NLH]/UI:[NR]/S:[UC]/C:[NLH]/I:[NLH]/A:[NLH]$")
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
# Credentials belong in evidence, never in prose that is stored and shown in clear.
_SECRET_IN_PROSE = re.compile(
    r"(?i)(authorization:\s*(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\b(password|passwd|pwd|api[_-]?key|secret|token)\s*[=:]\s*[^\s`'\"<>]{6,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


class WriteupError(ValueError):
    """A write-up with the wrong shape; ``errors`` lists every problem so the
    author fixes them in one round."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _text(value: Any, name: str, limit: int, errors: list[str]) -> str | None:
    if not isinstance(value, str):
        errors.append(f"{name}: must be a string")
        return None
    value = value.replace("\r\n", "\n").strip()
    if not value:
        errors.append(f"{name}: must not be blank (send null to clear it)")
        return None
    if len(value) > limit:
        errors.append(f"{name}: at most {limit} characters")
        return None
    return value


def reference_problem(url: str) -> str | None:
    """Syntax and source suitability only. The URL is never fetched."""
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        return "not a valid URL"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "not a valid URL"
    if parts.scheme != "https":
        return "must be an https:// URL"
    host = (parts.hostname or "").lower()
    if parts.username or parts.password or parts.port not in (None, 443):
        return "must not carry credentials or a non-standard port"
    try:
        ipaddress.ip_address(host)
        return "must name a public documentation host, not an IP address"
    except ValueError:
        pass
    if not _HOSTNAME.match(host) or host.endswith((".local", ".internal", ".lan")):
        return "must name a public documentation host"
    return None


def _digests(value: Any, name: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 10 or not all(
            isinstance(v, str) and _DIGEST.match(v) for v in value):
        errors.append(f"{name}: a list of up to 10 evidence digests (sha256:…)")
        return []
    return list(dict.fromkeys(value))


def _reproduction(value: Any, errors: list[str]) -> dict | None:
    if not isinstance(value, dict):
        errors.append("reproduction: an object {prerequisites, auth_role, steps, cleanup}")
        return None
    unknown = set(value) - {"prerequisites", "auth_role", "steps", "cleanup"}
    if unknown:
        errors.append(f"reproduction: unknown fields {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for field, limit in (("prerequisites", 2000), ("auth_role", 200), ("cleanup", 2000)):
        if value.get(field) is not None:
            text = _text(value[field], f"reproduction.{field}", limit, errors)
            if text:
                out[field] = text
    steps = value.get("steps", [])
    if not isinstance(steps, list) or len(steps) > 40:
        errors.append("reproduction.steps: a list of at most 40 steps")
        return out
    out["steps"] = []
    for i, step in enumerate(steps):
        name = f"reproduction.steps[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{name}: an object {{action, expected, evidence}}")
            continue
        action = _text(step.get("action"), f"{name}.action", 4000, errors)
        expected = (_text(step["expected"], f"{name}.expected", 2000, errors)
                    if step.get("expected") is not None else None)
        evidence = _digests(step.get("evidence"), f"{name}.evidence", errors)
        if action is not None:
            out["steps"].append({"action": action, **({"expected": expected} if expected else {}),
                                 "evidence": evidence})
    return out


def validate_patch(patch: Any) -> dict[str, Any]:
    """Normalise a write-up patch (section -> value, null clears) or raise
    ``WriteupError``. Shapes only: an incomplete section is accepted."""
    if not isinstance(patch, dict) or not patch:
        raise WriteupError(["writeup: must be a non-empty object of sections"])
    errors: list[str] = []
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in SECTIONS:
            errors.append(f"{key}: unknown section (allowed: {', '.join(SECTIONS)})")
            continue
        if value is None:
            clean[key] = None
        elif key in TEXT_SECTIONS:
            text = _text(value, key, TEXT_SECTIONS[key], errors)
            if text is not None:
                clean[key] = text
        elif key in SHORT_SECTIONS:
            text = _text(value, key, SHORT_SECTIONS[key], errors)
            if text is not None:
                clean[key] = text
        elif key in ENUMS:
            if value not in ENUMS[key]:
                errors.append(f"{key}: one of {', '.join(ENUMS[key])}")
            else:
                clean[key] = value
        elif key == "cvss_vector":
            if not isinstance(value, str) or not _CVSS.match(value.strip()):
                errors.append("cvss_vector: a CVSS 3.x vector such as "
                              "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H")
            else:
                clean[key] = value.strip()
        elif key == "affected_assets":
            if not isinstance(value, list) or not 1 <= len(value) <= 50:
                errors.append("affected_assets: a list of 1 to 50 assets")
                continue
            assets = []
            for i, item in enumerate(value):
                name = f"affected_assets[{i}]"
                if not isinstance(item, dict) or item.get("kind") not in ASSET_KINDS:
                    errors.append(f"{name}: needs kind in {', '.join(ASSET_KINDS)}")
                    continue
                text = _text(item.get("value"), f"{name}.value", 2048, errors)
                note = (_text(item["note"], f"{name}.note", 300, errors)
                        if item.get("note") is not None else None)
                if text is not None:
                    assets.append({"kind": item["kind"], "value": text,
                                   **({"note": note} if note else {})})
            clean[key] = assets
        elif key == "cwes":
            if not isinstance(value, list) or not 1 <= len(value) <= 10:
                errors.append("cwes: a list of 1 to 10 CWE entries")
                continue
            cwes = []
            for i, item in enumerate(value):
                cid = str(item.get("id", "")).strip().upper() if isinstance(item, dict) else ""
                if not _CWE.match(cid):
                    errors.append(f"cwes[{i}].id: must look like CWE-639")
                    continue
                label = _text(item.get("name"), f"cwes[{i}].name", 200, errors)
                if label is not None:
                    cwes.append({"id": cid, "name": label})
            clean[key] = cwes
        elif key == "references":
            if not isinstance(value, list) or not 1 <= len(value) <= 20:
                errors.append("references: a list of 1 to 20 references")
                continue
            refs = []
            for i, item in enumerate(value):
                item = {"url": item} if isinstance(item, str) else item
                if not isinstance(item, dict):
                    errors.append(f"references[{i}]: needs a url")
                    continue
                url = str(item.get("url", "")).strip()
                problem = reference_problem(url)
                if problem:
                    errors.append(f"references[{i}]: {problem}")
                    continue
                title = (_text(item["title"], f"references[{i}].title", 300, errors)
                         if item.get("title") is not None else None)
                refs.append({"url": url, **({"title": title} if title else {})})
            clean[key] = refs
        elif key == "reproduction":
            rep = _reproduction(value, errors)
            if rep is not None:
                clean[key] = rep
        elif key == "http_exception":
            reason = (_text(value.get("reason"), "http_exception.reason", 1000, errors)
                      if isinstance(value, dict) else None)
            if not isinstance(value, dict):
                errors.append("http_exception: an object {reason}")
            elif reason is not None and len(reason) < 20:
                errors.append("http_exception.reason: explain in at least 20 characters "
                              "why no HTTP exchange can prove this issue")
            elif reason is not None:
                clean[key] = {"reason": reason}
    if errors:
        raise WriteupError(errors)
    return clean


def step_digests(sections: dict) -> list[str]:
    rep = sections.get("reproduction") or {}
    return [d for step in rep.get("steps") or [] for d in step.get("evidence") or []]


# UX-24 stored the operator's write-up flat; read it as an operator patch.
def _legacy(sections: dict) -> dict:
    out = {k: v for k, v in sections.items()
           if k in (*TEXT_SECTIONS, *SHORT_SECTIONS, *ENUMS, "cvss_vector", "references")}
    if sections.get("cwe"):
        out["cwes"] = [{"id": sections["cwe"], "name": sections["cwe"]}]
    if sections.get("component"):
        out["affected_assets"] = [{"kind": "component", "value": sections["component"]}]
    return out


def state(finding: dict, events: list[dict]) -> dict:
    """The current write-up: the agent's draft on the finding, then every
    `finding_writeup` patch oldest first. ``origin`` names the owner of each
    section (agent or operator)."""
    sections: dict[str, Any] = {}
    origin: dict[str, str] = {}
    author = "operator" if finding.get("manual") else "agent"
    for key, value in (finding.get("writeup") or {}).items():
        if value is not None:
            sections[key] = value
            origin[key] = author
    updated = {"by": finding.get("actor"), "role": author, "at": finding.get("ts")} \
        if finding.get("writeup") else None
    for event in sorted(events, key=lambda e: e.get("id") or 0):
        payload = event.get("payload") or {}
        if payload.get("finding_id") != finding.get("finding_id"):
            continue
        if "patch" in payload:
            patch, role = payload["patch"] or {}, payload.get("role") or "operator"
        else:
            patch, role = _legacy(payload.get("sections") or {}), "operator"
        for key, value in patch.items():
            if value is None:
                sections.pop(key, None)
                origin.pop(key, None)
            else:
                sections[key] = value
                origin[key] = role
        updated = {"by": payload.get("actor") or event.get("actor"), "role": role,
                   "at": event.get("ts")}
    return {"schema": SCHEMA, "sections": sections, "origin": origin, "updated": updated}


def markdown_problems(text: str, name: str) -> list[str]:
    """House format: a language on every code fence, one paragraph per line,
    no indentation except nested list items."""
    problems = []
    in_fence = False
    run = 0
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence and stripped == "```":
                problems.append(f"{name}: line {number}: code fence without a language")
            in_fence = not in_fence
            run = 0
            continue
        if in_fence:
            continue
        if line[:1] in (" ", "\t") and not re.match(r"^ +([-*+]|\d+\.) ", line):
            problems.append(f"{name}: line {number}: indented text outside a nested list")
        if not stripped or re.match(r"^(#|[-*+] |\d+\. |>|\|)", stripped):
            run = 0
            continue
        run += 1
        if run == 2:
            problems.append(f"{name}: line {number}: a paragraph wrapped over several lines; "
                            "keep one paragraph per line")
    if in_fence:
        problems.append(f"{name}: unclosed code fence")
    return problems


def _check(checks, check_id, label, problems, *, blocking=True):
    checks.append({"id": check_id, "label": label, "ok": not problems,
                   "blocking": blocking, "messages": problems})


def readiness(finding: dict, sections: dict, *, verified: bool | None,
              resolves=lambda digest: True) -> dict:
    """The report-readiness checklist. Every failed check says exactly what is
    missing. ``verified=None`` leaves the verification check out (the agent's
    view: verification outcomes are not disclosed to agents)."""
    w = sections or {}
    checks: list[dict] = []
    dedup = finding.get("dedup") or {}
    _check(checks, "reportable", "Finding is reportable",
           ["the finding duplicates another one: write up the original"]
           if dedup.get("relation") == "duplicate" else [])
    if verified is not None:
        _check(checks, "verified", "Technically verified",
               [] if verified else ["not verified: the validator or an operator must confirm "
                                    "it; prose does not verify"])
    meta = []
    if not w.get("affected_assets"):
        meta.append("affected_assets: list every affected host, endpoint, parameter or component")
    if not w.get("cwes"):
        meta.append("cwes: add at least one related CWE with its name")
    if not w.get("severity") and not finding.get("severity"):
        meta.append("severity: rate it")
    _check(checks, "metadata", "Metadata", meta)
    product = []
    if not w.get("product"):
        product.append("product: name the affected product")
    if not w.get("affected_versions"):
        product.append("affected_versions: state the affected versions")
    _check(checks, "product", "Affected product and versions", product)
    summary = w.get("summary") or ""
    _check(checks, "summary", "Summary (CVE description)",
           (["summary: one paragraph: product, version, attacker, impact, vector"]
            if not summary else []) + (["summary: keep it to one paragraph"]
                                       if summary.count("\n") else []))
    impact = w.get("impact") or ""
    lines = [line for line in impact.split("\n") if line.strip()]
    _check(checks, "impact", "Impact",
           (["impact is missing"] if not impact else [])
           + ([f"impact has {len(lines)} lines: keep it to two or three"] if len(lines) > 3 else [])
           + markdown_problems(impact, "impact"))
    for key, label in (("description", "Description"), ("remediation", "Remediation")):
        text = w.get(key) or ""
        _check(checks, key, label, ([f"{key} is missing"] if not text else [])
               + markdown_problems(text, key))
    rep = w.get("reproduction") or {}
    steps = rep.get("steps") or []
    problems = []
    if not rep.get("prerequisites"):
        problems.append("reproduction.prerequisites: state the setup and network position")
    if not rep.get("auth_role"):
        problems.append("reproduction.auth_role: the role used ('unauthenticated' if none)")
    if not steps:
        problems.append("reproduction.steps: add the numbered, deterministic steps")
    for i, step in enumerate(steps, 1):
        problems += markdown_problems(step.get("action", ""), f"step {i}")
        for digest in step.get("evidence") or []:
            if not resolves(digest):
                problems.append(f"step {i}: evidence {digest[:19]}… is not a record of this arena")
    _check(checks, "reproduction", "Reproduction steps", problems)
    http = finding.get("http_transactions") or []
    proof = []
    if w.get("http_exception"):
        if not finding.get("evidence_artifacts"):
            proof.append("http_exception is set: attach the equivalent command output as an "
                         "evidence artifact")
    elif not http:
        proof.append("no captured HTTP exchange: attach transaction_digests (or set "
                     "http_exception with a reason if the issue is genuinely not HTTP)")
    if steps and not any(step.get("evidence") for step in steps):
        proof.append("no reproduction step cites its evidence")
    _check(checks, "evidence", "Evidence linked to the steps", proof)
    refs = w.get("references") or []
    ref_problems = []
    if len(refs) < MIN_REFERENCES:
        ref_problems.append(f"references: {len(refs)} of at least {MIN_REFERENCES}")
    if refs and not any(r["url"].startswith(TRUSTED_REFERENCE_PREFIXES) for r in refs):
        ref_problems.append("references: include an OWASP cheat sheet, PortSwigger Web "
                            "Security Academy or CWE page")
    if len({r["url"] for r in refs}) != len(refs):
        ref_problems.append("references: duplicate URLs")
    _check(checks, "references", "References", ref_problems)
    prose = [summary, impact, w.get("description") or "", w.get("remediation") or "",
             rep.get("prerequisites") or "", rep.get("cleanup") or "",
             *(s.get("action", "") + "\n" + s.get("expected", "") for s in steps)]
    _check(checks, "secrets", "No credentials in prose",
           ["a credential-like value appears in the prose: keep raw values in evidence"]
           if any(_SECRET_IN_PROSE.search(t) for t in prose) else [])
    _check(checks, "cvss", "CVSS vector", [] if w.get("cvss_vector") else
           ["cvss_vector: optional, a CVSS 3.1 vector"], blocking=False)
    blocking = [c for c in checks if c["blocking"] and not c["ok"]]
    return {"schema": SCHEMA, "ready": not blocking,
            "missing": [m for c in blocking for m in c["messages"]], "checks": checks}
