"""UX-25: findings written up by the reporting agent.

The agent sends a structured write-up with its finding (schema
nidavellir.finding-writeup.v1) and completes it with patches; an operator
can take any section over, after which the agent's patches to it are refused.
Shapes are checked on write, completeness by the readiness checklist; the
agent's view leaves out verification. Prose never verifies or scores."""
import sys
from pathlib import Path

import http_transactions
import writeup
from tests.research_support import active_arena, bind, client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cyber-range" / "webui"))
import finding_report  # noqa: E402


def _tx(arena, path="/export/x.jspf"):
    return http_transactions.record(
        arena, request={"node": "victim", "method": "GET", "path": path, "params": {},
                        "headers": {}, "body": None},
        response={"status": 200, "body": "marker|uid=998"}, actor="agent")["digest"]


def complete(digest):
    return {
        "summary": "Example CMS 22.0 lets a workplace author run code on the server by publishing a .jspf file with export=true.",
        "impact": "A low-privilege author runs arbitrary code as the CMS service user.\n\nThe whole site and its database are exposed.",
        "description": "The static export blacklist misses `.jspf`, which the JSP servlet compiles.",
        "remediation": "Refuse every extension the container maps to its JSP servlet when exporting.",
        "affected_assets": [{"kind": "endpoint", "value": "/export/sites/default/x.jspf"}],
        "cwes": [{"id": "CWE-94", "name": "Code Injection"}],
        "severity": "high", "product": "Example CMS", "affected_versions": "22.0",
        "reproduction": {"prerequisites": "A workplace account in group Users.",
                         "auth_role": "workplace author",
                         "steps": [{"action": "Request the exported file.",
                                    "expected": "200 with the marker", "evidence": [digest]}]},
        "references": [{"url": "https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html"},
                       {"url": "https://cwe.mitre.org/data/definitions/94.html"},
                       {"url": "https://example.org/advisory", "title": "Vendor advisory"}],
    }


def _setup():
    arena = active_arena("ux25-scenario")
    operator, agent = client("operator"), client("agent")
    bind(operator, arena, agent, stance="attacker")
    return arena, operator, agent


def test_agent_reports_with_a_writeup_and_completes_it():
    arena, operator, agent = _setup()
    digest = _tx(arena)
    body = complete(digest)
    impact = body.pop("impact")
    r = agent.post(f"/arenas/{arena}/findings", json={
        "title": "Export runs .jspf", "cwe": "CWE-94", "node": "victim",
        "transaction_digests": [digest], "writeup": body})
    assert r.status_code == 200, r.text
    fid = r.json()["finding_id"]
    path = f"/arenas/{arena}/findings/{fid}/writeup"
    view = agent.get(path).json()
    assert view["schema"] == "nidavellir.finding-writeup.v1"
    assert view["origin"]["summary"] == "agent" and "impact" not in view["sections"]
    checks = {c["id"]: c for c in view["readiness"]["checks"]}
    assert "verified" not in checks  # outcomes stay undisclosed to agents
    assert checks["impact"]["ok"] is False and view["readiness"]["ready"] is False
    view = agent.post(path, json={"patch": {"impact": impact}}).json()
    assert view["readiness"]["ready"] is True, view["readiness"]["missing"]
    op_view = operator.get(path).json()
    op_checks = {c["id"]: c for c in op_view["readiness"]["checks"]}
    assert op_checks["verified"]["ok"] is False and op_view["readiness"]["ready"] is False


def test_operator_sections_win_and_only_the_reporter_writes():
    arena, operator, agent = _setup()
    fid = agent.post(f"/arenas/{arena}/findings", json={
        "title": "t", "writeup": {"impact": "agent text"}}).json()["finding_id"]
    path = f"/arenas/{arena}/findings/{fid}/writeup"
    other = client("agent")
    bind(operator, arena, other, stance="attacker")
    assert other.post(path, json={"patch": {"impact": "x"}}).status_code == 403
    assert other.get(path).status_code == 403
    assert client("agent").get(path).status_code == 403  # not bound
    view = operator.post(path, json={"patch": {"impact": "operator text"}}).json()
    assert view["origin"]["impact"] == "operator" and view["updated"]["role"] == "operator"
    r = agent.post(path, json={"patch": {"impact": "again", "remediation": "fix"}})
    assert r.status_code == 409 and r.json()["detail"]["sections"] == ["impact"]
    operator.post(path, json={"patch": {"impact": None}})  # releases the section
    view = agent.post(path, json={"patch": {"impact": "agent again"}}).json()
    assert view["sections"]["impact"] == "agent again" and view["origin"]["impact"] == "agent"
    seen = agent.get(f"/deployments/{arena}/events").json()["events"]
    assert not [e for e in seen if e["type"] == "finding_writeup"]


def test_shapes_are_checked_and_every_problem_listed():
    arena, operator, agent = _setup()
    bad = {"unknown": 1, "cwes": [{"id": "94", "name": "x"}],
           "references": [{"url": "http://plain.example"}, {"url": "https://10.0.0.1/a"}],
           "impact": "x" * 1201, "attack_type": "telepathy",
           "reproduction": {"steps": [{"action": "a", "evidence": ["sha256:" + "0" * 64]}]}}
    r = agent.post(f"/arenas/{arena}/findings", json={"title": "t", "writeup": bad})
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert len(errors) >= 6 and any("unknown section" in e for e in errors)
    r = agent.post(f"/arenas/{arena}/findings", json={"title": "t", "writeup": {
        "reproduction": {"steps": [{"action": "a", "evidence": ["sha256:" + "0" * 64]}]}}})
    assert r.status_code == 422 and "not a record of this arena" in str(r.json())
    fid = agent.post(f"/arenas/{arena}/findings", json={"title": "t"}).json()["finding_id"]
    path = f"/arenas/{arena}/findings/{fid}/writeup"
    assert agent.post(path, json={"patch": {}}).status_code == 422
    assert agent.post(path, json={"impact": "x"}).status_code == 422  # not wrapped in patch
    assert operator.get(f"/arenas/{arena}/findings/000000000000/writeup").status_code == 404


def test_readiness_names_house_style_and_evidence_gaps():
    finding = {"http_transactions": [{"digest": "d"}], "severity": "high"}
    base = complete("sha256:" + "a" * 64)
    assert writeup.readiness(finding, base, verified=True)["ready"] is True

    def missing(**changes):
        sections = {**base, **changes}
        return " ".join(writeup.readiness(finding, sections, verified=True)["missing"])

    assert "keep it to two or three" in missing(impact="a\n\nb\n\nc\n\nd")
    assert "code fence without a language" in missing(description="Run:\n\n```\nid\n```")
    assert "one paragraph per line" in missing(remediation="first line\nsecond line")
    assert "references: 1 of at least 3" in missing(references=[{"url": "https://example.org/a"}])
    assert "OWASP" in missing(references=[{"url": f"https://example.org/{i}"} for i in range(3)])
    assert "credential" in missing(description="Login with password=hunter2hunter2")
    assert "cites its evidence" in missing(reproduction={**base["reproduction"], "steps": [
        {"action": "a", "evidence": []}]})
    assert "no captured HTTP exchange" in " ".join(
        writeup.readiness({}, base, verified=True)["missing"])
    assert "not verified" in " ".join(writeup.readiness(finding, base, verified=False)["missing"])


def test_report_renders_the_agent_writeup_with_origins():
    digest = "sha256:" + "b" * 64
    finding = {"finding_id": "f1", "title": "Export runs .jspf", "cwe": "CWE-94",
               "actor": "agent-1", "http_transactions": [
                   {"digest": digest, "method": "GET", "path": "/export/x.jspf", "status": 200}]}
    sections = complete(digest)
    view = {"sections": sections, "origin": {k: "agent" for k in sections} | {"remediation": "operator"},
            "readiness": writeup.readiness(finding, sections, verified=True)}
    report = finding_report.build(finding, view=view, validator="confirmed")
    by_key = {s["key"]: s for s in report["sections"]}
    assert by_key["impact"]["origin"] == "agent" and by_key["remediation"]["origin"] == "operator"
    assert by_key["reproduction"]["reproduction"]["steps"][0]["evidence"][0]["label"] == "E1"
    md = report["markdown"]
    assert "1. Request the exported file. (evidence E1)" in md
    assert "   - Expected: 200 with the marker" in md
    assert "- Authentication role: workplace author" in md
    assert "| Product | Example CMS |" in md and "E1 HTTP GET /export/x.jspf -> 200" in md
    cve = report["cve_request"]
    assert "[Affected product code base]\nExample CMS 22.0" in cve
    assert "[Attack vectors]\nRequest the exported file." in cve


def test_report_falls_back_to_the_record_when_nothing_is_written():
    report = finding_report.build(
        {"finding_id": "f2", "title": "Bare", "poc": "curl x", "path": "/a|b"},
        hypothesis={"preconditions": ["author"], "invariant": "Never execute exports."})
    by_key = {s["key"]: s for s in report["sections"]}
    assert by_key["impact"]["origin"] == "missing"
    assert by_key["description"]["origin"] == "derived"
    assert by_key["reproduction"]["code"] == "curl x"
    assert "| Affected assets | component: /a\\|b |" in report["markdown"]


def test_gateway_forwards_the_writeup_and_the_new_tools():
    from gateway import rest_client
    from gateway.stances import STANCE_TOOLS, Stance

    sent = []

    class Fake(rest_client.RestClient):
        def __init__(self):
            pass

        def _request(self, method, path, api_key, json=None, **_):
            sent.append((method, path, json))
            return {}

    Fake().report_finding("k", "a1", "t", writeup={"impact": "x"})
    Fake().update_finding_writeup("k", "a1", "f1", {"impact": "y"})
    Fake().get_finding_writeup("k", "a1", "f1")
    assert sent[0][2]["writeup"] == {"impact": "x"}
    assert sent[1] == ("POST", "/arenas/a1/findings/f1/writeup", {"patch": {"impact": "y"}})
    assert sent[2][:2] == ("GET", "/arenas/a1/findings/f1/writeup")
    assert {"get_finding_writeup", "update_finding_writeup"} <= STANCE_TOOLS[Stance.attacker]
