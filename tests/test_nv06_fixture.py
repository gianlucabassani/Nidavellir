"""NV-06 fixture shape errors are distinguishable (discovery affordance).

An absent X-Request-ID must never look like a wrong credential: each failing
shape clause answers with its own status, while nothing about the verdict
(whether A may read B's object) leaks. Socket-free: exercises the pure
classifier, not the HTTP server.
"""
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "nv06_authz_app",
    Path(__file__).resolve().parent.parent
    / "cyber-range/fixtures/nv06-authz/app.py")
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


def test_missing_actor_is_401():
    status, error = app.classify_request(None, "B", "abc123")
    assert status == 401
    assert "credential" in error


def test_unknown_owner_is_404():
    status, error = app.classify_request("A", "Z", "abc123")
    assert status == 404
    assert "object" in error


def test_missing_request_id_names_the_header():
    # The exact trial-3 failure: right endpoint, right token, no header.
    status, error = app.classify_request("A", "B", "")
    assert status == 400
    assert "X-Request-ID" in error


def test_malformed_request_id_is_400():
    for bad in ("has-hyphen", "with space", "x" * 65, "uniçode"):
        status, _ = app.classify_request("A", "B", bad)
        assert status == 400, bad


def test_valid_shape_passes_to_effect():
    assert app.classify_request("A", "B", "abc123") == (None, None)


# --- discoverable surface (index + schema) ------------------------------

def test_index_names_families_and_nothing_else():
    body = app.index_body()
    assert set(body["resources"]) == {"objects", "protected"}
    dumped = json.dumps(body).lower()
    assert "token" not in dumped and "disclos" not in dumped


def test_openapi_lists_both_families_without_contract():
    body = app.openapi_body()
    assert set(body["paths"]) == {"/objects/{owner}", "/protected/{owner}"}
    dumped = json.dumps(body)
    assert "X-Request" not in dumped and "Bearer" not in dumped
    assert "token" not in dumped.lower()


def test_route_dispatch():
    assert app.route("/health", 8080) == "health"
    assert app.route("/health", 8081) == "health"
    assert app.route("/", 8080) == "index"
    assert app.route("/openapi.json", 8080) == "openapi"
    assert app.route("/oracle/abc", 8081) == "oracle"
    assert app.route("/other", 8081) == "not_found"
    assert app.route("/", 9999) == "not_found"


def test_family_gate_still_404s_one_segment_and_wrong_family():
    assert app.route("/objects", 8080) == "not_found"  # one segment
    assert app.route("/api", 8080) == "not_found"  # wrong family
    assert app.route("/api/objects", 8080) == "not_found"  # three segments


def test_unknown_owner_reaches_shape_gate_distinctly():
    assert app.route("/objects/Z", 8080) == "object"
    status, error = app.classify_request("A", "Z", "abc123")
    assert status == 404 and "object" in error
