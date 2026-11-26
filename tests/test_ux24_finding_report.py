"""UX-24: findings as reports you can send.

The operator writes a report's missing sections (impact, remediation,
affected product and versions) as an append-only `finding_writeup` event;
the newest wins and agents never see it. The console assembles the report
from the finding, its hypothesis and evidence plus that write-up, names every
gap, and renders Markdown and a CVE request. BFF routes are covered in
test_webui.py (UX-24 tests)."""
import sys
from pathlib import Path

from tests.research_support import active_arena, bind, client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cyber-range" / "webui"))
import finding_report  # noqa: E402


def _finding(operator, arena, **extra):
    r = operator.post(f"/arenas/{arena}/findings/manual",
                      json={"title": "Upload runs as code", "cwe": "CWE-94", **extra})
    assert r.status_code == 200, r.text
    events = operator.get(f"/deployments/{arena}/events?type=finding").json()["events"]
    return events[0]["payload"]["finding_id"]


def test_writeup_is_operator_only_append_only_and_hidden_from_agents():
    arena = active_arena("ux24-scenario")
    operator = client("operator")
    fid = _finding(operator, arena)
    path = f"/arenas/{arena}/findings/{fid}/writeup"
    first = operator.post(path, json={"impact": "  Remote code execution.  ", "product": "CMS",
                                      "attack_type": "remote"})
    assert first.status_code == 200, first.text
    assert first.json()["sections"] == {"impact": "Remote code execution.", "product": "CMS",
                                        "attack_type": "remote"}
    operator.post(path, json={"impact": "Second text"})
    stored = operator.get(f"/deployments/{arena}/events?type=finding_writeup").json()["events"]
    assert [e["payload"]["sections"].get("impact") for e in stored] == [
        "Second text", "Remote code execution."]  # newest first; history kept

    agent = client("agent")
    bind(operator, arena, agent, stance="attacker")
    assert agent.post(path, json={"impact": "x"}).status_code == 403
    seen = agent.get(f"/deployments/{arena}/events").json()["events"]
    assert not [e for e in seen if e["type"] == "finding_writeup"]
    assert agent.get(f"/deployments/{arena}/events?type=finding_writeup").json()["events"] == []


def test_writeup_rejects_unknown_findings_and_bad_fields():
    arena = active_arena("ux24-scenario")
    operator = client("operator")
    fid = _finding(operator, arena)
    path = f"/arenas/{arena}/findings/{fid}/writeup"
    assert operator.post(f"/arenas/{arena}/findings/000000000000/writeup",
                         json={}).status_code == 404
    assert operator.post(f"/arenas/no-such-arena/findings/{fid}/writeup",
                         json={}).status_code == 404
    for bad in ({"cvss_vector": "CVSS:3.1/AV:X"}, {"references": [{"url": "http://plain.example"}]},
                {"references": [{"url": "javascript:alert(1)"}]}, {"severity": "severe"},
                {"cwe": "94"}, {"attack_type": "telepathy"}, {"unknown": "field"},
                {"impact": "x" * 4001}):
        assert operator.post(path, json=bad).status_code == 422, bad
    ok = operator.post(path, json={
        "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", "cwe": "CWE-94",
        "references": [{"url": "https://example.org/advisory", "title": "Advisory"}]})
    assert ok.status_code == 200, ok.text


FINDING = {
    "finding_id": "abc123abc123", "title": "Static export runs an uploaded .jspf",
    "severity": "high", "cwe": "CWE-94", "node": "victim", "actor": "research-agent",
    "path": "/export/sites/default/x.jspf", "param": "export property",
    "poc": "1. PUT /webdav/x.jspf\n```\nbody\n```\n2. GET /export/x.jspf",
    "ts": "2026-11-26 10:52:17",
    "http_transactions": [{"digest": "sha256:" + "a" * 64, "method": "GET",
                           "path": "/export/x.jspf", "status": 200}],
    "causality": {"trace": {"summary": "second GET printed the marker",
                            "evidence_digest": "sha256:" + "a" * 64}},
}
CONTRACT = {"id": "H-F1", "invariant": "Exported files must never execute.",
            "preconditions": ["Low-privilege workplace user"],
            "source_sink": {"source": "VFS body", "sink": "JSP servlet"}}
TESTED = {"hypothesis_id": "H-F1", "outcome": "supported", "note": "Executed as opencms",
          "finding_ids": ["abc123abc123"]}


def test_report_derives_from_the_record_and_names_every_gap():
    report = finding_report.build(FINDING, hypothesis=CONTRACT, tested=TESTED,
                                  arena={"id": "a1", "name": "cms", "scenario": "cms-22"},
                                  validator="inconclusive", operator=None)
    sections = {s["key"]: s for s in report["sections"]}
    assert sections["description"]["origin"] == "derived"
    assert "Exported files must never execute." in sections["description"]["text"]
    assert "Sink: JSP servlet." in sections["description"]["text"]
    assert sections["prerequisites"]["items"] == ["Low-privilege workplace user"]
    assert sections["impact"]["origin"] == "missing"
    assert sections["remediation"]["origin"] == "missing"
    assert any("Executed as opencms" in item for item in sections["proof"]["items"])
    assert report["facts"]["product"] == {"value": "cms-22", "origin": "derived",
                                          "source": "the arena's scenario"}
    assert report["facts"]["impact_type"]["value"] == "code_execution"
    assert report["facts"]["attack_type"]["value"] == "remote"
    readiness = report["readiness"]
    assert readiness["ready"] is False
    assert set(readiness["missing"]) == {"product", "impact", "remediation", "verified"}
    assert sections["references"]["links"][0]["url"] == "https://cwe.mitre.org/data/definitions/94.html"


def test_operator_writeup_completes_the_report_and_renders():
    writeup = {"actor": "admin", "ts": "2026-11-26 12:00:00", "sections": {
        "impact": "A workplace author runs code as the CMS user.",
        "remediation": "Block every JSP-mapped extension in the export.",
        "product": "OpenCms", "affected_versions": "22.0", "vendor": "Alkacon",
        "summary": "OpenCms 22.0 lets an author run code | via export.",
        "references": [{"url": "https://example.org/a", "title": "Advisory"}]}}
    report = finding_report.build(FINDING, writeup=writeup, hypothesis=CONTRACT, tested=TESTED,
                                  arena={"id": "a1", "scenario": "cms-22"},
                                  validator="inconclusive", operator="confirmed")
    assert report["readiness"]["ready"] is True
    md = report["markdown"]
    assert md.startswith("# Static export runs an uploaded .jspf\n")
    for heading in ("## Summary", "## Impact", "## Description", "## Prerequisites",
                    "## Steps to reproduce", "## Proof", "## Remediation", "## References"):
        assert heading in md
    assert "| Product | OpenCms |" in md and "| Weakness | CWE-94: Code Injection |" in md
    assert "````text\n1. PUT" in md  # the fence outgrows the PoC's own ``` block
    assert "- [Advisory](https://example.org/a)" in md
    cve = report["cve_request"]
    assert "[Suggested description]\nOpenCms 22.0 lets an author run code | via export." in cve
    assert "[Affected product code base]\nOpenCms 22.0" in cve
    assert "[Impact]\nCode execution" in cve
    assert "[Vendor of the product]\nAlkacon" in cve
    assert "TO BE COMPLETED" in cve  # fixed versions not given


def test_table_cells_cannot_break_the_markdown_table():
    finding = {**FINDING, "path": "/a|b\nc"}
    md = finding_report.build(finding)["markdown"]
    assert "| Component | /a\\|b c · export property |" in md
