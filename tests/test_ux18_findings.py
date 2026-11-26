"""UX-18: findings carry an optional reporter severity, shown as a claim.

The orchestrator accepts one of five levels (or none), stores it on the finding
event, never uses it for matching or scoring, and rejects anything else. The
gateway forwards it only when set. Console projections are covered in
test_webui.py (UX-18 tests)."""
from tests.research_support import active_arena, client


def _payloads(operator, arena):
    events = operator.get(f"/deployments/{arena}/events").json()["events"]
    return [e["payload"] for e in events if e["type"] == "finding"]


def test_severity_is_stored_as_the_reporters_claim_and_validated():
    arena = active_arena("ux18-scenario")
    operator = client("operator")
    for level in ("critical", "high", "medium", "low", "info"):
        r = operator.post(f"/arenas/{arena}/findings/manual",
                          json={"title": f"{level} issue", "severity": level})
        assert r.status_code == 200, r.text
    r = operator.post(f"/arenas/{arena}/findings/manual", json={"title": "unrated"})
    assert r.status_code == 200
    stored = {p["title"]: p.get("severity") for p in _payloads(operator, arena)}
    assert stored["high issue"] == "high"
    assert stored["unrated"] is None
    for bad in ("CRITICAL", "severe", "", 5):
        r = operator.post(f"/arenas/{arena}/findings/manual",
                          json={"title": "bad", "severity": bad})
        assert r.status_code == 422, (bad, r.text)


def test_severity_does_not_change_matching_or_validation():
    arena = active_arena("ux18-scenario")
    operator = client("operator")
    for severity in (None, "critical"):
        body = {"title": "same finding", "cwe": "CWE-89", "node": "victim"}
        if severity:
            body["severity"] = severity
        assert operator.post(f"/arenas/{arena}/findings/manual", json=body).status_code == 200
    a, b = _payloads(operator, arena)
    for key in ("matched_vuln_id", "validation"):
        assert a.get(key) == b.get(key)


def test_gateway_forwards_severity_only_when_set():
    from gateway import rest_client

    sent = []

    class Fake(rest_client.RestClient):
        def __init__(self):
            pass

        def _request(self, method, path, api_key, json=None, **_):
            sent.append(json)
            return {"recorded": True}

    Fake().report_finding("k", "a1", "t", severity="high")
    Fake().report_finding("k", "a1", "t")
    assert sent[0]["severity"] == "high"
    assert "severity" not in sent[1]
