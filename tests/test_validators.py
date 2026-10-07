"""
M2 deterministic-validator tests (ROADMAP M2 item 6, ADR-0009).

Covers the pure "perfect verification" framework (`validators.validate_finding`
/ `correlate_crash`) with injected effect functions — no arena, no network.
The generic HTTP access-control probe is exercised against a loopback server.
"""
import http.server
import json
import subprocess
import sys
import threading

import pytest

import validators


# --- method selection --------------------------------------------------------

def test_explicit_manifest_validator_wins():
    assert validators.method_for({"cwe": "CWE-89"}, {"validator": "oast_callback"}) == "oast_callback"


def test_cwe_inference():
    assert validators.method_for({"cwe": "CWE-79"}, None) == validators.REFLECTED_XSS
    assert validators.method_for({"cwe": "89"}, None) == validators.MARKER  # normalized
    assert validators.method_for({"cwe": "CWE-918"}, None) == validators.OAST_CALLBACK


def test_unknown_cwe_is_unverifiable():
    assert validators.method_for({"cwe": "CWE-1234"}, None) == validators.NONE
    assert validators.method_for({}, None) == validators.NONE


# --- reflected XSS -----------------------------------------------------------

def _echo_http(escape=False):
    def http_fn(path, params):
        val = "".join(str(v) for v in (params or {}).values())
        if escape:
            val = val.replace("<", "&lt;").replace(">", "&gt;")
        return {"status": 200, "body": f"<html><body>hello {val}</body></html>"}
    return http_fn


def test_reflected_xss_unescaped_is_unknown_without_execution_oracle():
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/search", "param": "q"},
        http_fn=_echo_http(escape=False), nonce="nvABCDEF",
    )
    assert r.confirmed is None
    assert r.method == validators.REFLECTED_XSS
    assert "headless browser" in r.explanation


def test_reflected_xss_refuted_when_escaped():
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/search", "param": "q"},
        http_fn=_echo_http(escape=True), nonce="nvABCDEF",
    )
    assert r.confirmed is False  # reflected but escaped -> not executable


def test_reflected_xss_refuted_when_absent():
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/search", "param": "q"},
        http_fn=lambda p, q: {"status": 200, "body": "no echo here"}, nonce="nvABCDEF",
    )
    assert r.confirmed is False


def test_reflected_xss_unverifiable_without_path_or_probe():
    # No path -> can't probe -> unknown (None), not refuted.
    assert validators.validate_finding({"cwe": "CWE-79"}, http_fn=_echo_http()).confirmed is None
    # No http_fn -> unknown.
    assert validators.validate_finding({"cwe": "CWE-79", "path": "/x"}).confirmed is None


def test_probe_error_is_unknown_not_refuted():
    def boom(path, params):
        raise RuntimeError("target unreachable")
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/x", "param": "q"}, http_fn=boom, nonce="nvABCDEF"
    )
    assert r.confirmed is None
    assert r.to_dict()["verdict"] == "infrastructure_failure"


def test_headless_browser_confirms_execution():
    # Browser oracle says the payload executed -> confirmed without reflection check.
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/x", "param": "q"},
        http_fn=lambda p, q: {"status": 200, "body": ""},
        browser_fn=lambda path, params, nonce: True, nonce="nvABCDEF",
    )
    assert r.confirmed is True
    assert "executed" in r.explanation


def test_headless_browser_refutes_non_execution_even_when_reflected():
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/x", "param": "q"},
        http_fn=_echo_http(escape=False),
        browser_fn=lambda path, params, nonce: False,
        nonce="nvABCDEF",
    )
    assert r.confirmed is False
    assert "did not execute" in r.explanation


def test_headless_browser_receives_platform_owned_marker_payload():
    seen = {}

    def browser(path, params, nonce):
        seen.update(path=path, params=params, nonce=nonce)
        return True

    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/x", "param": "term", "payload": "ignored"},
        browser_fn=browser, nonce="nvABCDEF",
    )
    assert r.confirmed is True
    assert "data-nidavellir-xss" in seen["params"]["term"]
    assert "nvABCDEF" in seen["params"]["term"]


# --- marker (e.g. SQLi disclosing a planted secret) --------------------------

def test_marker_confirmed_and_refuted():
    vuln = {"validator": "marker", "marker": "SECRET_9f3a"}
    ok = validators.validate_finding(
        {"cwe": "CWE-89", "path": "/item", "param": "id", "payload": "1 OR 1=1"},
        vuln=vuln,
        http_fn=lambda p, q: {"status": 200, "body": "row: SECRET_9f3a end"},
    )
    assert ok.confirmed is True
    no = validators.validate_finding(
        {"cwe": "CWE-89", "path": "/item", "param": "id"}, vuln=vuln,
        http_fn=lambda p, q: {"status": 200, "body": "nothing"},
    )
    assert no.confirmed is False


def test_marker_unverifiable_without_marker():
    r = validators.validate_finding(
        {"cwe": "CWE-89", "path": "/item"}, vuln={"validator": "marker"},
        http_fn=lambda p, q: {"status": 200, "body": "x"},
    )
    assert r.confirmed is None


# --- OAST out-of-band --------------------------------------------------------

def test_oast_confirmed_and_refuted():
    hit = validators.validate_finding(
        {"cwe": "CWE-918", "oast_token": "tok123"}, oast_fn=lambda t: t == "tok123"
    )
    assert hit.confirmed is True
    miss = validators.validate_finding(
        {"cwe": "CWE-918", "oast_token": "tok123"}, oast_fn=lambda t: False
    )
    assert miss.confirmed is False


def test_oast_unverifiable_without_token():
    assert validators.validate_finding(
        {"cwe": "CWE-918"}, oast_fn=lambda t: True
    ).confirmed is None


# --- passive crash correlation ----------------------------------------------

def test_correlate_crash_confirms_on_matching_node():
    signals = [{"kind": "crash", "node": "victim", "summary": "victim exited 139",
                "ts": "2026-09-23T10:00:01"}]
    r = validators.correlate_crash("victim", signals, action_ts="2026-09-23T10:00:00")
    assert r.confirmed is True
    assert r.method == validators.CRASH_SIGNAL


def test_correlate_crash_ignores_other_nodes_and_benign_kinds():
    assert validators.correlate_crash("victim", [{"kind": "crash", "node": "db"}]).confirmed is None
    assert validators.correlate_crash(
        "victim", [{"kind": "unhandled_5xx", "node": "victim"}]
    ).confirmed is None  # 5xx alone isn't a fault-site crash


def test_crash_requires_linked_recent_action():
    signal = [{"kind": "crash", "node": "victim", "ts": "2026-09-23T10:05:00"}]
    assert validators.correlate_crash("victim", signal).confirmed is None
    assert validators.correlate_crash(
        "victim", signal, action_ts="2026-09-23T10:00:00"
    ).confirmed is None


def test_validation_result_to_dict_is_bounded():
    r = validators.ValidationResult(True, "marker", "ok", "x" * 5000)
    d = r.to_dict()
    assert set(d) == {"confirmed", "method", "explanation", "evidence", "verdict", "reason_code"}
    assert len(d["evidence"]) <= validators._MAX_EVIDENCE


def test_caller_marker_cannot_confirm():
    r = validators.validate_finding(
        {"cwe": "CWE-89", "path": "/item", "marker": "FAKE"},
        http_fn=lambda *_: {"status": 200, "body": "FAKE"},
    )
    assert r.confirmed is None


# --- generic HTTP access control ---------------------------------------------

def _http_acl_config(**overrides):
    config = {
        "actor": "B", "owner": "A", "base_url": "http://127.0.0.1:9",
        "actor_headers": {"Authorization": "Bearer actor"},
        "owner_headers": {"Authorization": "Bearer owner"},
        "action": {"method": "GET", "path": "/api/objects/restricted"},
        "control": {"method": "GET", "path": "/api/objects/shared"},
        "forbidden_marker": "restricted-marker",
    }
    config.update(overrides)
    return config


def test_http_access_control_config_rejects_unsafe_input():
    for bad in (
        _http_acl_config(base_url="file:///etc/passwd"),
        _http_acl_config(base_url="http://user:pass@127.0.0.1"),
        _http_acl_config(action={"method": "GET", "path": "api/x"}),
        _http_acl_config(action={"method": "TRACE", "path": "/x"}),
        _http_acl_config(forbidden_marker=""),
        _http_acl_config(extra="nope"),
        _http_acl_config(actor_headers={}),
        _http_acl_config(actor_headers={"X-Test": "a\nInjected: 1"}),
    ):
        with pytest.raises(ValueError):
            validators.normalize_http_access_control_config(bad)


def test_http_access_control_verdicts():
    action = {"digest": "sha256:abc"}
    confirmed = {"owner": {"status": 200, "marker": True},
                 "actor": {"status": 200, "marker": True},
                 "control": {"status": 200, "marker": False}}
    denied = {**confirmed, "actor": {"status": 403, "marker": False}}
    assert validators.validate_http_access_control(
        action, confirmed, actor="B", owner="A"
    ).to_dict()["verdict"] == "confirmed"
    assert validators.validate_http_access_control(
        action, denied, actor="B", owner="A"
    ).to_dict()["verdict"] == "refuted"
    assert validators.validate_http_access_control(
        action, {**confirmed, "owner": {"status": 200, "marker": False}},
        actor="B", owner="A"
    ).to_dict()["verdict"] == "infrastructure_failure"
    assert validators.validate_http_access_control(
        action, {**confirmed, "control": {"status": 403, "marker": False}},
        actor="B", owner="A"
    ).to_dict()["verdict"] == "infrastructure_failure"
    assert validators.validate_http_access_control(
        None, None, actor="B", owner="A"
    ).to_dict()["verdict"] == "inconclusive"
    assert validators.validate_http_access_control(
        action, None, actor="B", owner="A"
    ).to_dict()["verdict"] == "infrastructure_failure"


class _AclHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        auth = self.headers.get("Authorization")
        restricted = self.path.startswith("/api/objects/restricted")
        shared = self.path.startswith("/api/objects/shared")
        body = b"denied"
        if restricted and auth == "Bearer owner":
            body = b"restricted-marker"
        elif restricted and auth == "Bearer actor":
            body = b"restricted-marker"  # the vulnerable effect under test
        elif shared and auth == "Bearer actor":
            body = b"shared"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output clean
        return


def test_http_access_control_probe_runs_and_verdicts():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _AclHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = validators.normalize_http_access_control_config(
            _http_acl_config(base_url=f"http://127.0.0.1:{server.server_port}"))
        source = validators.http_access_control_probe_source(config)
        output = subprocess.run([sys.executable, "-c", source], capture_output=True,
                                text=True, timeout=30, check=True).stdout
        probe = json.loads(output)
        result = validators.validate_http_access_control(
            {"digest": "sha256:abc"}, probe, actor="B", owner="A")
        assert result.to_dict()["verdict"] == "confirmed"
        assert result.reason_code == "unauthorized_disclosure"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_authorization_effect_uses_observer_not_response_text():
    action = {"request_id": "request1", "response_body": "private-B"}
    control = {"actor": "B", "owner": "B", "status": 200, "control_ok": True}
    positive = {"request_id": "request1", "actor": "A", "owner": "B",
                "status": 200, "unauthorized_disclosure": True}
    denied = {**positive, "status": 403, "unauthorized_disclosure": False}
    assert validators.validate_authorization_effect(
        action, positive, control, actor="A", owner="B"
    ).to_dict()["verdict"] == "confirmed"
    assert validators.validate_authorization_effect(
        action, denied, control, actor="A", owner="B"
    ).to_dict()["verdict"] == "refuted"
    assert validators.validate_authorization_effect(
        None, None, None, actor="A", owner="B"
    ).to_dict()["verdict"] == "inconclusive"
    assert validators.validate_authorization_effect(
        action, None, control, actor="A", owner="B"
    ).to_dict()["verdict"] == "infrastructure_failure"
