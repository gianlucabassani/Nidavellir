"""UI-R4 slice 1: frozen source review snapshots, site identity and capture state.

Hermetic: scratch git repositories, the test database and a per-test store.
"""
import json
import shutil
import subprocess
import typing

import pytest

import research_code
import source_review
from database import Database
from timeutil import db_now  # FR-08: DB timestamps are naive UTC


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@lab.invalid",
                             "-c", "user.name=lab", *args],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _commit(repo, files, message="change"):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


VIEWS = (
    "class DocumentView:\n"
    "    permission_classes = (IsAuthenticated,)\n"
    "    def get(self, request):\n"
    "        return Document.objects.filter(pk=1)\n"
    "    def post(self, request):\n"
    "        if request.user.is_superuser:\n"
    "            return Document.objects.all()\n"
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "SOURCE_REVIEW_SNAPSHOTS_DIR", tmp_path / "snapshots")
    return tmp_path / "snapshots"


@pytest.fixture()
def repo(tmp_path, monkeypatch, store):
    root = tmp_path / "target"
    root.mkdir()
    _git(root, "init", "-q")
    _commit(root, {"src/documents/views.py": VIEWS}, "init")
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(root))
    return root


def _session(db, **overrides):
    request = {"name": "review", "ref": "HEAD", "patterns": ["unscoped-queryset"],
               "actor": "operator", **overrides}
    return source_review.create_session(db, **request)


def _captured(db, **overrides):
    session = _session(db, **overrides)
    state = source_review.run_capture(db, session["session_id"])
    assert state["capture_state"] == "complete", state["capture"]
    return source_review.load_session_snapshot(db, session["session_id"])


# --- vocabulary and identity -------------------------------------------------

def test_pattern_vocabulary_matches_the_existing_query_contract():
    import api

    annotation = api.ResearchSiblingSearch.model_fields["pattern"].annotation
    assert typing.get_args(annotation) == source_review.PATTERNS


def test_site_key_is_stable_and_binds_every_identity_input():
    base = ("r" * 64, "a" * 40, "unscoped-queryset", "src/a.py", 7, "x = A.objects.all()")
    key = source_review.site_key(*base)
    assert key == source_review.site_key(*base) and len(key) == 64
    for index, other in enumerate(("s" * 64, "b" * 40, "mutation-order", "src/b.py", 8, "y")):
        changed = list(base)
        changed[index] = other
        assert source_review.site_key(*changed) != key
    # Field boundaries cannot be shifted between neighbours.
    assert source_review.site_key("r" * 64, "a" * 40, "p", "a", 1, "1x") != \
        source_review.site_key("r" * 64, "a" * 40, "p", "a1", 1, "x")


def test_site_keys_and_snapshot_digest_survive_moving_the_checkout(repo, tmp_path, monkeypatch):
    db = Database()
    first_session, first = _captured(db)
    moved = tmp_path / "moved-elsewhere"
    shutil.copytree(repo, moved)
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(moved))
    second_session, second = _captured(db, name="after the move")

    assert first_session["repo_id"] == second_session["repo_id"]
    assert first_session["session_id"] != second_session["session_id"]
    assert first == second
    assert first_session["capture"]["snapshot_digest"] == second_session["capture"]["snapshot_digest"]
    assert str(repo) not in json.dumps(first) and str(moved) not in json.dumps(second)
    keys = [site["site_key"] for site in first["patterns"][0]["sites"]]
    assert keys and len(set(keys)) == len(keys)


def test_site_key_changes_with_the_commit(repo):
    db = Database()
    _, before = _captured(db)
    _commit(repo, {"README": "unrelated\n"})
    _, after = _captured(db)
    old = {site["site_key"] for site in before["patterns"][0]["sites"]}
    new = {site["site_key"] for site in after["patterns"][0]["sites"]}
    assert old and new and not old & new


def test_session_records_resolved_sha_and_keeps_the_requested_ref_apart(repo):
    sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "tag", "v1.0")
    db = Database()
    session = _session(db, ref="v1.0", patterns=["mutation-order", "unscoped-queryset"])
    assert session["requested_ref"] == "v1.0" and session["commit_sha"] == sha
    assert session["patterns"] == ["unscoped-queryset", "mutation-order"]
    assert session["path_scope"] == list(source_review.DEFAULT_PATH_SCOPE)
    assert session["repo_shallow"] is False
    stored = source_review.get_session(db, session["session_id"])
    assert stored["capture_state"] == "capturing" and stored["capture"] is None
    assert stored["actor"] == "operator"


@pytest.mark.parametrize("overrides", [
    {"name": ""}, {"name": "x" * 121}, {"name": " padded "}, {"name": "a\nb"},
    {"patterns": []}, {"patterns": ["unknown"]},
    {"patterns": ["mutation-order", "mutation-order"]},
    {"ref": "--upload-pack=x"}, {"ref": "x" * 65},
    {"path_scope": ["../outside"]}, {"path_scope": ["/etc"]},
    {"path_scope": [f"p{i}/" for i in range(9)]},
    {"fix_links": [{"label": "a", "fix_ref": "HEAD", "affected_ref": "HEAD"}]},
    {"fix_links": [{"label": "a", "fix_ref": "HEAD", "affected_ref": "HEAD",
                    "fixed_ref": "HEAD", "extra": 1}]},
    {"fix_links": [{"label": "a", "fix_ref": "HEAD", "affected_ref": "HEAD", "fixed_ref": "HEAD"},
                   {"label": "a", "fix_ref": "HEAD", "affected_ref": "HEAD", "fixed_ref": "HEAD"}]},
    {"fix_links": [{"label": "a", "fix_ref": "HEAD", "affected_ref": "HEAD",
                    "fixed_ref": "HEAD"}] * 17},
])
def test_invalid_session_requests_are_refused_without_a_record(repo, overrides):
    db = Database()
    before = len(db.list_events(limit=None, types=(source_review.SESSION_EVENT,)))
    with pytest.raises(ValueError):
        _session(db, **overrides)
    assert len(db.list_events(limit=None, types=(source_review.SESSION_EVENT,))) == before


def test_unprovisioned_checkout_refuses_new_sessions(tmp_path, monkeypatch, store):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(empty))
    with pytest.raises(research_code.ResearchCodeError, match="not provisioned"):
        _session(Database())


# --- capture -----------------------------------------------------------------

def test_capture_follows_paging_to_the_end_without_loss_or_duplicates(repo):
    lines = "".join(f"    r{i} = Document.objects.get(pk={i})\n" for i in range(137))
    _commit(repo, {"src/documents/many.py": "def load():\n" + lines})
    session, snapshot = _captured(Database())
    pattern = snapshot["patterns"][0]
    assert pattern["total_matches"] == 139 == pattern["retained_sites"] == len(pattern["sites"])
    assert pattern["pages"] == 3 and pattern["total_matches_complete"] is True
    assert pattern["truncation_notes"] == []
    assert len({site["site_key"] for site in pattern["sites"]}) == 139
    assert source_review.pattern_complete(pattern)
    assert session["capture"]["complete"] is True
    assert session["capture"]["patterns"] == [{
        "pattern": "unscoped-queryset", "total_matches": 139,
        "total_matches_complete": True, "retained_sites": 139, "pages": 3}]
    # The paged sites are exactly what the existing query returns page by page.
    direct, offset = [], 0
    while offset is not None:
        page = research_code.sibling_search(repo, session["commit_sha"], "unscoped-queryset",
                                            session["path_scope"], offset=offset)["data"]
        direct += page["sites"]
        offset = page["next_offset"]
    assert [(s["file"], s["line"], s["status"], s["classification"], s["evidence"])
            for s in pattern["sites"]] == [
        (s["file"], s["line"], s["status"], s["classification"], s["evidence"]) for s in direct]


def test_default_query_shape_is_unchanged_by_the_clip_flag(repo):
    sha = _git(repo, "rev-parse", "HEAD").strip()
    plain = research_code.sibling_search(repo, sha, "unscoped-queryset")
    assert all("evidence_clipped" not in site for site in plain["data"]["sites"])
    marked = research_code.sibling_search(repo, sha, "unscoped-queryset", mark_clipped=True)
    assert [site["evidence_clipped"] for site in marked["data"]["sites"]] == [False, False]


def test_grep_cap_is_carried_as_a_lower_bound(repo, monkeypatch):
    lines = "".join(f"    r{i} = Document.objects.get(pk={i})\n" for i in range(400))
    _commit(repo, {"src/documents/many.py": "def load():\n" + lines})
    monkeypatch.setattr(research_code, "MAX_SEARCH_BYTES", 4096)
    session, snapshot = _captured(Database())
    pattern = snapshot["patterns"][0]
    assert pattern["total_matches_complete"] is False
    assert 0 < pattern["total_matches"] < 402
    assert pattern["retained_sites"] == pattern["total_matches"]
    assert "git grep byte cap" in pattern["truncation_notes"]
    assert "total_matches is a lower bound" in pattern["truncation_notes"]
    assert not source_review.pattern_complete(pattern)
    assert session["capture"]["complete"] is False
    assert session["capture"]["patterns"][0]["total_matches_complete"] is False


def test_oversized_source_is_retained_as_manual_review(repo, monkeypatch):
    _commit(repo, {"src/documents/big.py": "def f():\n    return Document.objects.all()\n"
                   + "# padding\n" * 400})
    monkeypatch.setattr(research_code, "MAX_FILE_BYTES", 1024)
    _, snapshot = _captured(Database())
    pattern = snapshot["patterns"][0]
    big = [site for site in pattern["sites"] if site["file"] == "src/documents/big.py"]
    assert [(site["status"], site["classification"]) for site in big] == [
        ("manual-review", "unparsed-source")]
    assert "source unavailable or exceeds file byte cap" in pattern["truncation_notes"]
    assert pattern["retained_sites"] == pattern["total_matches"] == 3


def test_clipped_evidence_is_flagged_per_site(repo):
    long_line = "    value = Document.objects.filter(" + "a=1, " * 60 + ")\n"
    _commit(repo, {"src/documents/wide.py": "def f():\n" + long_line})
    _, snapshot = _captured(Database())
    pattern = snapshot["patterns"][0]
    flags = {site["file"]: site["evidence_clipped"] for site in pattern["sites"]}
    assert flags == {"src/documents/views.py": False, "src/documents/wide.py": True}
    wide = next(site for site in pattern["sites"] if site["file"].endswith("wide.py"))
    assert len(wide["evidence"].encode()) <= 160
    assert "site evidence byte cap" in pattern["truncation_notes"]


def _guarded(count):
    return VIEWS + "".join(
        f"        if not request.user.has_perm('p{i}'):\n            raise PermissionDenied()\n"
        for i in range(count))


def test_fix_link_facts_are_stored_with_their_own_digests(repo):
    affected = _git(repo, "rev-parse", "HEAD").strip()
    fixed = _commit(repo, {"src/documents/views.py": _guarded(80)}, "fix")
    _git(repo, "tag", "fixed-1")
    session, snapshot = _captured(Database(), fix_links=[{
        "label": "GHSA demo", "fix_ref": fixed, "affected_ref": affected,
        "fixed_ref": "fixed-1", "advisory_id": "GHSA-xxxx"}])
    recorded = session["fix_links"][0]
    assert recorded["requested_fixed_ref"] == "fixed-1" and recorded["fixed_ref"] == fixed
    stored = snapshot["fix_links"][0]
    assert stored["counts_complete"] is True and stored["link_id"] == "F1"
    assert stored["fix_ref"] == stored["fixed_ref"] == fixed and stored["affected_ref"] == affected
    assert stored["fix_lookup"]["data"]["files_changed"] == ["src/documents/views.py"]
    assert stored["layer_diff"]["data"]["files"]["src/documents/views.py"]["added"] == 80
    for answer in (stored["fix_lookup"], stored["layer_diff"]):
        assert "repo" not in answer["provenance"]
        assert answer["provenance"]["repo_id"] == session["repo_id"]
        body = {key: value for key, value in answer.items() if key != "digest"}
        assert answer["digest"] == "sha256:" + research_code._digest(body)
    assert session["capture"]["fix_links"] == [{"link_id": "F1", "counts_complete": True}]


def test_cut_fix_link_diff_reports_incomplete_counts(repo):
    affected = _git(repo, "rev-parse", "HEAD").strip()
    # Larger than the 64 KiB git output cap, so the existing queries cut it.
    fixed = _commit(repo, {"src/documents/views.py": _guarded(1500)}, "large fix")
    session, snapshot = _captured(Database(), fix_links=[{
        "label": "large", "fix_ref": fixed, "affected_ref": affected, "fixed_ref": fixed}])
    stored = snapshot["fix_links"][0]
    assert stored["counts_complete"] is False
    assert stored["layer_diff"]["data"]["counts_complete"] is False
    assert stored["layer_diff"]["truncation"]["truncated"] is True
    assert stored["fix_lookup"]["truncation"]["truncated"] is True
    assert session["capture"]["fix_links"] == [{"link_id": "F1", "counts_complete": False}]


def test_fix_link_file_list_cut_to_fit_is_not_a_complete_count(repo):
    """The answer's byte cap can shorten the changed-file list of a wide fix."""
    affected = _git(repo, "rev-parse", "HEAD").strip()
    # Few Python files, but a file list that only fits the 64 KiB answer when cut.
    wide = {f"docs/{'n' * 180}-{index:04d}.txt": "x\n" for index in range(330)}
    fixed = _commit(repo, {"src/documents/views.py": _guarded(3), **wide}, "wide fix")
    lookup = research_code.fix_lookup(repo, fixed)
    assert len(lookup["data"]["files_changed"]) < 331
    assert lookup["data"]["counts_complete"] is False and lookup["truncation"]["truncated"]
    session, snapshot = _captured(Database(), fix_links=[{
        "label": "wide", "fix_ref": fixed, "affected_ref": affected, "fixed_ref": fixed}])
    assert snapshot["fix_links"][0]["counts_complete"] is False
    assert session["capture"]["fix_links"] == [{"link_id": "F1", "counts_complete": False}]


# --- capture state -----------------------------------------------------------

def test_capture_state_moves_once_and_stays(repo, monkeypatch):
    db = Database()
    session = _session(db)
    sid = session["session_id"]
    assert source_review.get_session(db, sid)["capture_state"] == "capturing"
    with pytest.raises(source_review.SourceReviewError, match="capturing"):
        source_review.load_session_snapshot(db, sid)

    done = source_review.run_capture(db, sid)
    assert done["capture_state"] == "complete" and done["capture"]["duration_ms"] >= 0
    events = db.list_events(source_review.scope(sid), limit=None)
    assert [event["type"] for event in reversed(events)] == [
        "source_review_session", "source_review_capture_start", "source_review_capture"]
    assert events[0]["actor"] == "worker"

    # Redelivery neither searches again nor appends a second outcome.
    monkeypatch.setattr(source_review, "build_snapshot",
                        lambda *args: pytest.fail("terminal session was captured again"))
    again = source_review.run_capture(db, sid)
    assert again["capture"] == done["capture"]
    # Session, start marker, outcome: a repeat adds nothing, not even a start.
    assert len(db.list_events(source_review.scope(sid), limit=None)) == 3


def test_first_recorded_outcome_wins(repo):
    db = Database()
    sid = _session(db)["session_id"]
    source_review.run_capture(db, sid)
    db.record_event(source_review.scope(sid), source_review.CAPTURE_EVENT,
                    {"session_id": sid, "capture_state": "failed",
                     "reason_code": "internal-error"}, actor="worker")
    assert source_review.get_session(db, sid)["capture_state"] == "complete"


def test_capture_fails_visibly_when_the_checkout_is_gone(repo, tmp_path, monkeypatch):
    db = Database()
    sid = _session(db)["session_id"]
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(empty))
    failed = source_review.run_capture(db, sid)
    assert failed["capture_state"] == "failed"
    assert failed["capture"]["reason_code"] == "repository-unavailable"
    assert "snapshot_digest" not in failed["capture"]
    with pytest.raises(source_review.SourceReviewError, match="failed"):
        source_review.load_session_snapshot(db, sid)
    # A failed session is terminal; restoring the checkout does not revive it.
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(repo))
    assert source_review.run_capture(db, sid)["capture_state"] == "failed"


def test_capture_fails_when_another_repository_is_swapped_in(repo, tmp_path, monkeypatch):
    db = Database()
    sid = _session(db)["session_id"]
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    _commit(other, {"src/documents/views.py": VIEWS + "# other history\n"}, "unrelated root")
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(other))
    failed = source_review.run_capture(db, sid)
    assert failed["capture_state"] == "failed"
    assert failed["capture"]["reason_code"] in {"query-failed", "repository-changed"}


def test_query_and_internal_failures_record_a_closed_reason_code(repo, monkeypatch, tmp_path):
    db = Database()
    sid = _session(db)["session_id"]

    def refuse(*args, **kwargs):
        raise research_code.ResearchCodeError(f"git grep failed: secret detail {tmp_path}")

    monkeypatch.setattr(research_code, "sibling_search", refuse)
    failed = source_review.run_capture(db, sid)
    assert failed["capture"]["reason_code"] == "query-failed"
    assert "secret detail" not in json.dumps(db.list_events(source_review.scope(sid), limit=None))

    other = _session(db)["session_id"]

    def crash(*args, **kwargs):
        raise RuntimeError("unexpected secret detail")

    monkeypatch.setattr(research_code, "sibling_search", crash)
    with pytest.raises(RuntimeError):
        source_review.run_capture(db, other)
    state = source_review.get_session(db, other)
    assert state["capture_state"] == "failed"
    assert state["capture"]["reason_code"] == "internal-error"
    assert "secret detail" not in json.dumps(db.list_events(source_review.scope(other), limit=None))


def test_snapshot_over_the_size_cap_fails_instead_of_shrinking(repo, monkeypatch, store):
    import config

    monkeypatch.setattr(config, "SOURCE_REVIEW_SNAPSHOT_MAX_BYTES", 64)
    db = Database()
    failed = source_review.run_capture(db, _session(db)["session_id"])
    assert failed["capture"]["reason_code"] == "snapshot-too-large"
    assert not any(store.glob("*/snapshot.json"))


def test_full_store_fails_the_capture(repo, monkeypatch):
    import config

    monkeypatch.setattr(config, "SOURCE_REVIEW_STORE_MAX_BYTES", 64)
    db = Database()
    failed = source_review.run_capture(db, _session(db)["session_id"])
    assert failed["capture"]["reason_code"] == "store-full"


def test_worker_task_runs_the_capture(repo):
    import tasks

    db = Database()
    sid = _session(db)["session_id"]
    assert tasks.capture_source_review.acks_late is True
    assert tasks.capture_source_review.run(sid) == {"session_id": sid, "capture_state": "complete"}
    assert source_review.get_session(db, sid)["capture_state"] == "complete"


def test_unknown_or_malformed_session_ids(repo):
    db = Database()
    assert source_review.get_session(db, "0" * 32) is None
    with pytest.raises(source_review.SourceReviewError, match="not found"):
        source_review.run_capture(db, "0" * 32)
    for bad in ("", "../x", "A" * 32, "0" * 31, None):
        with pytest.raises(source_review.SourceReviewError, match="invalid"):
            source_review.get_session(db, bad)


# --- integrity ---------------------------------------------------------------

def _stored_files(store, session):
    root = store / session["capture"]["snapshot_digest"].removeprefix("sha256:")
    return root / "snapshot.json", root / "manifest.json"


def test_altering_one_byte_of_the_snapshot_fails_closed(repo, store):
    db = Database()
    session, snapshot = _captured(db)
    sid = session["session_id"]
    payload, _ = _stored_files(store, session)
    original = payload.read_bytes()
    assert json.loads(original) == snapshot

    for position in (0, len(original) // 2, len(original) - 1):
        altered = bytearray(original)
        altered[position] ^= 0x01
        payload.write_bytes(bytes(altered))
        with pytest.raises(source_review.SourceReviewIntegrityError, match="integrity"):
            source_review.load_session_snapshot(db, sid)
    # A still-valid JSON edit of the same length is refused as well.
    payload.write_bytes(original.replace(b"views.py", b"viewz.py", 1))
    with pytest.raises(source_review.SourceReviewIntegrityError):
        source_review.load_session_snapshot(db, sid)
    # Capturing the same inventory again must not repair or overwrite it.
    repeat = source_review.run_capture(db, _session(db)["session_id"])
    assert repeat["capture"]["reason_code"] == "integrity"
    assert payload.read_bytes() != original

    payload.write_bytes(original)
    assert source_review.load_session_snapshot(db, sid)[1] == snapshot


def test_truncated_missing_or_relabelled_snapshot_fails_closed(repo, store):
    db = Database()
    session, _ = _captured(db)
    sid = session["session_id"]
    payload, manifest = _stored_files(store, session)
    original, described = payload.read_bytes(), manifest.read_bytes()

    payload.write_bytes(original[:-1])
    with pytest.raises(source_review.SourceReviewIntegrityError):
        source_review.load_session_snapshot(db, sid)
    payload.write_bytes(original)

    manifest.write_text(json.dumps({**json.loads(described), "digest": "sha256:" + "0" * 64}))
    with pytest.raises(source_review.SourceReviewIntegrityError):
        source_review.load_session_snapshot(db, sid)
    manifest.unlink()
    with pytest.raises(source_review.SourceReviewIntegrityError, match="missing"):
        source_review.load_session_snapshot(db, sid)
    manifest.write_bytes(described)

    payload.unlink()
    with pytest.raises(source_review.SourceReviewIntegrityError, match="missing"):
        source_review.load_session_snapshot(db, sid)
    for bad in ("sha256:../../etc", "0" * 64, "sha256:" + "A" * 64, None):
        with pytest.raises(source_review.SourceReviewIntegrityError, match="invalid"):
            source_review.load_snapshot(bad)


def test_interrupted_first_write_is_finished_not_overwritten(repo, store):
    db = Database()
    session, snapshot = _captured(db)
    payload, manifest = _stored_files(store, session)
    original = payload.read_bytes()
    manifest.unlink()
    assert source_review.store_snapshot(snapshot)["digest"] == session["capture"]["snapshot_digest"]
    assert payload.read_bytes() == original
    assert source_review.load_session_snapshot(db, session["session_id"])[1] == snapshot
    # A manifest is only finished for a body that still verifies.
    manifest.unlink()
    payload.write_bytes(original[:-1])
    with pytest.raises(source_review.SourceReviewIntegrityError):
        source_review.store_snapshot(snapshot)
    assert not manifest.exists()


def test_snapshot_of_another_target_is_refused(repo, store):
    db = Database()
    session, snapshot = _captured(db)
    foreign = source_review.store_snapshot({**snapshot, "commit_sha": "f" * 40})
    db.record_event(source_review.scope("1" * 32), source_review.SESSION_EVENT,
                    {**{key: session[key] for key in (
                        "name", "requested_ref", "commit_sha", "repo_id", "repo_shallow",
                        "patterns", "path_scope", "fix_links")}, "session_id": "1" * 32},
                    actor="operator")
    db.record_event(source_review.scope("1" * 32), source_review.CAPTURE_EVENT,
                    {"session_id": "1" * 32, "capture_state": "complete",
                     "snapshot_digest": foreign["digest"]}, actor="worker")
    with pytest.raises(source_review.SourceReviewIntegrityError, match="another target"):
        source_review.load_session_snapshot(db, "1" * 32)


def test_stored_snapshot_survives_losing_the_checkout(repo, tmp_path, monkeypatch):
    db = Database()
    session, snapshot = _captured(db)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(empty))
    assert source_review.load_session_snapshot(db, session["session_id"])[1] == snapshot


def test_events_hold_digests_and_counts_not_source_text(repo):
    db = Database()
    session, snapshot = _captured(db)
    events = json.dumps(db.list_events(source_review.scope(session["session_id"]), limit=None))
    assert session["capture"]["snapshot_digest"] in events
    for site in snapshot["patterns"][0]["sites"]:
        assert site["evidence"] not in events and site["site_key"] not in events
    assert str(repo) not in events


# --- a capture whose worker died ----------------------------------------------

def _lose_worker(db, session_id):
    """What a worker killed mid-capture leaves behind: a start marker, no outcome."""
    db.record_event(source_review.scope(session_id), source_review.START_EVENT,
                    {"session_id": session_id}, actor="worker")


def _outcomes(db, session_id):
    return db.list_events(source_review.scope(session_id), limit=None,
                          types=(source_review.CAPTURE_EVENT,))


def test_lost_capture_is_recorded_as_failed_once(repo):
    from datetime import timedelta

    db = Database()
    lost = _session(db)["session_id"]
    _lose_worker(db, lost)
    running = _session(db, name="still within the time limit")["session_id"]
    _lose_worker(db, running)
    done = _captured(db)[0]["session_id"]
    now = db_now()
    expire = source_review.expire_lost_captures

    # Inside the window nothing is touched.
    assert expire(db, now=now, lost_after_seconds=2100, queued_after_seconds=21600) == []
    later = now + timedelta(seconds=2101)
    source_review.run_capture(db, running)  # this one finishes before the reaper looks

    # Other tests leave undecided sessions in the shared database; they may expire too.
    expired = expire(db, now=later, lost_after_seconds=2100, queued_after_seconds=21600)
    assert lost in expired and running not in expired and done not in expired
    state = source_review.get_session(db, lost)
    assert state["capture_state"] == "failed"
    assert state["capture"]["reason_code"] == "capture-lost"
    assert state["capture"]["waited_seconds"] >= 2100 and state["capture"]["starts"] == 1
    for untouched in (running, done):
        assert source_review.get_session(db, untouched)["capture_state"] == "complete"
    summary = source_review.session_summary(db, lost)
    assert summary["capture_state"] == "failed" and summary["complete"] is False

    # Repeating adds nothing, and a late or redelivered capture does not replace it.
    assert lost not in expire(db, now=later, lost_after_seconds=2100)
    assert source_review.run_capture(db, lost)["capture_state"] == "failed"
    outcomes = _outcomes(db, lost)
    assert len(outcomes) == 1 and outcomes[0]["actor"] == "reaper"
    with pytest.raises(source_review.SourceReviewError):
        source_review.load_session_snapshot(db, lost)


def test_queued_capture_is_not_failed_by_session_age(repo):
    """A capture waiting behind a long queue has no worker to lose yet."""
    from datetime import timedelta

    db = Database()
    queued = _session(db)["session_id"]
    now = db_now()
    expire = source_review.expire_lost_captures
    # Far past the lost-worker window, still inside the queue window: left alone.
    assert queued not in expire(db, now=now + timedelta(seconds=20000),
                                lost_after_seconds=2100, queued_after_seconds=21600)
    assert source_review.get_session(db, queued)["capture_state"] == "capturing"
    # A worker picks it up late; the window now runs from that start.
    assert source_review.run_capture(db, queued)["capture_state"] == "complete"

    # A task that never arrives at any worker is failed after the queue window.
    never = _session(db, name="task lost in the queue")["session_id"]
    assert never in expire(db, now=db_now() + timedelta(seconds=21601),
                           lost_after_seconds=2100, queued_after_seconds=21600)
    capture = source_review.get_session(db, never)["capture"]
    assert capture["reason_code"] == "capture-not-started" and capture["starts"] == 0


def test_capture_that_keeps_killing_its_worker_ends(repo):
    from datetime import timedelta

    db = Database()
    looping = _session(db)["session_id"]
    _lose_worker(db, looping)
    first = db_now()
    expire = source_review.expire_lost_captures
    # Redelivered and restarted just now: the latest start is fresh.
    assert looping not in expire(db, now=first + timedelta(seconds=10), lost_after_seconds=2100)
    # Still being restarted three windows after the first start: it ends.
    _lose_worker(db, looping)
    assert looping in expire(db, now=first + timedelta(seconds=6301), lost_after_seconds=2100)
    assert source_review.get_session(db, looping)["capture"]["starts"] == 2


def test_capture_outcome_is_recorded_once(repo):
    db = Database()
    sid = _session(db)["session_id"]
    scope = source_review.scope(sid)
    first = {"session_id": sid, "capture_state": "failed", "reason_code": "capture-lost"}
    assert db.record_event_once(scope, source_review.CAPTURE_EVENT, first, actor="reaper") is True
    assert db.record_event_once(scope, source_review.CAPTURE_EVENT,
                                {**first, "reason_code": "other"}, actor="worker") is False
    # The worker finishing afterwards changes nothing.
    assert source_review.run_capture(db, sid)["capture_state"] == "failed"
    assert [event["actor"] for event in _outcomes(db, sid)] == ["reaper"]
    # Other event types and other scopes are unaffected.
    assert db.record_event_once(scope, "source_review_probe", {}, actor="test") is True


def test_concurrent_outcomes_leave_exactly_one(repo):
    """Worker, duplicate delivery and reaper racing: one outcome, whatever the order.

    Runs on SQLite and, in the release gate, on PostgreSQL, where event ids are
    assigned at insert and could otherwise disagree with commit order.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    db = Database()
    for _ in range(5):
        sid = _session(db)["session_id"]
        scope, barrier = source_review.scope(sid), Barrier(8)

        def write(index, scope=scope, sid=sid, barrier=barrier):
            barrier.wait(5)
            return db.record_event_once(scope, source_review.CAPTURE_EVENT, {
                "session_id": sid, "capture_state": "failed" if index % 2 else "complete",
                "reason_code": f"writer-{index}"}, actor=f"writer-{index}")

        with ThreadPoolExecutor(max_workers=8) as pool:
            won = list(pool.map(write, range(8)))
        assert sum(won) == 1
        outcomes = _outcomes(db, sid)
        assert len(outcomes) == 1
        assert outcomes[0]["actor"] == f"writer-{won.index(True)}"
        state = source_review.get_session(db, sid)
        assert state["capture"]["reason_code"] == f"writer-{won.index(True)}"


def test_reaper_task_expires_lost_captures(repo, monkeypatch):
    import config
    import tasks

    db = Database()
    lost = _session(db)["session_id"]
    _lose_worker(db, lost)
    assert config.SOURCE_REVIEW_CAPTURE_LOST_SECONDS > 1860  # above the task's hard limit
    assert config.SOURCE_REVIEW_CAPTURE_QUEUED_SECONDS >= config.SOURCE_REVIEW_CAPTURE_LOST_SECONDS
    tasks.reap_labs()
    assert source_review.get_session(db, lost)["capture_state"] == "capturing"
    monkeypatch.setattr(config, "SOURCE_REVIEW_CAPTURE_LOST_SECONDS", 0)
    tasks.reap_labs()
    assert source_review.get_session(db, lost)["capture_state"] == "failed"

    # A failure in this step never stops arena reaping.
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(source_review, "expire_lost_captures", broken)
    assert "reaped" in tasks.reap_labs()
