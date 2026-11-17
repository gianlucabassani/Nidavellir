"""Research campaigns (NV-14, slice 1): groups of findings and their disclosure state.

A campaign is an operator-only record in the append-only event store, under the
non-arena scope ``campaign:<campaign_id>``. It holds NV-11 finding groups, keyed
by ``research_key``, so one flaw reported from many arenas or versions is one
row. It deploys nothing, executes nothing and uses no budget.

Two kinds of statement are kept apart and never merged:

- what the recorded evidence shows: the members' verdicts and NV-11's derived
  outcome, read live from the finding events;
- what the operator says about disclosure: an append-only state per group.

Design: NV-14 in TODO.md.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

import config
import redaction

SCOPE_PREFIX = "campaign:"
CAMPAIGN_SCHEMA = "nidavellir/research-campaign/v1"
CAMPAIGN_EVENT = "research_campaign"
FINDING_EVENT = "campaign_finding"
DISCLOSURE_EVENT = "campaign_disclosure"
BUNDLE_EVENT = "campaign_bundle"
EVENT_TYPES = (CAMPAIGN_EVENT, FINDING_EVENT, DISCLOSURE_EVENT, BUNDLE_EVENT)
BUNDLE_SCHEMA = "nidavellir/disclosure-bundle/v1"
ARTIFACT_KINDS = ("action", "observation", "control")
BUNDLES_SHOWN = 20

INTERNAL = "internal"
DISCLOSURE_STATES = (INTERNAL, "reported", "fixed", "published", "regressed")
NOTE_MIN = 10
NOTE_MAX = 2000
REFERENCE_MAX = 120
HISTORY_MAX = 20
MAX_FINDINGS = 200
STANDING_NOTE = ("Disclosure state is operator judgment. The outcome and the identity lists "
                 "are what the recorded evidence shows; a version that was not run is not "
                 "listed, and nothing here establishes that other versions are unaffected.")

_CAMPAIGN_ID = re.compile(r"\A[0-9a-f]{32}\Z")
_FINDING_ID = re.compile(r"\A[0-9a-f]{12}\Z")
_PRINTABLE = re.compile(r"\A[^\x00-\x1f\x7f]+\Z")
# Evidence can support or contradict only these two states.
_EVIDENCE_FOR = {"fixed": "disappeared_under_controls", "regressed": "still_observed"}


class CampaignError(ValueError):
    """A bounded, operator-actionable failure. ``code`` selects the HTTP status."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


class BundleIntegrityError(CampaignError):
    """A stored bundle is missing or no longer matches its content address."""

    def __init__(self, message: str):
        super().__init__(message, "integrity")


def scope(campaign_id: str) -> str:
    if not isinstance(campaign_id, str) or not _CAMPAIGN_ID.fullmatch(campaign_id):
        raise CampaignError("invalid campaign id")
    return SCOPE_PREFIX + campaign_id


def _text(value, name: str, limit: int, *, required: bool = False) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise CampaignError(f"{name} is required")
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise CampaignError(f"{name} must be at most {limit} characters")
    return value.strip()


def create_campaign(db, *, name: str, product: str, note: str | None = None,
                    actor: str) -> dict:
    name = _text(name, "name", 120, required=True)
    product = _text(product, "product", 120, required=True)
    if not _PRINTABLE.fullmatch(name) or not _PRINTABLE.fullmatch(product):
        raise CampaignError("name and product must be printable")
    campaign = {"schema": CAMPAIGN_SCHEMA, "campaign_id": uuid.uuid4().hex, "name": name,
                "product": product, "note": _text(note, "note", NOTE_MAX)}
    db.record_event(scope(campaign["campaign_id"]), CAMPAIGN_EVENT, campaign, actor=actor)
    return get_campaign(db, campaign["campaign_id"])


def get_campaign(db, campaign_id: str) -> dict | None:
    events = db.list_events(scope(campaign_id), limit=None, types=(CAMPAIGN_EVENT,))
    if not events:
        return None
    first = events[-1]
    return {**first["payload"], "created_at": first["ts"], "actor": first["actor"]}


def _required(db, campaign_id: str) -> dict:
    try:
        campaign = get_campaign(db, campaign_id)
    except CampaignError:
        campaign = None
    if campaign is None:
        raise CampaignError("campaign was not found", "not-found")
    return campaign


def _members(db, campaign_id: str) -> dict[str, dict]:
    """research_key -> the event that first added it, in the order added."""
    added: dict[str, dict] = {}
    events = db.list_events(scope(campaign_id), limit=None, types=(FINDING_EVENT,))
    for event in reversed(events):
        key = (event["payload"] or {}).get("research_key")
        if key and key not in added:
            added[key] = event
    return added


def add_finding(db, campaign_id: str, finding_id: str, *, actor: str, find_group) -> dict:
    """Add the whole NV-11 group that ``finding_id`` belongs to. Idempotent.

    ``find_group(finding_id)`` returns the finding-group view or None.
    """
    _required(db, campaign_id)
    if not isinstance(finding_id, str) or not _FINDING_ID.fullmatch(finding_id):
        raise CampaignError("finding_id must be a 12-hex finding id")
    group = find_group(finding_id)
    if group is None:
        raise CampaignError("finding was not found", "not-found")
    key = group["research_key"]
    members = _members(db, campaign_id)
    if key not in members and len(members) >= MAX_FINDINGS:
        raise CampaignError(f"a campaign holds at most {MAX_FINDINGS} finding groups")
    # One row per research_key: a second add of any member changes nothing. Two
    # operators adding at the same instant could both append; reads keep the first.
    added = key not in members
    if added:
        db.record_event(scope(campaign_id), FINDING_EVENT, {
            "campaign_id": campaign_id, "research_key": key, "added_as": finding_id},
            actor=actor)
    return {"added": added, "research_key": key}


def record_disclosure(db, campaign_id: str, research_key: str, *, state: str,
                      note: str | None = None, reference: str | None = None,
                      actor: str) -> dict:
    _required(db, campaign_id)
    if research_key not in _members(db, campaign_id):
        raise CampaignError("finding group is not in this campaign", "not-found")
    if state not in DISCLOSURE_STATES:
        raise CampaignError("state must be one of: " + ", ".join(DISCLOSURE_STATES))
    note = _text(note, "note", NOTE_MAX)
    reference = _text(reference, "reference", REFERENCE_MAX)
    if reference is not None and not _PRINTABLE.fullmatch(reference):
        raise CampaignError("reference must be printable")
    # Saying a fix did not hold, or taking a disclosure back, needs a reason.
    if state in ("regressed", INTERNAL) and len(note or "") < NOTE_MIN:
        raise CampaignError(f"{state} needs a note of at least {NOTE_MIN} characters")
    db.record_event(scope(campaign_id), DISCLOSURE_EVENT, {
        "campaign_id": campaign_id, "research_key": research_key, "state": state,
        "note": note, "reference": reference}, actor=actor)
    return _disclosure(db, campaign_id)[research_key]


def _disclosure(db, campaign_id: str) -> dict[str, dict]:
    """research_key -> current state and history (newest first)."""
    result: dict[str, dict] = {}
    for event in db.list_events(scope(campaign_id), limit=None, types=(DISCLOSURE_EVENT,)):
        payload = event["payload"] or {}
        entry = {"state": payload.get("state"), "note": payload.get("note"),
                 "reference": payload.get("reference"), "actor": event["actor"],
                 "at": event["ts"]}
        slot = result.setdefault(payload.get("research_key"), {
            "current": entry, "history": [], "total": 0})
        slot["total"] += 1
        if len(slot["history"]) < HISTORY_MAX:
            slot["history"].append(entry)
    return result


def _identity_lists(members: list[dict]) -> dict:
    """Members' whitelisted identities by verdict. Unknown stays unknown."""
    lists = {"affected": [], "not_observed_under_controls": [], "unknown": []}
    for member in members:
        identity = member.get("identity") or {}
        verdict = (member.get("verdict") or {}).get("verdict")
        entry = {"finding_id": member.get("finding_id"), "arena_id": member.get("arena_id"),
                 "identity": identity}
        if not identity.get("known"):
            lists["unknown"].append(entry)
        elif verdict == "confirmed":
            lists["affected"].append(entry)
        elif verdict == "refuted":
            lists["not_observed_under_controls"].append(entry)
        else:
            lists["unknown"].append(entry)
    return lists


def _target_key(member: dict):
    """What was actually run: the per-node image and source of a known identity.

    The recipe digest is not used: it differs between two arenas that run the
    very same image, so it cannot say that another version was tested.
    """
    identity = member.get("identity") or {}
    if not identity.get("known"):
        return None
    images = identity.get("images") or {}
    return tuple(sorted((str(node), str(item.get("image")), str(item.get("source_repo")),
                         str(item.get("source_ref"))) for node, item in images.items()))


def _support(state: str, group: dict | None) -> tuple[bool | None, str | None]:
    """Whether recorded evidence shows a ``fixed`` or ``regressed`` state, and why not.

    NV-11's outcome alone is not enough: it also reads ``disappeared_under_controls``
    when the refuting run repeated the same target. Evidence supports
    - ``fixed`` only if a confirmed run and a refuted run used different targets;
    - ``regressed`` only if a confirmed run on a different target was reported
      after a refuted run, i.e. something held and later did not.
    """
    expected = _EVIDENCE_FOR.get(state)
    if expected is None:
        return None, None
    outcome = ((group or {}).get("comparison") or {}).get("outcome")
    if outcome != expected:
        return False, (f"marked {state}, but the recorded evidence outcome is "
                       f"{outcome or 'unknown'}, not {expected}.")
    runs = [(member, _target_key(member), (member.get("verdict") or {}).get("verdict"))
            for member in (group or {}).get("members") or []]
    confirmed = [(m, key) for m, key, verdict in runs if verdict == "confirmed" and key]
    refuted = [(m, key) for m, key, verdict in runs if verdict == "refuted" and key]
    if state == "fixed":
        if any(r_key != c_key for _, r_key in refuted for _, c_key in confirmed):
            return True, None
        return False, ("marked fixed, but the refuting run used the same target as the "
                       "confirming run, so no other version was tested.")
    later = any(c_key != r_key and str(c.get("reported_at") or "") > str(r.get("reported_at") or "")
                for c, c_key in confirmed for r, r_key in refuted)
    if later:
        return True, None
    return False, ("marked regressed, but no confirmed run on a different target was "
                   "recorded after a refuted one.")


def campaign_summary(db, campaign_id: str, *, find_group) -> dict:
    campaign = _required(db, campaign_id)
    disclosure = _disclosure(db, campaign_id)
    bundles = _bundles(db, campaign_id)
    findings, unresolved = [], []
    by_state = {state: 0 for state in DISCLOSURE_STATES}
    for key, event in _members(db, campaign_id).items():
        group = find_group(key)
        recorded = disclosure.get(key)
        current = recorded["current"] if recorded else {
            "state": INTERNAL, "note": None, "reference": None, "actor": None, "at": None}
        by_state[current["state"]] += 1
        if group is None:
            # The finding events are gone (an archive was cleared). Say so; keep the row.
            findings.append({
                "research_key": key, "added_at": event["ts"], "added_by": event["actor"],
                "available": False, "title": None, "cwe": None, "members": [],
                "identities": _identity_lists([]), "comparison": None,
                "disclosure": current, "disclosure_history": recorded["history"] if recorded else [],
                "disclosure_history_total": recorded["total"] if recorded else 0,
                "state_supported_by_evidence": None,
                "bundles": bundles.get(key, {"shown": [], "total": 0})["shown"],
                "bundles_total": bundles.get(key, {"total": 0})["total"]})
            unresolved.append(f"{key}: its finding records are no longer available.")
            continue
        members = group["members"]
        reference = members[0] if members else {}
        outcome = (group.get("comparison") or {}).get("outcome")
        supported, why_not = _support(current["state"], group)
        findings.append({
            "research_key": key, "added_at": event["ts"], "added_by": event["actor"],
            "available": True, "title": reference.get("title"), "cwe": reference.get("cwe"),
            "members": members, "identities": _identity_lists(members),
            "comparison": group.get("comparison"), "disclosure": current,
            "disclosure_history": recorded["history"] if recorded else [],
            "disclosure_history_total": recorded["total"] if recorded else 0,
            "state_supported_by_evidence": supported,
            "bundles": bundles.get(key, {"shown": [], "total": 0})["shown"],
            "bundles_total": bundles.get(key, {"total": 0})["total"]})
        if supported is False:
            unresolved.append(f"{key}: {why_not}")
        if outcome in (None, "unknown", "inconclusive"):
            unresolved.append(f"{key}: the evidence outcome across versions is "
                              f"{outcome or 'unknown'}.")
    unresolved.append(STANDING_NOTE)
    return {**campaign, "findings": findings, "by_disclosure_state": by_state,
            "unresolved": unresolved}


def list_campaigns(db, *, before: int | None = None, limit: int = 25) -> dict:
    """Newest first, paged by event id."""
    events = [event for event in db.list_events(
        limit=limit + 1, types=(CAMPAIGN_EVENT,), before_id=before)]
    campaigns = []
    for event in events[:limit]:
        payload = event["payload"] or {}
        campaign_id = payload.get("campaign_id")
        if event["lab_id"] != SCOPE_PREFIX + str(campaign_id):
            continue
        campaigns.append({"campaign_id": campaign_id, "name": payload.get("name"),
                          "product": payload.get("product"), "created_at": event["ts"],
                          "actor": event["actor"],
                          "finding_groups": len(_members(db, campaign_id))})
    return {"campaigns": campaigns,
            "next_before": events[limit - 1]["id"] if len(events) > limit else None}


# --- Disclosure bundles (slice 2) -------------------------------------------
# A bundle is a file for the operator. It is built from an allowlist, stored
# under its own digest and never sent anywhere.

_DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_HEADER_SECRETS = re.compile(r"(?i)\b(authorization|cookie|set-cookie|x-api-key|proxy-authorization)\b")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{4,}")


def _canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def redact_deep(value, _key: str = ""):
    """The existing redaction pass, applied through nested evidence.

    Values under secret-looking keys and credential headers are masked whole;
    every other string goes through ``redaction.redact`` and loses bearer tokens.
    """
    if isinstance(value, dict):
        return {key: redact_deep(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_deep(item, _key) for item in value]
    if isinstance(value, str):
        if _HEADER_SECRETS.search(_key) or redaction.redact_mapping({_key: value})[_key] != value:
            return redaction.MASK
        return _BEARER.sub(lambda match: f"{match.group(1)} {redaction.MASK}",
                           redaction.redact(value))
    return value


def _bundle_paths(digest: str) -> tuple[Path, Path]:
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise BundleIntegrityError("invalid disclosure bundle digest")
    root = config.DISCLOSURE_BUNDLES_DIR / digest.removeprefix("sha256:")
    return root / "bundle.json", root / "manifest.json"


def store_bundle(bundle: dict) -> dict:
    """Write one bundle atomically under its own digest; return its manifest."""
    content = _canonical(bundle)
    if len(content) > config.DISCLOSURE_BUNDLE_MAX_BYTES:
        raise CampaignError("disclosure bundle exceeds the configured limit")
    digest = "sha256:" + _sha256(content)
    payload_path, manifest_path = _bundle_paths(digest)
    manifest = {"schema": "nidavellir/disclosure-bundle-manifest/v1", "digest": digest,
                "bytes": len(content), "media_type": "application/json; charset=utf-8",
                "bundle_schema": BUNDLE_SCHEMA}
    root = config.DISCLOSURE_BUNDLES_DIR
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".store.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if payload_path.exists():
            # The same state bundled before. A differing body here is corruption.
            if payload_path.read_bytes() != content:
                raise BundleIntegrityError("disclosure bundle integrity check failed")
        else:
            used = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
            if used + len(content) > config.DISCLOSURE_BUNDLE_STORE_MAX_BYTES:
                raise CampaignError("disclosure bundle store has reached its capacity")
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
    load_bundle(digest)
    return manifest


def load_bundle(digest: str) -> dict:
    """Load a bundle only if its bytes still hash to ``digest``."""
    return _load_bundle_snapshot(digest)[0]


def _load_bundle_snapshot(digest: str) -> tuple[dict, bytes]:
    """Parse and return the very same bytes whose digest was verified."""
    payload_path, manifest_path = _bundle_paths(digest)
    try:
        content = payload_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleIntegrityError("disclosure bundle is missing or unreadable") from exc
    if ("sha256:" + _sha256(content) != digest or not isinstance(manifest, dict)
            or manifest.get("digest") != digest or manifest.get("bytes") != len(content)):
        raise BundleIntegrityError("disclosure bundle integrity check failed")
    try:
        bundle = json.loads(content)
    except ValueError as exc:
        raise BundleIntegrityError("disclosure bundle integrity check failed") from exc
    if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
        raise BundleIntegrityError("disclosure bundle has an unsupported schema")
    return bundle, content


def _bundles(db, campaign_id: str) -> dict[str, dict]:
    """research_key -> recorded bundles, newest first."""
    result: dict[str, dict] = {}
    for event in db.list_events(scope(campaign_id), limit=None, types=(BUNDLE_EVENT,)):
        payload = event["payload"] or {}
        slot = result.setdefault(payload.get("research_key"), {"shown": [], "total": 0})
        slot["total"] += 1
        if len(slot["shown"]) < BUNDLES_SHOWN:
            slot["shown"].append({
                "bundle_digest": payload.get("bundle_digest"), "bytes": payload.get("bytes"),
                "include_poc": payload.get("include_poc"),
                "include_evidence": payload.get("include_evidence"),
                "unresolved_artifacts": payload.get("unresolved_artifacts"),
                "actor": event["actor"], "at": event["ts"]})
    return result


def build_bundle(db, campaign_id: str, research_key: str, *, include_poc: bool,
                 include_evidence: bool, find_group, find_poc, resolve_artifact) -> dict:
    """Assemble one group's bundle from an allowlist. Nothing else is copied.

    ``find_poc(finding_id)`` returns the reported PoC text or None.
    ``resolve_artifact(arena_id, digest)`` returns ``{"store": ..., "body": ...}``
    for a digest that still resolves in a live store, else None. ``body`` is
    present only for validation evidence; raw HTTP transactions are never copied.
    """
    campaign = _required(db, campaign_id)
    if research_key not in _members(db, campaign_id):
        raise CampaignError("finding group is not in this campaign", "not-found")
    group = find_group(research_key)
    if group is None or not group["members"]:
        raise CampaignError("the finding records of this group are no longer available",
                            "unavailable")
    recorded = _disclosure(db, campaign_id).get(research_key)
    current = recorded["current"]["state"] if recorded else INTERNAL
    outcome = (group.get("comparison") or {}).get("outcome")
    members, unresolved = [], []
    for member in group["members"]:
        verdict = member.get("verdict") or {}
        artifacts = {}
        for kind in ARTIFACT_KINDS:
            digest = verdict.get(f"{kind}_digest")
            if not digest:
                artifacts[kind] = {"digest": None, "resolved": None, "store": None}
                continue
            found = resolve_artifact(member["arena_id"], digest)
            artifacts[kind] = {"digest": digest, "resolved": found is not None,
                               "store": found["store"] if found else None}
            if found is None:
                unresolved.append(f"{member['finding_id']}: the {kind} artifact {digest} "
                                  "does not resolve in a live store.")
            elif include_evidence and found.get("body") is not None:
                artifacts[kind]["body_redacted"] = redact_deep(found["body"])
        poc = find_poc(member["finding_id"])
        entry = {
            "finding_id": member["finding_id"], "arena_id": member["arena_id"],
            "scenario": member.get("scenario"), "title": member.get("title"),
            "cwe": member.get("cwe"), "reported_at": member.get("reported_at"),
            "variant_of": member.get("variant_of"),
            "verdict": {key: verdict.get(key) for key in (
                "verdict", "reason_code", "validator_id", "validator_version")},
            "identity": member.get("identity"), "artifacts": artifacts,
            "poc": {"reported": poc is not None,
                    "digest": "sha256:" + _sha256(poc.encode()) if poc is not None else None,
                    "included": bool(include_poc and poc is not None)}}
        if include_poc and poc is not None:
            entry["poc"]["text_redacted"] = redact_deep(poc)
        members.append(entry)
    if outcome in (None, "unknown", "inconclusive"):
        unresolved.append(f"The evidence outcome across versions is {outcome or 'unknown'}.")
    supported, why_not = _support(current, group)
    if supported is False:
        unresolved.append(why_not[0].upper() + why_not[1:])
    history = [{key: entry[key] for key in ("state", "note", "reference", "at")}
               for entry in (recorded["history"] if recorded else [])]
    reference = group["members"][0]
    return {
        "schema": BUNDLE_SCHEMA,
        "campaign": {key: campaign[key] for key in ("campaign_id", "name", "product")},
        "research_key": research_key, "title": reference.get("title"),
        "cwe": reference.get("cwe"), "comparison": group.get("comparison"),
        "identities": _identity_lists(group["members"]), "members": members,
        "disclosure": {"state": current, "history": history,
                       "history_total": recorded["total"] if recorded else 0,
                       "state_supported_by_evidence": supported},
        "contents": {"include_poc": bool(include_poc), "include_evidence": bool(include_evidence),
                     "redaction": "PoC text and evidence bodies, when included, passed the "
                                  "platform redaction pass; raw HTTP transactions, key names, "
                                  "prompts and traces are never included."},
        "unresolved": [*unresolved, STANDING_NOTE]}


def generate_bundle(db, campaign_id: str, research_key: str, *, include_poc: bool = False,
                    include_evidence: bool = False, actor: str, find_group, find_poc,
                    resolve_artifact) -> dict:
    bundle = build_bundle(db, campaign_id, research_key, include_poc=include_poc,
                          include_evidence=include_evidence, find_group=find_group,
                          find_poc=find_poc, resolve_artifact=resolve_artifact)
    manifest = store_bundle(bundle)
    db.record_event(scope(campaign_id), BUNDLE_EVENT, {
        "campaign_id": campaign_id, "research_key": research_key,
        "bundle_digest": manifest["digest"], "bytes": manifest["bytes"],
        "include_poc": bool(include_poc), "include_evidence": bool(include_evidence),
        "unresolved_artifacts": sum(
            artifact["resolved"] is False for member in bundle["members"]
            for artifact in member["artifacts"].values())}, actor=actor)
    return {"bundle_digest": manifest["digest"], "bytes": manifest["bytes"], "bundle": bundle}


def get_bundle_bytes(db, campaign_id: str, digest: str) -> bytes:
    """The stored bytes of a bundle of this campaign, exactly as they were hashed.

    A reviewer checks a bundle file with ``sha256sum``; anything that re-serialises
    it (other key order, escaped characters, a trailing newline) breaks that.
    """
    _require_recorded_bundle(db, campaign_id, digest)
    return _load_bundle_snapshot(digest)[1]


def get_bundle(db, campaign_id: str, digest: str) -> dict:
    """A bundle recorded in this campaign, verified against its content address."""
    _require_recorded_bundle(db, campaign_id, digest)
    return load_bundle(digest)


def _require_recorded_bundle(db, campaign_id: str, digest: str) -> None:
    _required(db, campaign_id)
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise CampaignError("invalid disclosure bundle digest")
    recorded = {(event["payload"] or {}).get("bundle_digest") for event in db.list_events(
        scope(campaign_id), limit=None, types=(BUNDLE_EVENT,))}
    if digest not in recorded:
        raise CampaignError("disclosure bundle was not found", "not-found")
