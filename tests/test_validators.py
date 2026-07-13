"""
M2 deterministic-validator tests (ROADMAP M2 item 6, ADR-0009).

Covers the pure "perfect verification" framework (`validators.validate_finding`
/ `correlate_crash`) with injected effect functions — no arena, no network.
"""
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


def test_reflected_xss_confirmed_when_unescaped():
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/search", "param": "q"},
        http_fn=_echo_http(escape=False), nonce="nvABCDEF",
    )
    assert r.confirmed is True
    assert r.method == validators.REFLECTED_XSS


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


def test_headless_browser_confirms_execution():
    # Browser oracle says the payload executed -> confirmed without reflection check.
    r = validators.validate_finding(
        {"cwe": "CWE-79", "path": "/x", "param": "q"},
        http_fn=lambda p, q: {"status": 200, "body": ""},
        browser_fn=lambda path, params, nonce: True, nonce="nvABCDEF",
    )
    assert r.confirmed is True
    assert "executed" in r.explanation


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
    signals = [{"kind": "crash", "node": "victim", "summary": "victim exited 139"}]
    r = validators.correlate_crash("victim", signals)
    assert r.confirmed is True
    assert r.method == validators.CRASH_SIGNAL


def test_correlate_crash_ignores_other_nodes_and_benign_kinds():
    assert validators.correlate_crash("victim", [{"kind": "crash", "node": "db"}]).confirmed is None
    assert validators.correlate_crash(
        "victim", [{"kind": "unhandled_5xx", "node": "victim"}]
    ).confirmed is None  # 5xx alone isn't a fault-site crash


def test_validation_result_to_dict_is_bounded():
    r = validators.ValidationResult(True, "marker", "ok", "x" * 5000)
    d = r.to_dict()
    assert set(d) == {"confirmed", "method", "explanation", "evidence"}
    assert len(d["evidence"]) <= validators._MAX_EVIDENCE
