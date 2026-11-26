"""UX-24: a finding as a report you can send.

Builds one report from what the platform already holds (the finding, its
hypothesis contract and test note, root cause, causality and evidence) plus
the operator's write-up (impact, remediation, affected product and the rest).
Each section says where its text came from: the operator, the record
(derived), or nowhere yet (missing). A readiness checklist names every gap.
The report renders as Markdown and as a CVE request in the fields of the
public request form. Pure functions: no I/O, no markup in, text out.
"""
from __future__ import annotations

import re

# Common weaknesses: name and the CVE form's impact type.
CWES = {
    "CWE-20": ("Improper Input Validation", "other"),
    "CWE-22": ("Path Traversal", "information_disclosure"),
    "CWE-77": ("Command Injection", "code_execution"),
    "CWE-78": ("OS Command Injection", "code_execution"),
    "CWE-79": ("Cross-site Scripting", "other"),
    "CWE-89": ("SQL Injection", "information_disclosure"),
    "CWE-94": ("Code Injection", "code_execution"),
    "CWE-200": ("Exposure of Sensitive Information", "information_disclosure"),
    "CWE-209": ("Information Exposure Through an Error Message", "information_disclosure"),
    "CWE-269": ("Improper Privilege Management", "privilege_escalation"),
    "CWE-284": ("Improper Access Control", "privilege_escalation"),
    "CWE-285": ("Improper Authorization", "privilege_escalation"),
    "CWE-287": ("Improper Authentication", "privilege_escalation"),
    "CWE-306": ("Missing Authentication for Critical Function", "privilege_escalation"),
    "CWE-352": ("Cross-Site Request Forgery", "other"),
    "CWE-400": ("Uncontrolled Resource Consumption", "denial_of_service"),
    "CWE-434": ("Unrestricted Upload of File with Dangerous Type", "code_execution"),
    "CWE-502": ("Deserialization of Untrusted Data", "code_execution"),
    "CWE-601": ("Open Redirect", "other"),
    "CWE-611": ("XML External Entity Reference", "information_disclosure"),
    "CWE-639": ("Authorization Bypass Through User-Controlled Key", "privilege_escalation"),
    "CWE-668": ("Exposure of Resource to Wrong Sphere", "information_disclosure"),
    "CWE-798": ("Use of Hard-coded Credentials", "privilege_escalation"),
    "CWE-862": ("Missing Authorization", "privilege_escalation"),
    "CWE-863": ("Incorrect Authorization", "privilege_escalation"),
    "CWE-918": ("Server-Side Request Forgery", "information_disclosure"),
    "CWE-1321": ("Prototype Pollution", "code_execution"),
}
SEVERITIES = ("critical", "high", "medium", "low", "info")
ATTACK_TYPES = {"remote": "Remote", "adjacent": "Adjacent network", "local": "Local",
                "physical": "Physical"}
IMPACT_TYPES = {"code_execution": "Code execution",
                "information_disclosure": "Information disclosure",
                "denial_of_service": "Denial of service",
                "privilege_escalation": "Escalation of privileges", "other": "Other"}
CAUSALITY = (("trace", "Trace"), ("fixed_build_control", "Control"), ("toggle", "Toggle"))


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _cwe(value) -> dict | None:
    match = re.search(r"CWE-(\d{1,5})", value or "", re.IGNORECASE)
    if not match:
        return None
    cwe_id = f"CWE-{match.group(1)}"
    name = CWES.get(cwe_id, ("", ""))[0]
    return {"id": cwe_id, "name": name,
            "url": f"https://cwe.mitre.org/data/definitions/{match.group(1)}.html"}


def _verified(validator: str | None, operator: str | None) -> bool:
    if operator == "refuted":
        return False
    return validator == "confirmed" or operator == "confirmed"


def build(finding: dict, *, writeup: dict | None = None, hypothesis: dict | None = None,
          tested: dict | None = None, arena: dict | None = None,
          validator: str | None = None, operator: str | None = None) -> dict:
    """The report for one finding.

    finding: the stored finding payload; writeup: the newest operator write-up
    event payload; hypothesis: the registered contract the finding tested;
    tested: the hypothesis test record naming this finding; arena: {id, name,
    scenario}; validator/operator: the two verdicts, kept apart."""
    w = (writeup or {}).get("sections") or {}
    contract = hypothesis or {}
    arena = arena or {}
    transactions = [t for t in finding.get("http_transactions") or [] if isinstance(t, dict)]
    artifacts = [a for a in finding.get("evidence_artifacts") or [] if isinstance(a, dict)]
    causality = finding.get("causality") if isinstance(finding.get("causality"), dict) else {}
    cwe = _cwe(w.get("cwe") or finding.get("cwe"))
    severity = w.get("severity") or (finding.get("severity")
                                     if finding.get("severity") in SEVERITIES else None)
    verified = _verified(validator, operator)

    def fact(key, derived=None, source=""):
        if _text(w.get(key)):
            return {"value": _text(w[key]), "origin": "operator"}
        if derived:
            return {"value": derived, "origin": "derived", "source": source}
        return {"value": None, "origin": "missing"}

    component = " · ".join(x for x in (_text(finding.get("path")), _text(finding.get("param"))) if x)
    facts = {
        "severity": ({"value": severity, "origin": "operator" if w.get("severity") else "derived",
                      "source": "the reporter's rating"} if severity
                     else {"value": None, "origin": "missing"}),
        "cwe": ({"value": cwe["id"], "origin": "operator" if w.get("cwe") else "derived",
                 "source": "the finding"} if cwe else {"value": None, "origin": "missing"}),
        "vendor": fact("vendor"),
        "product": fact("product", _text(arena.get("scenario")), "the arena's scenario"),
        "affected_versions": fact("affected_versions"),
        "fixed_versions": fact("fixed_versions"),
        "component": fact("component", component, "the finding's path and parameter"),
        "station": {"value": finding.get("node"), "origin": "derived" if finding.get("node") else "missing"},
        "attack_type": fact("attack_type", "remote" if transactions else None,
                            "the evidence is HTTP traffic"),
        "impact_type": fact("impact_type", CWES.get((cwe or {}).get("id", ""), ("", ""))[1] or None,
                            "the weakness"),
        "cvss_vector": fact("cvss_vector"),
        "discoverer": fact("discoverer", _text(finding.get("actor")) or None, "the reporting agent"),
    }

    sections = []

    def section(key, title, *, operator_text=None, derived=None, source="", items=None,
                code=None):
        entry = {"key": key, "title": title}
        if _text(operator_text):
            entry.update(origin="operator", text=_text(operator_text))
        elif derived or items or code:
            entry.update(origin="derived", source=source)
            if derived:
                entry["text"] = derived
            if items:
                entry["items"] = items
            if code:
                entry["code"] = code
        else:
            entry["origin"] = "missing"
        sections.append(entry)

    product = facts["product"]["value"]
    versions = facts["affected_versions"]["value"]
    where = " ".join(x for x in (product, versions) if x)
    summary = _text(finding.get("title"))
    if summary and where:
        summary = f"{summary.rstrip('.')} ({where})."
    section("summary", "Summary", operator_text=w.get("summary"), derived=summary,
            source="the finding title and affected product")
    section("impact", "Impact", operator_text=w.get("impact"))

    parts = []
    if _text(contract.get("invariant")):
        parts.append(f"Expected behaviour: {_text(contract['invariant'])}")
    source_sink = contract.get("source_sink") if isinstance(contract.get("source_sink"), dict) else {}
    if _text(source_sink.get("source")) or _text(source_sink.get("sink")):
        parts.append(f"Source: {_text(source_sink.get('source')) or 'not stated'}. "
                     f"Sink: {_text(source_sink.get('sink')) or 'not stated'}.")
    normalised = ((finding.get("root_cause") or {}).get("normalised") or {}) \
        if isinstance(finding.get("root_cause"), dict) else {}
    if not parts and normalised:
        parts.extend(f"{label}: {normalised[key]}" for key, label in (
            ("invariant", "Invariant"), ("source", "Source"), ("sink", "Sink"),
            ("missing_check", "Missing check")) if normalised.get(key))
    if _text((causality.get("trace") or {}).get("summary")):
        parts.append(f"Observed: {_text(causality['trace']['summary'])}")
    if not parts and _text(finding.get("evidence")):
        parts.append(_text(finding["evidence"]))
    section("description", "Description", operator_text=w.get("description"),
            derived="\n\n".join(parts), source="the hypothesis, root cause and trace")

    preconditions = [_text(p) for p in contract.get("preconditions") or [] if _text(p)]
    section("prerequisites", "Prerequisites", items=preconditions,
            source="the hypothesis preconditions")
    section("steps", "Steps to reproduce", code=_text(finding.get("poc")),
            source="the reporter's proof of concept")

    proof = []
    proof.append("Independent validator: " + (validator or "no conclusion").replace("_", " "))
    proof.append("Operator decision: " + (operator or "not decided yet"))
    for key, label in CAUSALITY:
        claim = causality.get(key) or {}
        if _text(claim.get("summary")):
            proof.append(f"{label}: {_text(claim['summary'])} ({claim.get('evidence_digest', '')})")
    if _text((tested or {}).get("note")):
        proof.append(f"Hypothesis {tested.get('hypothesis_id', '')} {tested.get('outcome', '')}: "
                     f"{_text(tested['note'])}")
    for t in transactions:
        proof.append(f"HTTP {t.get('method', '')} {t.get('path', '')} -> {t.get('status', '')} "
                     f"({t.get('digest', '')})")
    for a in artifacts:
        proof.append(f"Artifact {a.get('bytes', '?')} bytes ({a.get('digest', '')})")
    section("proof", "Proof", items=proof, source="validation, causality and evidence records")
    section("remediation", "Remediation", operator_text=w.get("remediation"))

    references = [{"url": cwe["url"], "title": f"{cwe['id']}: {cwe['name'] or 'weakness'}"}] if cwe else []
    references += [r for r in w.get("references") or [] if isinstance(r, dict) and r.get("url")]
    sections.append({"key": "references", "title": "References",
                     "origin": "operator" if w.get("references") else "derived" if references else "missing",
                     "items": [f"{r.get('title') or r['url']}: {r['url']}" for r in references],
                     "links": references})

    by_key = {s["key"]: s for s in sections}
    has_proof = bool(transactions or artifacts or any(causality.get(k) for k, _ in CAUSALITY))
    checks = [
        ("severity", "Severity is set", bool(severity), True,
         "Set a severity (the reporter's rating is a claim until you confirm it)."),
        ("cwe", "Weakness (CWE) is named", bool(cwe), True, "Name the CWE."),
        ("product", "Affected product and version are stated",
         facts["product"]["origin"] == "operator" and bool(versions), True,
         "Write the product and affected versions; the arena's scenario name is only a hint."),
        ("impact", "Impact is written", by_key["impact"]["origin"] == "operator", True,
         "Write the impact: attacker capability, affected asset, consequence."),
        ("description", "Description is present", by_key["description"]["origin"] != "missing", True,
         "Describe the vulnerable component and the root cause."),
        ("steps", "Steps to reproduce are present", by_key["steps"]["origin"] != "missing", True,
         "The finding has no proof of concept."),
        ("proof", "Evidence is attached", has_proof, True,
         "Attach an HTTP transaction, an artifact or a causality claim."),
        ("remediation", "Remediation is written", by_key["remediation"]["origin"] == "operator", True,
         "Write the fix: what to check, where, against which policy."),
        ("verified", "Technically verified", verified, True,
         "Confirm the finding (or wait for the validator) before you send it."),
        ("cvss", "CVSS vector", bool(facts["cvss_vector"]["value"]), False,
         "Optional: add a CVSS 3.1 vector."),
    ]
    readiness = [{"id": i, "label": label, "ok": ok, "blocking": blocking,
                  "message": None if ok else message}
                 for i, label, ok, blocking, message in checks]
    report = {
        "id": finding.get("finding_id"), "title": _text(finding.get("title")) or "Untitled finding",
        "cwe": cwe, "facts": facts, "sections": sections,
        "verdict": {"validator": validator, "operator": operator, "verified": verified},
        "reported_at": finding.get("ts"), "reported_by": finding.get("actor"),
        "arena": {"id": arena.get("id"), "name": arena.get("name")},
        "readiness": {"ready": all(c["ok"] for c in readiness if c["blocking"]),
                      "missing": [c["id"] for c in readiness if c["blocking"] and not c["ok"]],
                      "checks": readiness},
        "writeup": w, "updated_by": (writeup or {}).get("actor"),
        "updated_at": (writeup or {}).get("ts"),
    }
    report["markdown"] = markdown(report)
    report["cve_request"] = cve_request(report)
    return report


def _cell(value) -> str:
    return str(value or "Not stated").replace("|", "\\|").replace("\n", " ")


def _fence(code: str) -> str:
    longest = max((len(m) for m in re.findall(r"`{3,}", code)), default=2)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}text\n{code}\n{ticks}"


def markdown(report: dict) -> str:
    f = report["facts"]
    cwe = report.get("cwe") or {}
    severity = (f["severity"]["value"] or "not rated").capitalize()
    if f["cvss_vector"]["value"]:
        severity += f" ({f['cvss_vector']['value']})"
    verdict = report["verdict"]
    rows = [
        ("Report ID", report.get("id")),
        ("Severity", severity),
        ("Weakness", f"{cwe['id']}: {cwe['name']}" if cwe.get("name") else cwe.get("id")),
        ("Vendor", f["vendor"]["value"]),
        ("Product", f["product"]["value"]),
        ("Affected versions", f["affected_versions"]["value"]),
        ("Fixed versions", f["fixed_versions"]["value"]),
        ("Component", f["component"]["value"]),
        ("Attack type", ATTACK_TYPES.get(f["attack_type"]["value"] or "", None)),
        ("Impact type", IMPACT_TYPES.get(f["impact_type"]["value"] or "", None)),
        ("Discovered by", f["discoverer"]["value"]),
        ("Reported", report.get("reported_at")),
        ("Verification", "verified" if verdict["verified"] else "not verified"),
    ]
    out = [f"# {report['title']}", "", "| Field | Value |", "|---|---|"]
    out += [f"| {k} | {_cell(v)} |" for k, v in rows]
    for s in report["sections"]:
        out += ["", f"## {s['title']}", ""]
        if s["origin"] == "missing":
            out.append("_Not written yet._")
            continue
        if s.get("text"):
            out.append(s["text"])
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
    cwe = report.get("cwe") or {}
    impact = f["impact_type"]["value"]
    steps = sections["steps"].get("code") or ""
    vector = next((line.strip() for line in steps.splitlines() if line.strip()), "")
    refs = [r["url"] for r in sections["references"].get("links") or []]
    fields = [
        ("Suggested description", sections["summary"].get("text")),
        ("Vulnerability type", " / ".join(x for x in (cwe.get("id"), cwe.get("name")) if x) or None),
        ("Vendor of the product", f["vendor"]["value"]),
        ("Affected product code base",
         " ".join(x for x in (f["product"]["value"], f["affected_versions"]["value"]) if x) or None),
        ("Fixed versions", f["fixed_versions"]["value"]),
        ("Affected component", f["component"]["value"]),
        ("Attack type", ATTACK_TYPES.get(f["attack_type"]["value"] or "", None)),
        ("Impact", IMPACT_TYPES.get(impact or "", None)),
        ("CVSS", f["cvss_vector"]["value"]),
        ("Attack vectors", vector or None),
        ("Impact details", sections["impact"].get("text")),
        ("Reference", "\n".join(refs) or None),
        ("Discoverer", f["discoverer"]["value"]),
    ]
    return "\n\n".join(f"[{name}]\n{value or 'TO BE COMPLETED'}" for name, value in fields) + "\n"
