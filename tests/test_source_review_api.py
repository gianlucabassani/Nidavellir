"""UI-R4 slice 2: the six operator-only source review routes."""
import json
import subprocess
import types
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import source_review
from database import Database
from tests.test_source_review import VIEWS, _commit, _git, _guarded

BASE = "/research/review-sessions"
SUMMARY_KEYS = {
    "schema", "session_id", "name", "created_at", "actor", "repo_id", "repo_label",
    "commit_sha", "requested_ref", "path_scope", "snapshot_digest", "capture_state",
    "patterns", "complete", "unresolved", "fix_links"}
PATTERN_KEYS = {"pattern", "total_matches", "total_matches_complete", "retained_sites",
                "truncation_notes", "by_status", "by_classification", "by_review_state"}
SITE_KEYS = {"site_key", "file", "line", "status", "classification", "evidence",
             "evidence_clipped", "review", "review_history", "review_history_total",
             "fix_links_touching_file"}
REVIEW_KEYS = {"state", "note", "finding_id", "actor", "at"}


def _client(role, *, raise_server_exceptions=True):
    import api
    import auth

    key = auth.generate_api_key()
    name = f"{role}-source-review-{uuid4().hex[:8]}"
    Database().create_api_key(auth.hash_api_key(key), name=name, role=role)
    client = TestClient(api.app, raise_server_exceptions=raise_server_exceptions)
    client.headers["X-API-Key"] = key
    client.principal_name = name
    return client


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    import api
    import config

    monkeypatch.setattr(config, "SOURCE_REVIEW_SNAPSHOTS_DIR", tmp_path / "snapshots")
    root = tmp_path / "target"
    root.mkdir()
    _git(root, "init", "-q")
    _commit(root, {"src/documents/views.py": VIEWS}, "init")
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(root))
    monkeypatch.delenv("RESEARCH_REPO_LABEL", raising=False)
    # The worker is not running in tests: run the queued capture inline.
    monkeypatch.setattr(api, "capture_source_review", types.SimpleNamespace(
        delay=lambda session_id: source_review.run_capture(Database(), session_id)))
    return root


@pytest.fixture()
def operator():
    return _client("operator")


def _create(operator, **overrides):
    body = {"name": "review", "ref": "HEAD", "patterns": ["unscoped-queryset"], **overrides}
    response = operator.post(BASE, json=body)
    assert response.status_code == 202, response.text
    return response.json()


def _sites(operator, session_id, **params):
    response = operator.get(f"{BASE}/{session_id}/sites",
                            params={"pattern": "unscoped-queryset", **params})
    assert response.status_code == 200, response.text
    return response.json()


# --- access ------------------------------------------------------------------

def test_agent_keys_get_403_on_every_route(repo, operator):
    session = _create(operator)
    sid = session["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    agent = _client("agent")
    calls = [
        ("post", BASE, {"json": {"name": "x", "ref": "HEAD", "patterns": ["mutation-order"]}}),
        ("get", BASE, {}),
        ("get", f"{BASE}/{sid}", {}),
        ("get", f"{BASE}/{sid}/sites", {"params": {"pattern": "unscoped-queryset"}}),
        ("post", f"{BASE}/{sid}/sites/{key}/review", {"json": {"state": "in_review"}}),
        ("get", f"{BASE}/{sid}/fix-links/F1", {}),
    ]
    before = len(Database().list_events(limit=None))
    for method, url, kwargs in calls:
        assert getattr(agent, method)(url, **kwargs).status_code == 403, url
    # Unknown sessions are also 403 for an agent, never 404: no existence oracle.
    assert agent.get(f"{BASE}/{'0' * 32}").status_code == 403
    assert len(Database().list_events(limit=None)) == before
    unauthenticated = TestClient(__import__("api").app)
    assert unauthenticated.get(BASE).status_code in (401, 403)


def test_agents_cannot_read_source_review_events_from_the_feed(repo, operator):
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    operator.post(f"{BASE}/{sid}/sites/{key}/review",
                  json={"state": "dismissed", "note": "operator-only judgment text"})
    hidden = {source_review.SESSION_EVENT, source_review.START_EVENT,
              source_review.CAPTURE_EVENT, source_review.REVIEW_EVENT}
    agent = _client("agent")
    for kind in (None, *hidden):
        feed = agent.get("/events", params={"limit": 500, **({"type": kind} if kind else {})})
        # FR-04: the cross-arena feed is operator-only.
        assert feed.status_code == 403
        assert "operator-only judgment text" not in feed.text
    seen = {event["type"] for event in operator.get(
        "/events", params={"limit": 500}).json()["events"]}
    assert hidden <= seen


# --- create and summary ------------------------------------------------------

def test_create_returns_the_summary_shape_exactly(repo, operator, monkeypatch):
    monkeypatch.setenv("RESEARCH_REPO_LABEL", "paperless-ngx pinned")
    sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "tag", "v2.0")
    summary = _create(operator, ref="v2.0", name="Tagged review")
    assert set(summary) == SUMMARY_KEYS
    assert summary["schema"] == "nidavellir/source-review-session/v1"
    assert summary["requested_ref"] == "v2.0" and summary["commit_sha"] == sha
    assert summary["repo_label"] == "paperless-ngx pinned" and len(summary["repo_id"]) == 64
    assert summary["actor"] == operator.principal_name
    assert summary["capture_state"] == "complete" and summary["complete"] is True
    assert summary["snapshot_digest"].startswith("sha256:")
    assert summary["path_scope"] == list(source_review.DEFAULT_PATH_SCOPE)
    assert summary["fix_links"] == []
    assert summary["unresolved"] == [source_review.STANDING_NOTE]
    [pattern] = summary["patterns"]
    assert set(pattern) == PATTERN_KEYS
    assert pattern["total_matches"] == pattern["retained_sites"] == 2
    assert pattern["total_matches_complete"] is True
    assert pattern["by_status"] == {"uncovered": 2}
    assert pattern["by_classification"] == {"no-local-owner-check": 2}
    assert pattern["by_review_state"] == {
        "unreviewed": 2, "in_review": 0, "dismissed": 0, "candidate": 0}
    assert operator.get(f"{BASE}/{summary['session_id']}").json() == summary
    assert str(repo) not in json.dumps(summary)


def test_no_field_or_text_claims_absence_exhaustion_or_safety(repo, operator):
    summary = _create(operator, patterns=list(source_review.PATTERNS))
    page = _sites(operator, summary["session_id"])
    forbidden = ("safe", "secure", "absen", "exhaust", "verified", "no_vulnerab", "clean")

    def keys(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                yield key
                yield from keys(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from keys(inner)

    # Machine classifications such as "...-unverified" are values, not fields.
    for name in {*keys({**summary, "patterns": [dict.fromkeys(PATTERN_KEYS)]}), *SITE_KEYS,
                 *REVIEW_KEYS, *page}:
        assert not any(word in name.lower() for word in forbidden), name
    assert not {"safe", "verified"} & set(source_review.ALL_REVIEW_STATES)
    assert "not findings" in summary["unresolved"][-1]


def test_capturing_and_failed_sessions_say_so(repo, operator, monkeypatch, tmp_path):
    import api

    monkeypatch.setattr(api, "capture_source_review",
                        types.SimpleNamespace(delay=lambda session_id: None))
    pending = _create(operator)
    assert set(pending) == SUMMARY_KEYS
    assert pending["capture_state"] == "capturing" and pending["complete"] is False
    assert pending["snapshot_digest"] is None
    assert pending["patterns"][0]["total_matches"] is None
    assert "still being captured" in pending["unresolved"][0]
    sid = pending["session_id"]
    assert operator.get(f"{BASE}/{sid}/sites",
                        params={"pattern": "unscoped-queryset"}).status_code == 409

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(empty))
    source_review.run_capture(Database(), sid)
    failed = operator.get(f"{BASE}/{sid}").json()
    assert failed["capture_state"] == "failed" and failed["complete"] is False
    assert "repository-unavailable" in failed["unresolved"][0]
    assert operator.get(f"{BASE}/{sid}/sites",
                        params={"pattern": "unscoped-queryset"}).status_code == 409


def test_incomplete_scan_is_reported_as_a_lower_bound(repo, operator, monkeypatch):
    import research_code

    lines = "".join(f"    r{i} = Document.objects.get(pk={i})\n" for i in range(400))
    _commit(repo, {"src/documents/many.py": "def load():\n" + lines})
    monkeypatch.setattr(research_code, "MAX_SEARCH_BYTES", 4096)
    summary = _create(operator)
    assert summary["capture_state"] == "complete" and summary["complete"] is False
    assert summary["patterns"][0]["total_matches_complete"] is False
    assert "lower bound" in summary["unresolved"][0]
    assert summary["unresolved"][-1] == source_review.STANDING_NOTE
    listed = operator.get(BASE).json()["sessions"][0]
    assert listed["session_id"] == summary["session_id"] and listed["complete"] is False


@pytest.mark.parametrize("body", [
    {"name": "", "ref": "HEAD", "patterns": ["mutation-order"]},
    {"name": "x" * 121, "ref": "HEAD", "patterns": ["mutation-order"]},
    {"name": "x", "ref": "y" * 65, "patterns": ["mutation-order"]},
    {"name": "x", "ref": "no such ref!", "patterns": ["mutation-order"]},
    {"name": "x", "ref": "HEAD", "patterns": []},
    {"name": "x", "ref": "HEAD", "patterns": ["everything"]},
    {"name": "x", "ref": "HEAD", "patterns": ["mutation-order"], "path_scope": ["../x"]},
    {"name": "x", "ref": "HEAD", "patterns": ["mutation-order"],
     "path_scope": [f"p{i}/" for i in range(9)]},
    {"name": "x", "ref": "HEAD", "patterns": ["mutation-order"], "repo_label": "mine"},
    {"name": "x", "ref": "HEAD", "patterns": ["mutation-order"],
     "fix_links": [{"label": "l" * 33, "fix_ref": "HEAD", "affected_ref": "HEAD",
                    "fixed_ref": "HEAD"}]},
    {"name": "x", "ref": "HEAD", "patterns": ["mutation-order"],
     "fix_links": [{"label": "a", "fix_ref": "HEAD", "affected_ref": "HEAD",
                    "fixed_ref": "HEAD"}] * 17},
])
def test_invalid_create_requests_are_refused(repo, operator, body):
    before = len(Database().list_events(limit=None, types=(source_review.SESSION_EVENT,)))
    assert operator.post(BASE, json=body).status_code == 422
    assert len(Database().list_events(
        limit=None, types=(source_review.SESSION_EVENT,))) == before


def test_missing_checkout_refuses_new_sessions_but_keeps_old_ones(
        repo, operator, tmp_path, monkeypatch):
    summary = _create(operator)
    sid = summary["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(empty))
    refused = operator.post(BASE, json={"name": "x", "ref": "HEAD",
                                        "patterns": ["mutation-order"]})
    assert refused.status_code == 422
    audit = [event for event in Database().list_events(
        lab_id="research-code", limit=50, types=("research_code_lookup",))
        if event["actor"] == operator.principal_name]
    assert audit[0]["payload"] == {"tool": "review_session_create", "outcome": "failed",
                                   "status_code": 422}
    assert operator.get(f"{BASE}/{sid}").json() == summary
    assert len(_sites(operator, sid)["sites"]) == 2
    assert operator.post(f"{BASE}/{sid}/sites/{key}/review",
                         json={"state": "in_review"}).status_code == 200


def test_unqueued_capture_fails_the_session_instead_of_hanging(repo, operator, monkeypatch):
    import api

    def broken(session_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(api, "capture_source_review", types.SimpleNamespace(delay=broken))
    response = operator.post(BASE, json={"name": "x", "ref": "HEAD",
                                         "patterns": ["mutation-order"]})
    assert response.status_code == 503
    newest = operator.get(BASE).json()["sessions"][0]
    assert newest["capture_state"] == "failed"
    assert "enqueue-failed" in operator.get(
        f"{BASE}/{newest['session_id']}").json()["unresolved"][0]


# --- list --------------------------------------------------------------------

def test_session_list_pages_newest_first_by_event_cursor(repo, operator):
    created = [_create(operator, name=f"session {index}")["session_id"] for index in range(3)]
    first = operator.get(BASE, params={"limit": 2}).json()
    assert [item["session_id"] for item in first["sessions"]] == created[:0:-1]
    assert first["next_before"] is not None
    item = first["sessions"][0]
    assert set(item) == {"session_id", "name", "commit_sha", "repo_label", "created_at",
                         "actor", "capture_state", "complete", "review_progress"}
    assert item["review_progress"] == {"total_sites": 2, "by_review_state": {
        "unreviewed": 2, "in_review": 0, "dismissed": 0, "candidate": 0}}
    rest = operator.get(BASE, params={"limit": 2, "before": first["next_before"]}).json()
    assert rest["sessions"][0]["session_id"] == created[0]
    for bad in ({"limit": 0}, {"limit": 101}, {"before": 0}):
        assert operator.get(BASE, params=bad).status_code == 422


# --- sites -------------------------------------------------------------------

def _many(repo, count=137):
    lines = "".join(f"    r{i} = Document.objects.get(pk={i})\n" for i in range(count))
    _commit(repo, {"src/documents/many.py": "def load():\n" + lines})


def test_sites_page_shape_and_paging_reach_every_retained_site(repo, operator):
    _many(repo)
    summary = _create(operator)
    sid = summary["session_id"]
    page = _sites(operator, sid)
    assert set(page) == {"session_id", "pattern", "sites", "offset", "next_offset",
                         "filtered_total", "pattern_total", "snapshot_digest"}
    assert len(page["sites"]) == 50 and page["next_offset"] == 50
    assert page["filtered_total"] == page["pattern_total"] == 139
    assert page["snapshot_digest"] == summary["snapshot_digest"]
    site = page["sites"][0]
    assert set(site) == SITE_KEYS and set(site["review"]) == REVIEW_KEYS
    assert site["review"] == {"state": "unreviewed", "note": None, "finding_id": None,
                              "actor": None, "at": None}
    assert site["review_history"] == [] and site["fix_links_touching_file"] == []

    for limit in (50, 100, 7):
        keys, offset = [], 0
        while offset is not None:
            current = _sites(operator, sid, offset=offset, limit=limit)
            keys += [entry["site_key"] for entry in current["sites"]]
            offset = current["next_offset"]
        assert len(keys) == 139 == len(set(keys))
    assert _sites(operator, sid, offset=139)["sites"] == []
    assert _sites(operator, sid, offset=100, limit=100)["next_offset"] is None
    # Visiting again returns the same page: paging is over the frozen snapshot.
    assert _sites(operator, sid, offset=50) == _sites(operator, sid, offset=50)


def test_sites_filters(repo, operator):
    _many(repo, 20)
    _commit(repo, {"src/paperless/models.py": "ALL = Document.objects.all()\n"})
    sid = _create(operator)["session_id"]
    assert _sites(operator, sid)["filtered_total"] == 23
    prefixed = _sites(operator, sid, file_prefix="src/documents/many")
    assert prefixed["filtered_total"] == 20 and prefixed["pattern_total"] == 23
    manual = _sites(operator, sid, status="manual-review")
    assert [site["file"] for site in manual["sites"]] == ["src/paperless/models.py"]
    assert _sites(operator, sid, classification="framework-queryset-or-module-scope"
                  )["filtered_total"] == 1
    assert _sites(operator, sid, status="uncovered", file_prefix="src/paperless/"
                  )["filtered_total"] == 0
    key = manual["sites"][0]["site_key"]
    operator.post(f"{BASE}/{sid}/sites/{key}/review", json={"state": "in_review"})
    assert _sites(operator, sid, review_state="in_review")["filtered_total"] == 1
    assert _sites(operator, sid, review_state="unreviewed")["filtered_total"] == 22


@pytest.mark.parametrize("params,status", [
    ({}, 422), ({"pattern": "everything"}, 422), ({"pattern": "mutation-order"}, 422),
    ({"pattern": "unscoped-queryset", "limit": 101}, 422),
    ({"pattern": "unscoped-queryset", "limit": 0}, 422),
    ({"pattern": "unscoped-queryset", "offset": -1}, 422),
    ({"pattern": "unscoped-queryset", "review_state": "safe"}, 422),
    ({"pattern": "unscoped-queryset", "file_prefix": "x" * 257}, 422),
])
def test_invalid_site_queries(repo, operator, params, status):
    sid = _create(operator)["session_id"]
    assert operator.get(f"{BASE}/{sid}/sites", params=params).status_code == status


def test_unknown_or_malformed_ids_are_404(repo, operator):
    sid = _create(operator)["session_id"]
    for bad in ("0" * 32, "not-a-session", "A" * 32):
        assert operator.get(f"{BASE}/{bad}").status_code == 404
        assert operator.get(f"{BASE}/{bad}/sites",
                            params={"pattern": "unscoped-queryset"}).status_code == 404
        assert operator.post(f"{BASE}/{bad}/sites/{'a' * 64}/review",
                             json={"state": "in_review"}).status_code == 404
    for bad in ("a" * 64, "short", "A" * 64):
        assert operator.post(f"{BASE}/{sid}/sites/{bad}/review",
                             json={"state": "in_review"}).status_code == 404
    assert operator.get(f"{BASE}/{sid}/fix-links/F1").status_code == 404


# --- review state ------------------------------------------------------------

def test_review_states_append_and_the_newest_wins(repo, operator):
    summary = _create(operator)
    sid = summary["session_id"]
    first, second = _sites(operator, sid)["sites"]
    url = f"{BASE}/{sid}/sites/{first['site_key']}/review"

    started = operator.post(url, json={"state": "in_review"})
    assert started.status_code == 200, started.text
    assert set(started.json()) == {"session_id", "site_key", "review", "review_history",
                                   "review_history_total"}
    assert started.json()["review"]["state"] == "in_review"
    assert started.json()["review"]["note"] is None
    dismissed = operator.post(url, json={"state": "dismissed",
                                         "note": "  Filter is by primary key only.  "}).json()
    assert dismissed["review"]["note"] == "Filter is by primary key only."
    assert dismissed["review"]["actor"] == operator.principal_name
    assert [entry["state"] for entry in dismissed["review_history"]] == ["dismissed", "in_review"]
    assert dismissed["review_history_total"] == 2

    sites = _sites(operator, sid)["sites"]
    assert sites[0]["review"] == dismissed["review"]
    assert sites[0]["review_history"] == dismissed["review_history"]
    assert sites[1]["review"]["state"] == "unreviewed"
    # The machine fields are exactly what was captured.
    for before, after in zip((first, second), sites):
        for field in ("status", "classification", "evidence", "file", "line", "site_key"):
            assert before[field] == after[field]
    refreshed = operator.get(f"{BASE}/{sid}").json()
    assert refreshed["patterns"][0]["by_review_state"] == {
        "unreviewed": 1, "in_review": 0, "dismissed": 1, "candidate": 0}
    assert refreshed["snapshot_digest"] == summary["snapshot_digest"]
    assert refreshed["patterns"][0]["by_status"] == summary["patterns"][0]["by_status"]
    assert operator.get(BASE).json()["sessions"][0]["review_progress"]["by_review_state"] == {
        "unreviewed": 1, "in_review": 0, "dismissed": 1, "candidate": 0}

    events = Database().list_events(source_review.scope(sid), limit=None,
                                    types=(source_review.REVIEW_EVENT,))
    assert [event["payload"]["state"] for event in events] == ["dismissed", "in_review"]
    assert events[0]["payload"] == {
        "session_id": sid, "site_key": first["site_key"], "state": "dismissed",
        "note": "Filter is by primary key only.", "finding_id": None}
    assert first["evidence"] not in json.dumps(events)


@pytest.mark.parametrize("body", [
    {"state": "dismissed"},
    {"state": "dismissed", "note": ""},
    {"state": "dismissed", "note": "too short"},
    {"state": "dismissed", "note": "   9 chars     "},
    {"state": "unreviewed"},
    {"state": "safe"},
    {"state": "verified"},
    {},
    {"state": "in_review", "note": "x" * 2001},
    {"state": "in_review", "extra": True},
    {"state": "in_review", "finding_id": "0123456789ab"},
    {"state": "candidate", "finding_id": "0123456789ab"},
    {"state": "candidate", "finding_id": "not-an-id"},
])
def test_refused_reviews_append_nothing(repo, operator, body):
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    response = operator.post(f"{BASE}/{sid}/sites/{key}/review", json=body)
    assert response.status_code == 422, response.text
    assert Database().list_events(source_review.scope(sid), limit=None,
                                  types=(source_review.REVIEW_EVENT,)) == []
    assert _sites(operator, sid)["sites"][0]["review"]["state"] == "unreviewed"


def test_dismissal_with_a_ten_character_note_is_accepted(repo, operator):
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    response = operator.post(f"{BASE}/{sid}/sites/{key}/review",
                             json={"state": "dismissed", "note": "0123456789"})
    assert response.status_code == 200


def test_candidate_may_link_an_existing_finding(repo, operator):
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    url = f"{BASE}/{sid}/sites/{key}/review"
    assert operator.post(url, json={"state": "candidate"}).status_code == 200
    finding = uuid4().hex[:12]
    Database().record_event("some-arena", "finding", {"finding_id": finding}, actor="operator")
    linked = operator.post(url, json={"state": "candidate", "finding_id": finding,
                                      "note": "Probe planned"})
    assert linked.status_code == 200, linked.text
    assert linked.json()["review"]["finding_id"] == finding
    assert _sites(operator, sid, review_state="candidate")["sites"][0]["review"][
        "finding_id"] == finding


def test_review_history_is_bounded_in_the_page_but_counted(repo, operator):
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    for index in range(source_review.HISTORY_MAX + 3):
        operator.post(f"{BASE}/{sid}/sites/{key}/review",
                      json={"state": "in_review", "note": f"pass {index}"})
    site = _sites(operator, sid)["sites"][0]
    assert len(site["review_history"]) == source_review.HISTORY_MAX
    assert site["review_history_total"] == source_review.HISTORY_MAX + 3
    assert site["review_history"][0]["note"] == f"pass {source_review.HISTORY_MAX + 2}"


# --- fix links ---------------------------------------------------------------

def test_fix_link_detail_and_same_file_labels(repo, operator):
    affected = _git(repo, "rev-parse", "HEAD").strip()
    fixed = _commit(repo, {"src/documents/views.py": _guarded(3)}, "fix")
    _commit(repo, {"src/paperless/other.py": "def f():\n    return Document.objects.all()\n"})
    summary = _create(operator, fix_links=[{
        "label": "GHSA demo", "fix_ref": fixed, "affected_ref": affected,
        "fixed_ref": fixed, "advisory_id": "GHSA-xxxx"}])
    sid = summary["session_id"]
    assert summary["fix_links"] == [{
        "link_id": "F1", "label": "GHSA demo", "advisory_id": "GHSA-xxxx", "fix_ref": fixed,
        "affected_ref": affected, "fixed_ref": fixed, "counts_complete": True}]
    detail = operator.get(f"{BASE}/{sid}/fix-links/F1")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["counts_complete"] is True and body["requested_fix_ref"] == fixed
    assert body["snapshot_digest"] == summary["snapshot_digest"]
    assert body["fix_lookup"]["data"]["files_changed"] == ["src/documents/views.py"]
    assert body["layer_diff"]["data"]["files"]["src/documents/views.py"]["added"] == 3
    assert "repo" not in body["fix_lookup"]["provenance"]
    touching = {site["file"]: site["fix_links_touching_file"]
                for site in _sites(operator, sid)["sites"]}
    assert touching["src/documents/views.py"] == [{"link_id": "F1", "label": "GHSA demo"}]
    assert touching["src/paperless/other.py"] == []
    assert operator.get(f"{BASE}/{sid}/fix-links/F2").status_code == 404


def test_cut_fix_link_shows_incomplete_counts(repo, operator):
    affected = _git(repo, "rev-parse", "HEAD").strip()
    fixed = _commit(repo, {"src/documents/views.py": _guarded(1500)}, "large fix")
    summary = _create(operator, fix_links=[{
        "label": "large", "fix_ref": fixed, "affected_ref": affected, "fixed_ref": fixed}])
    assert summary["fix_links"][0]["counts_complete"] is False
    assert any("Fix link F1" in reason for reason in summary["unresolved"])
    body = operator.get(f"{BASE}/{summary['session_id']}/fix-links/F1").json()
    assert body["counts_complete"] is False
    assert body["layer_diff"]["truncation"]["truncated"] is True


# --- integrity and persistence ----------------------------------------------

def test_altered_snapshot_fails_every_read_and_write_closed(repo, operator, tmp_path):
    summary = _create(operator)
    sid = summary["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    payload = tmp_path / "snapshots" / summary["snapshot_digest"][7:] / "snapshot.json"
    original = payload.read_bytes()
    altered = bytearray(original)
    altered[len(altered) // 2] ^= 0x01
    payload.write_bytes(bytes(altered))

    for response in (
            operator.get(f"{BASE}/{sid}"),
            operator.get(f"{BASE}/{sid}/sites", params={"pattern": "unscoped-queryset"}),
            operator.post(f"{BASE}/{sid}/sites/{key}/review", json={"state": "in_review"}),
            operator.get(f"{BASE}/{sid}/fix-links/F1")):
        assert response.status_code == 409, response.text
        assert "integrity" in response.json()["detail"]
    assert Database().list_events(source_review.scope(sid), limit=None,
                                  types=(source_review.REVIEW_EVENT,)) == []
    # The list reads events only, so the damaged session is still visible there.
    assert operator.get(BASE).json()["sessions"][0]["session_id"] == sid
    payload.write_bytes(original)
    assert operator.get(f"{BASE}/{sid}").json() == summary


def test_state_survives_a_fresh_process_view(repo, operator):
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    operator.post(f"{BASE}/{sid}/sites/{key}/review",
                  json={"state": "dismissed", "note": "Covered by queryset filter."})
    before = (operator.get(f"{BASE}/{sid}").json(), _sites(operator, sid))
    other = _client("operator")  # another key, a new client, a new Database handle
    assert (other.get(f"{BASE}/{sid}").json(), _sites(other, sid)) == before
    assert source_review.session_summary(Database(), sid) == before[0]


def test_reviewing_changes_no_budget_or_arena_record(repo, operator):
    from sqlalchemy import func, select

    from models import BudgetAccount, BudgetAction, Deployment

    def counts():
        with Database()._session() as session:
            return [session.scalar(select(func.count()).select_from(model))
                    for model in (BudgetAccount, BudgetAction, Deployment)]

    before = counts()
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    operator.post(f"{BASE}/{sid}/sites/{key}/review", json={"state": "in_review"})
    operator.get(f"{BASE}/{sid}")
    assert counts() == before


def test_git_is_not_run_for_reads_of_a_stored_session(repo, operator, monkeypatch):
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]

    def forbidden(*args, **kwargs):
        raise AssertionError("a stored session must not touch the checkout")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert operator.get(f"{BASE}/{sid}").status_code == 200
    assert operator.get(BASE).status_code == 200
    assert len(_sites(operator, sid)["sites"]) == 2
    assert operator.post(f"{BASE}/{sid}/sites/{key}/review",
                         json={"state": "in_review"}).status_code == 200


# --- MCP tool against the real routes (slice 3) ------------------------------

def _gateway_ctx(client):
    from gateway.rest_client import RestClient
    from gateway.session import Session
    from gateway.stances import Stance
    from gateway.tools import GatewayContext

    class Transport:
        def request(self, method, url, headers=None, json=None, timeout=None):
            return client.request(method, url.removeprefix("http://orch"), headers=headers,
                                  json=json)

    return GatewayContext(client=RestClient("http://orch", http=Transport()),
                          session=Session(api_key=client.headers["X-API-Key"],
                                          stance=Stance.operator), trace_dir=None)


def test_mcp_tool_reads_the_same_summary_and_page_as_rest(repo, operator):
    from gateway import tools

    _many(repo, 60)
    sid = _create(operator)["session_id"]
    key = _sites(operator, sid)["sites"][0]["site_key"]
    operator.post(f"{BASE}/{sid}/sites/{key}/review",
                  json={"state": "dismissed", "note": "Covered by the queryset filter."})
    ctx = _gateway_ctx(operator)
    before = len(Database().list_events(limit=None))

    summary_only = tools.source_review_read(ctx, sid)
    assert summary_only == {"session": operator.get(f"{BASE}/{sid}").json(), "sites": None}
    out = tools.source_review_read(ctx, sid, pattern="unscoped-queryset", offset=50, limit=7,
                                   file_prefix="src/documents/")
    assert out["sites"] == _sites(operator, sid, offset=50, limit=7,
                                  file_prefix="src/documents/")
    assert len(out["sites"]["sites"]) == 7 and out["sites"]["next_offset"] == 57
    dismissed = tools.source_review_read(ctx, sid, pattern="unscoped-queryset",
                                         review_state="dismissed")["sites"]
    assert [site["site_key"] for site in dismissed["sites"]] == [key]
    assert dismissed["sites"][0]["status"] and dismissed["sites"][0]["classification"]
    # Paging through the tool reaches every retained site exactly once.
    keys, offset = [], 0
    while offset is not None:
        page = tools.source_review_read(ctx, sid, pattern="unscoped-queryset",
                                        offset=offset, limit=100)["sites"]
        keys += [site["site_key"] for site in page["sites"]]
        offset = page["next_offset"]
    assert len(keys) == 62 == len(set(keys))
    # Reading through the tool appends nothing: no audit event, no review state.
    assert len(Database().list_events(limit=None)) == before


def test_mcp_tool_with_an_agent_key_is_refused_by_the_service(repo, operator):
    from gateway import tools
    from gateway.rest_client import GatewayRestError

    sid = _create(operator)["session_id"]
    with pytest.raises(GatewayRestError, match="403"):
        tools.source_review_read(_gateway_ctx(_client("agent")), sid)
    with pytest.raises(GatewayRestError, match="404"):
        tools.source_review_read(_gateway_ctx(operator), "0" * 32)
