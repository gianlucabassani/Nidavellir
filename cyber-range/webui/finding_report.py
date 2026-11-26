"""UX-24/25: a finding as a report you can send.

The reporting agent writes the report (the structured write-up, schema
nidavellir.finding-writeup.v1, owned and checked by the orchestrator); an
operator can take any section over. Where a section is still empty, the
report falls back to what the platform recorded (the hypothesis the finding
tested, its PoC, causality and evidence) and says so. Each section carries
its origin: agent, operator, derived (from the record) or missing.

Renders as Markdown and as a CVE request in the public request form's
fields. Pure functions: no I/O, text in, text out.
"""
from __future__ import annotations

import re

CWE_NAMES = {
    "CWE-20": "Improper Input Validation", "CWE-22": "Path Traversal",
    "CWE-77": "Command Injection", "CWE-78": "OS Command Injection",
    "CWE-79": "Cross-site Scripting", "CWE-89": "SQL Injection", "CWE-94": "Code Injection",
    "CWE-200": "Exposure of Sensitive Information", "CWE-269": "Improper Privilege Management",
    "CWE-284": "Improper Access Control", "CWE-285": "Improper Authorization",
    "CWE-287": "Improper Authentication", "CWE-306": "Missing Authentication for Critical Function",
    "CWE-352": "Cross-Site Request Forgery", "CWE-400": "Uncontrolled Resource Consumption",
    "CWE-434": "Unrestricted Upload of File with Dangerous Type",
    "CWE-502": "Deserialization of Untrusted Data", "CWE-601": "Open Redirect",
    "CWE-611": "XML External Entity Reference",
    "CWE-639": "Authorization Bypass Through User-Controlled Key",
    "CWE-668": "Exposure of Resource to Wrong Sphere", "CWE-798": "Use of Hard-coded Credentials",
    "CWE-862": "Missing Authorization", "CWE-863": "Incorrect Authorization",
    "CWE-918": "Server-Side Request Forgery", "CWE-1321": "Prototype Pollution",
}
ATTACK_TYPES = {"remote": "Remote", "adjacent": "Adjacent network", "local": "Local",
                "physical": "Physical"}
IMPACT_TYPES = {"code_execution": "Code execution",
                "information_disclosure": "Information disclosure",
                "denial_of_service": "Denial of service",
                "privilege_escalation": "Escalation of privileges", "other": "Other"}
SEVERITIES = ("critical", "high", "medium", "low", "info")
CAUSALITY = (("trace", "Trace"), ("fixed_build_control", "Control"), ("toggle", "Toggle"))
TEXT_KEYS = ("summary", "impact", "description", "remediation")


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _cwe_url(cwe_id: str) -> str:
    return f"https://cwe.mitre.org/data/definitions/{cwe_id.split('-')[1]}.html"


def _cwe_label(c: dict) -> str:
    return f"{c['id']}: {c['name']}" if c.get("name") and c["name"] != c["id"] else c["id"]


def build(finding: dict, *, view: dict | None = None, hypothesis: dict | None = None,
          tested: dict | None = None, arena: dict | None = None,
          validator: str | None = None, operator: str | None = None) -> dict:
    """The report for one finding.

    view: the orchestrator's write-up view {sections, origin, readiness,
    updated}; hypothesis: the registered contract the finding tested; tested:
    the hypothesis test record naming it; arena: {id, name, scenario}."""
    view = view or {}
    w = view.get("sections") or {}
    owner = view.get("origin") or {}
    contract = hypothesis or {}
    arena = arena or {}
    transactions = [t for t in finding.get("http_transactions") or [] if isinstance(t, dict)]
    artifacts = [a for a in finding.get("evidence_artifacts") or [] if isinstance(a, dict)]
    causality = finding.get("causality") if isinstance(finding.get("causality"), dict) else {}
    labels: dict[str, str] = {}
    for item in transactions + artifacts:
        if item.get("digest"):
            labels.setdefault(item["digest"], f"E{len(labels) + 1}")
    for step in (w.get("reproduction") or {}).get("steps") or []:
        for digest in step.get("evidence") or []:
            labels.setdefault(digest, f"E{len(labels) + 1}")

    def owned(key):
        return owner.get(key, "agent")

    cwes = w.get("cwes") or []
    if not cwes and finding.get("cwe"):
        cid = str(finding["cwe"]).upper()
        cwes = [{"id": cid, "name": CWE_NAMES.get(cid, "")}]
    reporter_severity = finding.get("severity") if finding.get("severity") in SEVERITIES else None

    def fact(key, value, derived_value=None, source=""):
        if value:
            return {"value": value, "origin": owned(key)}
        if derived_value:
            return {"value": derived_value, "origin": "derived", "source": source}
        return {"value": None, "origin": "missing"}

    component = " · ".join(x for x in (_text(finding.get("path")), _text(finding.get("param"))) if x)
    assets = w.get("affected_assets") or []
    facts = {
        "severity": fact("severity", w.get("severity"), reporter_severity,
                         "the reporter's rating"),
        "cwe": fact("cwes", ", ".join(_cwe_label(c) for c in w.get("cwes") or []),
                    ", ".join(_cwe_label(c) for c in cwes), "the finding"),
        "affected_assets": fact("affected_assets",
                                "; ".join(f"{a['kind']}: {a['value']}" for a in assets),
                                f"component: {component}" if component else None,
                                "the finding's path and parameter"),
        "vendor": fact("vendor", w.get("vendor")),
        "product": fact("product", w.get("product"), _text(arena.get("scenario")),
                        "the arena's scenario"),
        "affected_versions": fact("affected_versions", w.get("affected_versions")),
        "fixed_versions": fact("fixed_versions", w.get("fixed_versions")),
        "attack_type": fact("attack_type", w.get("attack_type"),
                            "remote" if transactions else None, "the evidence is HTTP traffic"),
        "impact_type": fact("impact_type", w.get("impact_type")),
        "cvss_vector": fact("cvss_vector", w.get("cvss_vector")),
        "discoverer": fact("discoverer", w.get("discoverer"), _text(finding.get("actor")),
                           "the reporting agent"),
        "station": {"value": finding.get("node"),
                    "origin": "derived" if finding.get("node") else "missing"},
    }

    sections: list[dict] = []

    def text_section(key, title, derived_text="", source=""):
        if w.get(key):
            sections.append({"key": key, "title": title, "origin": owned(key), "text": w[key]})
        elif derived_text:
            sections.append({"key": key, "title": title, "origin": "derived", "source": source,
                             "text": derived_text})
        else:
            sections.append({"key": key, "title": title, "origin": "missing"})

    where = " ".join(x for x in (facts["product"]["value"], facts["affected_versions"]["value"])
                     if x)
    summary = _text(finding.get("title"))
    if summary and where:
        summary = f"{summary.rstrip('.')} ({where})."
    text_section("summary", "Summary", summary, "the finding title and affected product")
    text_section("impact", "Impact")

    parts = []
    if _text(contract.get("invariant")):
        parts.append(f"Expected behaviour: {_text(contract['invariant'])}")
    source_sink = contract.get("source_sink") if isinstance(contract.get("source_sink"), dict) else {}
    if _text(source_sink.get("source")) or _text(source_sink.get("sink")):
        parts.append(f"Source: {_text(source_sink.get('source')) or 'not stated'}. "
                     f"Sink: {_text(source_sink.get('sink')) or 'not stated'}.")
    if _text((causality.get("trace") or {}).get("summary")):
        parts.append(f"Observed: {_text(causality['trace']['summary'])}")
    if not parts and _text(finding.get("evidence")):
        parts.append(_text(finding["evidence"]))
    text_section("description", "Description", "\n\n".join(parts), "the hypothesis and trace")

    rep = w.get("reproduction") or {}
    if rep:
        steps = [{**step, "evidence": [{"digest": d, "label": labels.get(d, "E?")}
                                       for d in step.get("evidence") or []]}
                 for step in rep.get("steps") or []]
        sections.append({"key": "reproduction", "title": "Reproduction steps",
                         "origin": owned("reproduction"), "reproduction": {**rep, "steps": steps}})
    else:
        preconditions = [_text(p) for p in contract.get("preconditions") or [] if _text(p)]
        poc = _text(finding.get("poc"))
        entry = {"key": "reproduction", "title": "Reproduction steps"}
        if preconditions or poc:
            entry.update(origin="derived",
                         source="the hypothesis preconditions and the reporter's PoC")
            if preconditions:
                entry["reproduction"] = {"prerequisites": "; ".join(preconditions), "steps": []}
            if poc:
                entry["code"] = poc
        else:
            entry["origin"] = "missing"
        sections.append(entry)

    proof = ["Independent validator: " + (validator or "no conclusion").replace("_", " "),
             "Operator decision: " + (operator or "not decided yet")]
    for key, label in CAUSALITY:
        claim = causality.get(key) or {}
        if _text(claim.get("summary")):
            proof.append(f"{label}: {_text(claim['summary'])} ({claim.get('evidence_digest', '')})")
    if _text((tested or {}).get("note")):
        proof.append(f"Hypothesis {tested.get('hypothesis_id', '')} {tested.get('outcome', '')}: "
                     f"{_text(tested['note'])}")
    for t in transactions:
        proof.append(f"{labels.get(t.get('digest'), 'E?')} HTTP {t.get('method', '')} "
                     f"{t.get('path', '')} -> {t.get('status', '')} ({t.get('digest', '')})")
    for a in artifacts:
        proof.append(f"{labels.get(a.get('digest'), 'E?')} artifact {a.get('bytes', '?')} bytes "
                     f"({a.get('digest', '')})")
    if (w.get("http_exception") or {}).get("reason"):
        proof.append(f"No HTTP exchange: {w['http_exception']['reason']}")
    sections.append({"key": "evidence", "title": "Evidence", "origin": "derived",
                     "source": "validation, causality and evidence records", "items": proof})
    text_section("remediation", "Remediation")

    refs = list(w.get("references") or [])
    for c in cwes:
        if c.get("id") and not any(r.get("url") == _cwe_url(c["id"]) for r in refs):
            refs.append({"url": _cwe_url(c["id"]), "title": f"{c['id']}: {c.get('name') or 'weakness'}"})
    sections.append({"key": "references", "title": "References",
                     "origin": owned("references") if w.get("references")
                     else "derived" if refs else "missing", "links": refs})

    report = {
        "id": finding.get("finding_id"), "title": _text(finding.get("title")) or "Untitled finding",
        "facts": facts, "sections": sections,
        "verdict": {"validator": validator, "operator": operator},
        "reported_at": finding.get("ts"), "reported_by": finding.get("actor"),
        "arena": {"id": arena.get("id"), "name": arena.get("name")},
        "readiness": view.get("readiness") or {"ready": False, "missing": [], "checks": []},
        "writeup": w, "origin": owner, "updated": view.get("updated"),
        "evidence_options": [
            {"digest": t["digest"], "label": labels.get(t["digest"], "E?"),
             "what": f"HTTP {t.get('method', '')} {t.get('path', '')} -> {t.get('status', '')}"}
            for t in transactions if t.get("digest")] + [
            {"digest": a["digest"], "label": labels.get(a["digest"], "E?"),
             "what": f"artifact {a.get('bytes', '?')} bytes"}
            for a in artifacts if a.get("digest")],
    }
    report["markdown"] = markdown(report)
    report["cve_request"] = cve_request(report)
    return report


def _cell(value) -> str:
    return str(value or "Not stated").replace("|", "\\|").replace("\n", " ")


def _fence(code: str, language: str = "text") -> str:
    longest = max((len(m) for m in re.findall(r"`{3,}", code)), default=2)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{language}\n{code}\n{ticks}"


def markdown(report: dict) -> str:
    f = report["facts"]
    severity = (f["severity"]["value"] or "not rated").capitalize()
    if f["cvss_vector"]["value"]:
        severity += f" ({f['cvss_vector']['value']})"
    rows = [("Report ID", report.get("id")), ("Severity", severity),
            ("Weakness", f["cwe"]["value"]), ("Affected assets", f["affected_assets"]["value"]),
            ("Vendor", f["vendor"]["value"]), ("Product", f["product"]["value"]),
            ("Affected versions", f["affected_versions"]["value"]),
            ("Fixed versions", f["fixed_versions"]["value"]),
            ("Attack type", ATTACK_TYPES.get(f["attack_type"]["value"] or "")),
            ("Impact type", IMPACT_TYPES.get(f["impact_type"]["value"] or "")),
            ("Discovered by", f["discoverer"]["value"]), ("Reported", report.get("reported_at"))]
    out = [f"# {report['title']}", "", "| Field | Value |", "|---|---|"]
    out += [f"| {k} | {_cell(v)} |" for k, v in rows]
    for s in report["sections"]:
        out += ["", f"## {s['title']}", ""]
        if s["origin"] == "missing":
            out.append("_Not written yet._")
            continue
        if s.get("text"):
            out.append(s["text"])
        rep = s.get("reproduction")
        if rep:
            if rep.get("prerequisites"):
                out.append(f"- Prerequisites: {rep['prerequisites']}")
            if rep.get("auth_role"):
                out.append(f"- Authentication role: {rep['auth_role']}")
            for i, step in enumerate(rep.get("steps") or [], 1):
                cites = ", ".join(e["label"] for e in step.get("evidence") or [])
                out.append(f"{i}. {step['action']}" + (f" (evidence {cites})" if cites else ""))
                if step.get("expected"):
                    out.append(f"   - Expected: {step['expected']}")
            if rep.get("cleanup"):
                out.append(f"- Cleanup: {rep['cleanup']}")
        if s.get("code"):
            out.append(_fence(s["code"]))
        if s["key"] == "references":
            out += [f"- [{r.get('title') or r['url']}]({r['url']})" for r in s.get("links") or []]
        elif s.get("items"):
            out += [f"- {item}" for item in s["items"]]
    return "\n".join(out).rstrip() + "\n"


def cve_request(report: dict) -> str:
    """The report in the fields of the public CVE request form."""
    f = report["facts"]
    sections = {s["key"]: s for s in report["sections"]}
    rep = sections["reproduction"].get("reproduction") or {}
    vector = next((step["action"].splitlines()[0] for step in rep.get("steps") or []), "") \
        or next((line.strip() for line in (sections["reproduction"].get("code") or "").splitlines()
                 if line.strip()), "")
    refs = [r["url"] for r in sections["references"].get("links") or []]
    fields = [
        ("Suggested description", sections["summary"].get("text")),
        ("Vulnerability type", f["cwe"]["value"]),
        ("Vendor of the product", f["vendor"]["value"]),
        ("Affected product code base",
         " ".join(x for x in (f["product"]["value"], f["affected_versions"]["value"]) if x) or None),
        ("Fixed versions", f["fixed_versions"]["value"]),
        ("Affected component", f["affected_assets"]["value"]),
        ("Attack type", ATTACK_TYPES.get(f["attack_type"]["value"] or "")),
        ("Impact", IMPACT_TYPES.get(f["impact_type"]["value"] or "")),
        ("CVSS", f["cvss_vector"]["value"]),
        ("Attack vectors", vector or None),
        ("Impact details", sections["impact"].get("text")),
        ("Reference", "\n".join(refs) or None),
        ("Discoverer", f["discoverer"]["value"]),
    ]
    return "\n\n".join(f"[{name}]\n{value or 'TO BE COMPLETED'}" for name, value in fields) + "\n"
