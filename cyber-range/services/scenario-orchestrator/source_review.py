"""Source review sessions: frozen, content-addressed candidate inventories (UI-R4).

A session pins one repository identity and one commit SHA, then captures the
complete paged ``sibling_search`` result for each chosen pattern into a snapshot
that is written once and never edited. Events hold the snapshot digest and
metadata; the body lives in a non-arena, operator-only store (ADR-0011
amendment 2026-11-10).

A snapshot lists syntactic candidates. Nothing here states that a flaw exists
or is absent, and nothing here writes to the research checkout.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import config
import research_code

SNAPSHOT_SCHEMA = "nidavellir/source-review-snapshot/v1"
SCOPE_PREFIX = "source-review:"
SESSION_EVENT = "source_review_session"
CAPTURE_EVENT = "source_review_capture"
REVIEW_EVENT = "source_site_review"
START_EVENT = "source_review_capture_start"
SESSION_SCHEMA = "nidavellir/source-review-session/v1"
# No state says "safe" or "verified": review never settles what the code does.
UNREVIEWED = "unreviewed"
REVIEW_STATES = ("in_review", "dismissed", "candidate")
ALL_REVIEW_STATES = (UNREVIEWED, *REVIEW_STATES)
DISMISS_NOTE_MIN = 10
NOTE_MAX = 2000
HISTORY_MAX = 20
STANDING_NOTE = ("Statuses and classifications are syntactic candidates, not findings. "
                 "Review states record operator judgment and do not establish what the code does.")

# The closed sibling_search vocabulary, in the order a snapshot stores it.
PATTERNS = ("unscoped-queryset", "bare-auth-view", "bulk-permission",
            "half-composed-check", "unguarded-verb", "field-validation",
            "privilege-flags", "template-context", "mutation-order")
# sibling_search's own default, passed explicitly so the snapshot records the
# scope that was really searched.
DEFAULT_PATH_SCOPE = ("src/documents/", "src/paperless_mail/", "src/paperless/")

CAPTURING, COMPLETE, FAILED = "capturing", "complete", "failed"
MAX_FIX_LINKS = 16
# Capture follows next_offset itself, so this one note is resolved, not a cut.
_PAGE_NOTE = re.compile(r"site page capped at \d+; follow next_offset")
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
_LABEL = re.compile(r"[^\x00-\x1f\x7f]{1,32}\Z")


class SourceReviewError(ValueError):
    """A bounded, operator-actionable failure. ``code`` is safe to audit."""

    def __init__(self, message: str, code: str = "invalid-request"):
        super().__init__(message)
        self.code = code


class SourceReviewIntegrityError(SourceReviewError):
    """A stored snapshot is missing or does not match its address. Fail closed."""

    def __init__(self, message: str):
        super().__init__(message, "integrity")


def _canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- Identity ----------------------------------------------------------------

def repo_identity(repo: Path, commit_sha: str) -> dict:
    """``repo_id`` from the root commits reachable from the pinned commit.

    It does not depend on the checkout path, so moving the directory keeps the
    identity. A shallow checkout ends at different commits than a full one;
    that is reported, not hidden.
    """
    out = research_code.run_git(repo, "log", "--max-parents=0", "--format=%H", commit_sha)
    roots = sorted(set(out.split()))
    if out.truncated or not roots or not all(_SHA.fullmatch(root) for root in roots):
        raise SourceReviewError("repository root commits could not be listed",
                                "repository-unavailable")
    shallow = research_code.run_git(repo, "rev-parse", "--is-shallow-repository").strip()
    return {"repo_id": _sha256(_canonical(roots)), "repo_shallow": shallow != "false"}


def repo_label() -> str | None:
    """Operator's name for the checkout (RESEARCH_REPO_LABEL). Not part of repo_id."""
    label = os.getenv("RESEARCH_REPO_LABEL", "").strip()
    if not label:
        return None
    if len(label) > 64 or any(ord(char) < 32 or ord(char) == 127 for char in label):
        raise SourceReviewError("RESEARCH_REPO_LABEL must be at most 64 printable characters",
                                "repository-unavailable")
    return label


def site_key(repo_id: str, commit_sha: str, pattern: str, file: str, line: int,
             evidence: str) -> str:
    """Stable per-site identity; every input is fixed by the pinned commit."""
    return _sha256(_canonical([repo_id, commit_sha, pattern, file, line, evidence]))


# --- Content-addressed store -------------------------------------------------

def _snapshot_paths(digest: str) -> tuple[Path, Path]:
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise SourceReviewIntegrityError("invalid source review snapshot digest")
    root = config.SOURCE_REVIEW_SNAPSHOTS_DIR / digest.removeprefix("sha256:")
    return root / "snapshot.json", root / "manifest.json"


def _store_size() -> int:
    root = config.SOURCE_REVIEW_SNAPSHOTS_DIR
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def store_snapshot(snapshot: dict) -> dict:
    """Write one snapshot atomically under its own digest; return its manifest."""
    content = _canonical(snapshot)
    if len(content) > config.SOURCE_REVIEW_SNAPSHOT_MAX_BYTES:
        raise SourceReviewError("source review snapshot exceeds the configured limit",
                                "snapshot-too-large")
    digest = "sha256:" + _sha256(content)
    payload_path, manifest_path = _snapshot_paths(digest)
    manifest = {"schema": "nidavellir/source-review-snapshot-manifest/v1",
                "digest": digest, "bytes": len(content),
                "media_type": "application/json; charset=utf-8",
                "snapshot_schema": SNAPSHOT_SCHEMA}
    config.SOURCE_REVIEW_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with (config.SOURCE_REVIEW_SNAPSHOTS_DIR / ".store.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if payload_path.exists():
            # Same inventory captured before. Never overwrite the body: a
            # differing one at this address is corruption, not a newer version.
            if payload_path.read_bytes() != content:
                raise SourceReviewIntegrityError("source review snapshot integrity check failed")
            if manifest_path.exists():
                load_snapshot(digest)
                return manifest
            # An interrupted first write left the body without its manifest.
            # The manifest is derived from the verified body, so finish it.
        elif _store_size() + len(content) > config.SOURCE_REVIEW_STORE_MAX_BYTES:
            raise SourceReviewError("source review snapshot store has reached its capacity",
                                    "store-full")
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = []
        try:
            for target, body in ((payload_path, content), (manifest_path, _canonical(manifest))):
                if target.exists():
                    continue
                with tempfile.NamedTemporaryFile(dir=payload_path.parent, delete=False) as handle:
                    temporary.append(Path(handle.name))
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary[-1], target)
        finally:
            for path in temporary:
                path.unlink(missing_ok=True)
    return manifest


def load_snapshot(digest: str) -> dict:
    """Load a snapshot only if its bytes still hash to ``digest``."""
    payload_path, manifest_path = _snapshot_paths(digest)
    try:
        content = payload_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceReviewIntegrityError("source review snapshot is missing or unreadable") from exc
    if ("sha256:" + _sha256(content) != digest or not isinstance(manifest, dict)
            or manifest.get("digest") != digest or manifest.get("bytes") != len(content)):
        raise SourceReviewIntegrityError("source review snapshot integrity check failed")
    try:
        snapshot = json.loads(content)
    except ValueError as exc:  # Unreachable while SHA-256 holds; still fail closed.
        raise SourceReviewIntegrityError("source review snapshot integrity check failed") from exc
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise SourceReviewIntegrityError("source review snapshot has an unsupported schema")
    return snapshot


# --- Sessions ----------------------------------------------------------------

def scope(session_id: str) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise SourceReviewError("invalid source review session id")
    return SCOPE_PREFIX + session_id


def _check_fix_links(repo: Path, fix_links) -> list[dict]:
    links = list(fix_links or [])
    if len(links) > MAX_FIX_LINKS:
        raise SourceReviewError(f"at most {MAX_FIX_LINKS} fix links per session")
    resolved, labels = [], set()
    for index, link in enumerate(links, start=1):
        if not isinstance(link, dict) or set(link) - {
                "label", "fix_ref", "affected_ref", "fixed_ref", "advisory_id"}:
            raise SourceReviewError("invalid fix link")
        label, advisory = link.get("label"), link.get("advisory_id")
        if not isinstance(label, str) or not _LABEL.fullmatch(label) or label in labels:
            raise SourceReviewError("fix link labels must be unique, 1-32 printable characters")
        if advisory is not None and (not isinstance(advisory, str) or not _LABEL.fullmatch(advisory)):
            raise SourceReviewError("invalid fix link advisory id")
        labels.add(label)
        entry = {"link_id": f"F{index}", "label": label, "advisory_id": advisory}
        for field in ("fix_ref", "affected_ref", "fixed_ref"):
            value = link.get(field)
            if not isinstance(value, str) or len(value) > 64:
                raise SourceReviewError(f"invalid fix link {field}")
            # Requested and resolved refs are kept apart; only the SHA is used later.
            entry["requested_" + field] = value
            entry[field] = research_code.resolve_ref(repo, value)
        resolved.append(entry)
    return resolved


def create_session(db, *, name: str, ref: str, patterns, path_scope=None,
                   fix_links=None, actor: str) -> dict:
    """Pin identity and refs, then append the session record in state ``capturing``.

    The caller enqueues the capture task. Nothing is searched here.
    """
    if not isinstance(name, str) or not 1 <= len(name) <= 120 or name != name.strip() \
            or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise SourceReviewError("session name must be 1-120 printable characters")
    if not isinstance(ref, str) or not 1 <= len(ref) <= 64:
        raise SourceReviewError("invalid ref")
    chosen = list(patterns or [])
    if not chosen or len(set(chosen)) != len(chosen) or not set(chosen) <= set(PATTERNS):
        raise SourceReviewError("patterns must be 1-9 distinct values from the known vocabulary")
    if path_scope is not None and (not isinstance(path_scope, list) or not all(
            isinstance(path, str) and len(path) <= 256 for path in path_scope)):
        raise SourceReviewError("invalid path scope")
    repo = research_code.repo_root()
    scope_paths = research_code._check_paths(path_scope, list(DEFAULT_PATH_SCOPE))
    commit_sha = research_code.resolve_ref(repo, ref)
    session = {
        "session_id": uuid.uuid4().hex, "name": name,
        "requested_ref": ref, "commit_sha": commit_sha,
        **repo_identity(repo, commit_sha), "repo_label": repo_label(),
        "patterns": [pattern for pattern in PATTERNS if pattern in chosen],
        "path_scope": scope_paths,
        "fix_links": _check_fix_links(repo, fix_links),
    }
    db.record_event(scope(session["session_id"]), SESSION_EVENT, session, actor=actor)
    return session


def expire_lost_captures(db, *, now: datetime, lost_after_seconds: int,
                         queued_after_seconds: int | None = None) -> list[str]:
    """Fail sessions whose capture will never report an outcome.

    A worker killed outright (hard time limit, out of memory, host restart)
    records nothing, and the session would read ``capturing`` for ever. The
    worker records a start marker before it captures, so age is judged from
    there, not from session creation:

    - started, and the latest start is older than ``lost_after_seconds`` (above
      the task's hard limit): ``capture-lost``;
    - started three windows ago and still redelivered: ``capture-lost`` too, so
      a capture that kills its worker every time ends;
    - never started: still queued. Failed as ``capture-not-started`` only after
      ``queued_after_seconds``, in case the queued task itself was lost.

    The outcome is recorded once (``record_event_once``), so a capture finishing
    at the same moment either wins or is ignored, never both.
    """
    queued_after_seconds = max(queued_after_seconds or 0, lost_after_seconds)
    events = db.list_events(limit=None, types=(SESSION_EVENT, CAPTURE_EVENT, START_EVENT))
    decided = {event["lab_id"] for event in events if event["type"] == CAPTURE_EVENT}
    starts: dict[str, list[datetime]] = {}
    for event in events:
        if event["type"] == START_EVENT:
            starts.setdefault(event["lab_id"], []).append(datetime.fromisoformat(event["ts"]))
    expired = []
    for event in reversed(events):  # oldest first
        session_id = (event["payload"] or {}).get("session_id")
        if (event["type"] != SESSION_EVENT or event["lab_id"] in decided
                or event["lab_id"] != SCOPE_PREFIX + str(session_id)):
            continue
        started = starts.get(event["lab_id"])
        if started:
            since_last = (now - max(started)).total_seconds()
            since_first = (now - min(started)).total_seconds()
            if since_last < lost_after_seconds and since_first < 3 * lost_after_seconds:
                continue
            outcome = {"reason_code": "capture-lost", "waited_seconds": int(since_last),
                       "starts": len(started)}
        else:
            queued = (now - datetime.fromisoformat(event["ts"])).total_seconds()
            if queued < queued_after_seconds:
                continue
            outcome = {"reason_code": "capture-not-started", "waited_seconds": int(queued),
                       "starts": 0}
        if db.record_event_once(event["lab_id"], CAPTURE_EVENT, {
                "session_id": session_id, "capture_state": FAILED, **outcome}, actor="reaper"):
            expired.append(session_id)
    return expired


def get_session(db, session_id: str) -> dict | None:
    """Session record plus its derived capture state. History is never rewritten."""
    events = db.list_events(scope(session_id), limit=None, types=(SESSION_EVENT, CAPTURE_EVENT))
    created = [event for event in events if event["type"] == SESSION_EVENT]
    if not created:
        return None
    # Outcomes are recorded once. Records written before that rule may hold two;
    # the lowest id is then the outcome.
    outcomes = sorted((event for event in events if event["type"] == CAPTURE_EVENT),
                      key=lambda event: event["id"])
    first = created[-1]
    outcome = outcomes[0] if outcomes else None
    return {
        **first["payload"], "event_id": first["id"], "created_at": first["ts"],
        "actor": first["actor"],
        "capture_state": outcome["payload"]["capture_state"] if outcome else CAPTURING,
        "capture": {**outcome["payload"], "at": outcome["ts"]} if outcome else None,
    }


def load_session_snapshot(db, session_id: str) -> tuple[dict, dict]:
    """(session, verified snapshot) for a completed session; otherwise refuse."""
    session = get_session(db, session_id)
    if session is None:
        raise SourceReviewError("source review session was not found", "not-found")
    if session["capture_state"] != COMPLETE:
        raise SourceReviewError(f"source review capture is {session['capture_state']}",
                                "not-captured")
    snapshot = load_snapshot(session["capture"]["snapshot_digest"])
    if snapshot.get("repo_id") != session["repo_id"] or snapshot.get("commit_sha") != session["commit_sha"]:
        raise SourceReviewIntegrityError("source review snapshot belongs to another target")
    return session, snapshot


# --- Capture -----------------------------------------------------------------

def _capture_pattern(repo: Path, repo_id: str, commit_sha: str, pattern: str,
                     path_scope: list[str]) -> dict:
    sites, keys, notes = [], set(), set()
    total, complete, offset, pages = None, True, 0, 0
    while True:
        result = research_code.sibling_search(repo, commit_sha, pattern, path_scope,
                                              offset=offset, mark_clipped=True)
        data = result["data"]
        pages += 1
        if result["provenance"]["ref"] != commit_sha or (
                total is not None and data["total_matches"] != total):
            raise SourceReviewError("inventory changed while it was being captured",
                                    "repository-changed")
        total = data["total_matches"]
        complete = complete and data["total_matches_complete"] is True
        note = _PAGE_NOTE.sub("", result["truncation"]["note"])
        notes.update(piece.strip() for piece in note.split(";") if piece.strip())
        for site in data["sites"]:
            key = site_key(repo_id, commit_sha, pattern, site["file"], site["line"], site["evidence"])
            if key in keys:
                raise SourceReviewError("duplicate site in captured inventory", "query-failed")
            keys.add(key)
            sites.append({"site_key": key, "file": site["file"], "line": site["line"],
                          "status": site["status"], "classification": site["classification"],
                          "evidence": site["evidence"],
                          "evidence_clipped": site["evidence_clipped"]})
        following = data["next_offset"]
        if following is None:
            break
        if not data["sites"] or following != offset + len(data["sites"]):
            raise SourceReviewError("site paging made no progress", "query-failed")
        offset = following
    return {"pattern": pattern, "total_matches": total, "total_matches_complete": complete,
            "retained_sites": len(sites), "pages": pages,
            "truncation_notes": sorted(notes), "sites": sites}


def _stored_answer(result: dict, repo_id: str) -> dict:
    """Keep a research-code answer without the checkout's filesystem path."""
    body = {"data": result["data"], "truncation": result["truncation"],
            "provenance": {**{key: value for key, value in result["provenance"].items()
                              if key != "repo"}, "repo_id": repo_id}}
    return {**body, "digest": "sha256:" + _sha256(_canonical(body))}


def _capture_fix_link(repo: Path, repo_id: str, link: dict) -> dict:
    lookup = research_code.fix_lookup(repo, link["fix_ref"], link["advisory_id"])
    delta = research_code.layer_diff(repo, link["affected_ref"], link["fixed_ref"])
    return {**{key: link[key] for key in ("link_id", "label", "advisory_id", "fix_ref",
                                           "affected_ref", "fixed_ref")},
            "counts_complete": lookup["data"]["counts_complete"] is True
            and delta["data"]["counts_complete"] is True,
            "fix_lookup": _stored_answer(lookup, repo_id),
            "layer_diff": _stored_answer(delta, repo_id)}


def build_snapshot(repo: Path, session: dict) -> dict:
    """The frozen inventory. Holds no session id, name, time or path."""
    repo_id, commit_sha = session["repo_id"], session["commit_sha"]
    if research_code.resolve_ref(repo, commit_sha) != commit_sha or \
            repo_identity(repo, commit_sha)["repo_id"] != repo_id:
        raise SourceReviewError("research checkout no longer matches the session",
                                "repository-changed")
    return {
        "schema": SNAPSHOT_SCHEMA, "repo_id": repo_id, "commit_sha": commit_sha,
        "path_scope": list(session["path_scope"]),
        "patterns": [_capture_pattern(repo, repo_id, commit_sha, pattern,
                                      list(session["path_scope"]))
                     for pattern in session["patterns"]],
        "fix_links": [_capture_fix_link(repo, repo_id, link)
                      for link in session["fix_links"]],
    }


def pattern_complete(pattern: dict) -> bool:
    return pattern["total_matches_complete"] is True and \
        pattern["retained_sites"] == pattern["total_matches"]


def run_capture(db, session_id: str) -> dict:
    """Worker entry point: ``capturing`` -> ``complete`` | ``failed``, once.

    A terminal session is returned unchanged. The outcome event carries counts
    and a closed failure code, never source text or exception text.
    """
    session = get_session(db, session_id)
    if session is None:
        raise SourceReviewError("source review session was not found", "not-found")
    if session["capture_state"] != CAPTURING:
        return session
    # The reaper judges a lost capture from here, not from session creation.
    db.record_event(scope(session_id), START_EVENT, {"session_id": session_id}, actor="worker")
    started = time.monotonic()
    error = None
    try:
        try:
            repo = research_code.repo_root()
        except research_code.ResearchCodeError as exc:
            raise SourceReviewError(str(exc), "repository-unavailable") from exc
        snapshot = build_snapshot(repo, session)
        manifest = store_snapshot(snapshot)
        outcome = {
            "capture_state": COMPLETE, "snapshot_digest": manifest["digest"],
            "snapshot_bytes": manifest["bytes"],
            "complete": all(pattern_complete(pattern) for pattern in snapshot["patterns"]),
            "patterns": [{key: pattern[key] for key in (
                "pattern", "total_matches", "total_matches_complete", "retained_sites", "pages")}
                for pattern in snapshot["patterns"]],
            "fix_links": [{"link_id": link["link_id"], "counts_complete": link["counts_complete"]}
                          for link in snapshot["fix_links"]],
        }
    except SourceReviewError as exc:
        outcome = {"capture_state": FAILED, "reason_code": exc.code}
    except research_code.ResearchCodeError:
        outcome = {"capture_state": FAILED, "reason_code": "query-failed"}
    except Exception as exc:  # Record the failure, then let the worker log it.
        outcome = {"capture_state": FAILED, "reason_code": (
            "time-limit" if type(exc).__name__ == "SoftTimeLimitExceeded" else "internal-error")}
        error = exc
    # Recorded once: a duplicate delivery or the reaper may have decided already,
    # and then that earlier outcome stands.
    db.record_event_once(scope(session_id), CAPTURE_EVENT,
                         {"session_id": session_id, **outcome,
                          "duration_ms": int((time.monotonic() - started) * 1000)},
                         actor="worker")
    current = get_session(db, session_id)
    if error is not None:
        raise error
    return current


# --- Review state and read projections ---------------------------------------

_SITE_KEY = re.compile(r"[0-9a-f]{64}\Z")
_FINDING_ID = re.compile(r"[0-9a-f]{12}\Z")
_NO_REVIEW = {"state": UNREVIEWED, "note": None, "finding_id": None, "actor": None, "at": None}


def _review_history(db, session_id: str) -> dict[str, list[dict]]:
    """site_key -> review entries, newest first. Earlier entries are never rewritten."""
    history: dict[str, list[dict]] = {}
    for event in db.list_events(scope(session_id), limit=None, types=(REVIEW_EVENT,)):
        payload = event["payload"] or {}
        history.setdefault(payload.get("site_key"), []).append({
            "state": payload.get("state"), "note": payload.get("note"),
            "finding_id": payload.get("finding_id"), "actor": event["actor"], "at": event["ts"]})
    return history


def _state_counts(keys, history) -> dict:
    counts = dict.fromkeys(ALL_REVIEW_STATES, 0)
    for key in keys:
        counts[history[key][0]["state"] if key in history else UNREVIEWED] += 1
    return counts


def _tally(values) -> dict:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _required_session(db, session_id: str) -> dict:
    session = get_session(db, session_id)
    if session is None:
        raise SourceReviewError("source review session was not found", "not-found")
    return session


def session_summary(db, session_id: str) -> dict:
    """The session as stored, with every reason it may be incomplete.

    A completed session is read through its verified snapshot, so a damaged
    snapshot is an integrity error here rather than a plausible-looking answer.
    """
    session = _required_session(db, session_id)
    state, capture = session["capture_state"], session["capture"] or {}
    unresolved, patterns, links = [], [], []
    captured_links = {}
    if state == COMPLETE:
        _, snapshot = load_session_snapshot(db, session_id)
        history = _review_history(db, session_id)
        captured_links = {link["link_id"]: link for link in snapshot["fix_links"]}
        for pattern in snapshot["patterns"]:
            name, sites = pattern["pattern"], pattern["sites"]
            patterns.append({
                "pattern": name, "total_matches": pattern["total_matches"],
                "total_matches_complete": pattern["total_matches_complete"],
                "retained_sites": pattern["retained_sites"],
                "truncation_notes": pattern["truncation_notes"],
                "by_status": _tally(site["status"] for site in sites),
                "by_classification": _tally(site["classification"] for site in sites),
                "by_review_state": _state_counts([site["site_key"] for site in sites], history)})
            if pattern["total_matches_complete"] is not True:
                unresolved.append(f"{name}: the search output was cut, so "
                                  f"{pattern['total_matches']} matches is a lower bound.")
            if pattern["retained_sites"] != pattern["total_matches"]:
                unresolved.append(f"{name}: {pattern['retained_sites']} of "
                                  f"{pattern['total_matches']} matched sites were retained.")
        complete = all(pattern_complete(pattern) for pattern in snapshot["patterns"])
    else:
        complete = False
        patterns = [{"pattern": name, "total_matches": None, "total_matches_complete": None,
                     "retained_sites": None, "truncation_notes": [], "by_status": {},
                     "by_classification": {}, "by_review_state": {}}
                    for name in session["patterns"]]
        unresolved.append("The inventory is still being captured; no counts are available yet."
                          if state == CAPTURING else
                          f"The capture failed ({capture.get('reason_code', 'unknown')}); "
                          "this session has no inventory.")
    for link in session["fix_links"]:
        stored = captured_links.get(link["link_id"])
        counts_complete = stored["counts_complete"] if stored else None
        links.append({**{key: link[key] for key in (
            "link_id", "label", "advisory_id", "fix_ref", "affected_ref", "fixed_ref")},
            "counts_complete": counts_complete})
        if stored and counts_complete is not True:
            unresolved.append(f"Fix link {link['link_id']}: the patch output was cut, "
                              "so its counts are incomplete.")
    if session.get("repo_shallow"):
        unresolved.append("The checkout was shallow when captured; its repository identity "
                          "depends on the clone depth.")
    unresolved.append(STANDING_NOTE)
    return {
        "schema": SESSION_SCHEMA, "session_id": session["session_id"], "name": session["name"],
        "created_at": session["created_at"], "actor": session["actor"],
        "repo_id": session["repo_id"], "repo_label": session.get("repo_label"),
        "commit_sha": session["commit_sha"], "requested_ref": session["requested_ref"],
        "path_scope": session["path_scope"],
        "snapshot_digest": capture.get("snapshot_digest"), "capture_state": state,
        "patterns": patterns, "complete": complete, "unresolved": unresolved,
        "fix_links": links,
    }


def list_sessions(db, *, before: int | None = None, limit: int = 25) -> dict:
    """Newest first, paged by event id. Reads events only, never a snapshot."""
    events = [event for event in db.list_events(
        limit=limit + 1, types=(SESSION_EVENT,), before_id=before)]
    sessions = []
    for event in events[:limit]:
        payload = event["payload"] or {}
        session_id = payload.get("session_id")
        if event["lab_id"] != SCOPE_PREFIX + str(session_id):
            continue
        session = get_session(db, session_id)
        capture = session["capture"] or {}
        captured = session["capture_state"] == COMPLETE
        total = sum(pattern["retained_sites"] for pattern in capture.get("patterns") or [])
        history = _review_history(db, session_id) if captured else {}
        reviewed = _state_counts(history, history)
        reviewed[UNREVIEWED] = max(total - sum(reviewed[state] for state in REVIEW_STATES), 0)
        sessions.append({
            "session_id": session_id, "name": session["name"],
            "commit_sha": session["commit_sha"], "repo_label": session.get("repo_label"),
            "created_at": session["created_at"], "actor": session["actor"],
            "capture_state": session["capture_state"],
            "complete": capture.get("complete") is True if captured else False,
            "review_progress": {"total_sites": total, "by_review_state": reviewed}
            if captured else None})
    return {"sessions": sessions,
            "next_before": events[limit - 1]["id"] if len(events) > limit else None}


def _files_by_link(snapshot: dict) -> list[tuple[dict, set]]:
    touching = []
    for link in snapshot["fix_links"]:
        files = set(link["fix_lookup"]["data"].get("files_changed") or [])
        files.update(link["layer_diff"]["data"].get("files") or {})
        touching.append(({"link_id": link["link_id"], "label": link["label"]}, files))
    return touching


def sites_page(db, session_id: str, pattern: str, *, offset: int = 0, limit: int = 50,
               status: str | None = None, classification: str | None = None,
               review_state: str | None = None, file_prefix: str | None = None) -> dict:
    """One page of a frozen pattern inventory with each site's review state."""
    session, snapshot = load_session_snapshot(db, session_id)
    captured = next((entry for entry in snapshot["patterns"] if entry["pattern"] == pattern), None)
    if captured is None:
        raise SourceReviewError("pattern is not part of this session")
    if review_state is not None and review_state not in ALL_REVIEW_STATES:
        raise SourceReviewError("unknown review state")
    if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 100:
        raise SourceReviewError("invalid page")
    history = _review_history(db, session_id)
    links = _files_by_link(snapshot)

    def current(site):
        return history[site["site_key"]][0] if site["site_key"] in history else _NO_REVIEW

    selected = [site for site in captured["sites"]
                if (status is None or site["status"] == status)
                and (classification is None or site["classification"] == classification)
                and (file_prefix is None or site["file"].startswith(file_prefix))
                and (review_state is None or current(site)["state"] == review_state)]
    page = selected[offset:offset + limit]
    following = offset + len(page)
    return {
        "session_id": session["session_id"], "pattern": pattern,
        "sites": [{**site, "review": current(site),
                   "review_history": history.get(site["site_key"], [])[:HISTORY_MAX],
                   "review_history_total": len(history.get(site["site_key"], [])),
                   "fix_links_touching_file": [link for link, files in links
                                               if site["file"] in files]}
                  for site in page],
        "offset": offset, "next_offset": following if following < len(selected) else None,
        "filtered_total": len(selected), "pattern_total": captured["retained_sites"],
        "snapshot_digest": session["capture"]["snapshot_digest"],
    }


def fix_link(db, session_id: str, link_id: str) -> dict:
    """Stored patch facts for one declared fix link, with their truncation flags."""
    session, snapshot = load_session_snapshot(db, session_id)
    stored = next((link for link in snapshot["fix_links"] if link["link_id"] == link_id), None)
    declared = next((link for link in session["fix_links"] if link["link_id"] == link_id), None)
    if stored is None or declared is None:
        raise SourceReviewError("fix link was not found", "not-found")
    return {**stored,
            **{key: declared[key] for key in declared if key.startswith("requested_")},
            "session_id": session["session_id"],
            "snapshot_digest": session["capture"]["snapshot_digest"]}


def record_review(db, session_id: str, key: str, *, state: str, note: str = "",
                  finding_id: str | None = None, actor: str, finding_exists=None) -> dict:
    """Append one operator judgment for one site. Machine fields are untouched."""
    if state not in REVIEW_STATES:
        raise SourceReviewError("state must be in_review, dismissed or candidate")
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise SourceReviewError(f"note must be at most {NOTE_MAX} characters")
    if state == "dismissed" and len(note) < DISMISS_NOTE_MIN:
        raise SourceReviewError(
            f"dismissing a site needs a note of at least {DISMISS_NOTE_MIN} characters")
    if finding_id is not None:
        if state != "candidate":
            raise SourceReviewError("only a candidate may link a finding")
        if not isinstance(finding_id, str) or not _FINDING_ID.fullmatch(finding_id) \
                or finding_exists is None or not finding_exists(finding_id):
            raise SourceReviewError("unknown finding")
    if not isinstance(key, str) or not _SITE_KEY.fullmatch(key):
        raise SourceReviewError("site was not found", "not-found")
    _, snapshot = load_session_snapshot(db, session_id)
    if not any(site["site_key"] == key for pattern in snapshot["patterns"]
               for site in pattern["sites"]):
        raise SourceReviewError("site was not found", "not-found")
    db.record_event(scope(session_id), REVIEW_EVENT,
                    {"session_id": session_id, "site_key": key, "state": state,
                     "note": note or None, "finding_id": finding_id}, actor=actor)
    entries = _review_history(db, session_id)[key]
    return {"session_id": session_id, "site_key": key, "review": entries[0],
            "review_history": entries[:HISTORY_MAX], "review_history_total": len(entries)}
