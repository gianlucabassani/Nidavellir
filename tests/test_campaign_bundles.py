"""Disclosure bundles (NV-14, slice 2): allowlist, redaction pass, content address."""
from __future__ import annotations

import socket

import pytest

import campaigns
import config
import http_transactions
import validation_evidence
from database import Database
from tests.test_campaigns import (BASE, _add, _arena_with_image, _create, _disclose, _hex,  # noqa: F401
                                  _pair, operator)
from tests.test_finding_variants import _arena_with_recipe, _record_verdict

SECRET_TOKEN = "tok-live-4f9a1c7e22"
POC = ("curl -H 'Authorization: Bearer " + SECRET_TOKEN + "' http://target/api/ciphers\n"
       "password=hunter2-very-secret\n# then read the other account's vault")
MASK = "***REDACTED***"


def _bundle(client, campaign_id, key, **body):
    return client.post(f"{BASE}/{campaign_id}/findings/{key}/bundles", json=body)


def _evidenced_pair(db):
    """A pair whose verdict digests resolve: real evidence files and a real transaction."""
    root, variant = _hex(), _hex()
    arenas = {"affected": _arena_with_recipe(db, "bundle-affected-" + root[:6]),
              "fixed": _arena_with_image(db, "bundle-fixed-" + root[:6])}
    for role, finding, verdict, variant_of in (("affected", root, "confirmed", None),
                                               ("fixed", variant, "refuted", root)):
        arena = arenas[role]
        observation = validation_evidence.record(arena, {
            "status": 200 if role == "affected" else 403, "marker_in_body": role == "affected",
            "request_headers": {"Authorization": "Bearer " + SECRET_TOKEN, "Accept": "*/*"},
            "note": f"api_key={SECRET_TOKEN} seen in body"})
        control = validation_evidence.record(arena, {"status": 200, "owner": "A", "role": role})
        action = http_transactions.record(
            arena, request={"method": "GET", "url": "http://target/api/ciphers",
                            "headers": {"Authorization": "Bearer " + SECRET_TOKEN}},
            response={"status": 200, "headers": {}, "body": "private-vault-content"},
            actor="operator")["digest"]
        db.record_event(arena, "finding", {
            "finding_id": finding, "title": "Cross-account vault read — «café»",
            "cwe": "CWE-639",
            "node": "target", "variant_of": variant_of, "research_key": root, "poc": POC,
            "validation": {"verdict": verdict, "reason_code": "x",
                           "validator_id": "http_access_control", "validator_version": 1,
                           "action_digest": action, "observation_digest": observation,
                           "control_digest": control}}, actor="secret-key-name")
    return root, variant, arenas


@pytest.fixture()
def bundle_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DISCLOSURE_BUNDLES_DIR", tmp_path / "disclosure-bundles")
    return tmp_path / "disclosure-bundles"


def _campaign_with(client, key):
    campaign = _create(client)["campaign_id"]
    assert _add(client, campaign, key).status_code == 200
    return campaign


def test_default_bundle_is_an_allowlist_with_digests_only(operator, bundle_store):  # noqa: F811
    db = Database()
    root, variant, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    _disclose(operator, campaign, root, state="reported", reference="GHSA-demo",
              note="reported to maintainers")
    response = _bundle(operator, campaign, root)
    assert response.status_code == 201, response.text
    body = response.json()
    bundle = body["bundle"]
    assert set(body) == {"bundle_digest", "bytes", "bundle"}
    assert set(bundle) == {"schema", "campaign", "research_key", "title", "cwe", "comparison",
                           "identities", "members", "disclosure", "contents", "unresolved"}
    assert bundle["schema"] == "nidavellir/disclosure-bundle/v1"
    assert bundle["campaign"] == {"campaign_id": campaign, "name": "Vaultwarden 1.3x",
                                  "product": "vaultwarden"}
    assert bundle["comparison"]["outcome"] == "disappeared_under_controls"
    assert [member["finding_id"] for member in bundle["members"]] == [root, variant]
    for member in bundle["members"]:
        assert set(member) == {"finding_id", "arena_id", "scenario", "title", "cwe",
                               "reported_at", "variant_of", "verdict", "identity",
                               "artifacts", "poc"}
        assert set(member["verdict"]) == {"verdict", "reason_code", "validator_id",
                                          "validator_version"}
        assert member["poc"] == {"reported": True, "included": False,
                                 "digest": "sha256:" + campaigns._sha256(POC.encode())}
        assert {kind: (item["resolved"], item["store"])
                for kind, item in member["artifacts"].items()} == {
            "action": (True, "http-transactions"),
            "observation": (True, "validation-evidence"),
            "control": (True, "validation-evidence")}
        assert all(set(item) == {"digest", "resolved", "store"}
                   for item in member["artifacts"].values())
    assert bundle["disclosure"]["state"] == "reported"
    history = bundle["disclosure"]["history"]
    assert [set(entry) for entry in history] == [{"state", "note", "reference", "at"}]
    assert history[0]["note"] == "reported to maintainers"
    assert history[0]["reference"] == "GHSA-demo"
    assert bundle["contents"]["include_poc"] is False
    assert bundle["contents"]["include_evidence"] is False
    assert bundle["unresolved"] == [campaigns.STANDING_NOTE]
    # No PoC text, evidence body, credential, private content or key name anywhere.
    for forbidden in (SECRET_TOKEN, "hunter2", "private-vault-content", "secret-key-name",
                      "curl -H", "marker_in_body", "campaign-operator"):
        assert forbidden not in response.text, forbidden
    # Stored under its own digest and listed on the campaign.
    assert body["bundle_digest"] == "sha256:" + campaigns._sha256(campaigns._canonical(bundle))
    row = operator.get(f"{BASE}/{campaign}").json()["findings"][0]
    assert row["bundles_total"] == 1
    assert row["bundles"][0]["bundle_digest"] == body["bundle_digest"]
    assert row["bundles"][0]["include_poc"] is False
    assert row["bundles"][0]["unresolved_artifacts"] == 0
    assert operator.get(f"{BASE}/{campaign}/bundles/{body['bundle_digest']}").json() == bundle


def test_opt_in_poc_and_evidence_pass_the_redaction_pass(operator, bundle_store):  # noqa: F811
    db = Database()
    root, _, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    response = _bundle(operator, campaign, root, include_poc=True, include_evidence=True)
    assert response.status_code == 201
    bundle = response.json()["bundle"]
    member = bundle["members"][0]
    assert member["poc"]["included"] is True
    assert "read the other account's vault" in member["poc"]["text_redacted"]
    observed = member["artifacts"]["observation"]["body_redacted"]
    assert observed["status"] == 200 and observed["marker_in_body"] is True
    assert observed["request_headers"] == {"Authorization": MASK, "Accept": "*/*"}
    # The raw transaction is cited by digest only, even with evidence included.
    assert "body_redacted" not in member["artifacts"]["action"]
    assert bundle["contents"]["include_poc"] is True
    assert bundle["contents"]["include_evidence"] is True
    for forbidden in (SECRET_TOKEN, "hunter2", "private-vault-content", "secret-key-name"):
        assert forbidden not in response.text, forbidden
    listed = operator.get(f"{BASE}/{campaign}").json()["findings"][0]["bundles"][0]
    assert listed["include_evidence"] is True and listed["include_poc"] is True


def test_redaction_masks_credentials_at_any_depth():
    masked = campaigns.redact_deep({
        "headers": {"Cookie": "session=abc123456", "X-Api-Key": "k-123456", "Accept": "json"},
        "nested": [{"password": "p4ssw0rd!", "text": "token=abcdef123456 trailing"},
                   "Authorization: Bearer abcdefgh12345678"],
        "count": 3, "ok": True})
    assert masked["headers"] == {"Cookie": MASK, "X-Api-Key": MASK, "Accept": "json"}
    assert masked["nested"][0]["password"] == MASK
    assert "abcdef123456" not in masked["nested"][0]["text"]
    assert "abcdefgh12345678" not in masked["nested"][1]
    assert masked["count"] == 3 and masked["ok"] is True


def test_artifact_that_no_longer_resolves_is_listed_not_hidden(operator, bundle_store):  # noqa: F811
    db = Database()
    root, _, _, _ = _pair(db)  # digests in these verdicts point at nothing
    campaign = _campaign_with(operator, root)
    response = _bundle(operator, campaign, root)
    assert response.status_code == 201
    bundle = response.json()["bundle"]
    assert all(item["resolved"] is False for member in bundle["members"]
               for item in member["artifacts"].values())
    assert sum("does not resolve in a live store" in line for line in bundle["unresolved"]) == 6
    listed = operator.get(f"{BASE}/{campaign}").json()["findings"][0]["bundles"][0]
    assert listed["unresolved_artifacts"] == 6


def test_unsupported_state_and_unknown_outcome_are_carried_into_the_bundle(
        operator, bundle_store):  # noqa: F811
    db = Database()
    root = _hex()
    arena = _arena_with_recipe(db, "bundle-single-" + root[:6])
    _record_verdict(db, arena, root, verdict="confirmed", reason="x", research_key=root)
    campaign = _campaign_with(operator, root)
    _disclose(operator, campaign, root, state="fixed")
    bundle = _bundle(operator, campaign, root).json()["bundle"]
    assert bundle["disclosure"]["state_supported_by_evidence"] is False
    assert "The evidence outcome across versions is unknown." in bundle["unresolved"]
    assert any(line.startswith("Marked fixed, but") for line in bundle["unresolved"])
    assert len(bundle["identities"]["affected"]) == 1


def test_same_state_gives_the_same_bundle_and_a_change_gives_a_new_one(
        operator, bundle_store):  # noqa: F811
    db = Database()
    root, _, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    first = _bundle(operator, campaign, root).json()["bundle_digest"]
    assert _bundle(operator, campaign, root).json()["bundle_digest"] == first
    assert len(list(bundle_store.glob("*/bundle.json"))) == 1
    _disclose(operator, campaign, root, state="reported")
    assert _bundle(operator, campaign, root).json()["bundle_digest"] != first
    assert operator.get(f"{BASE}/{campaign}").json()["findings"][0]["bundles_total"] == 3


def test_altered_or_missing_bundle_fails_closed(operator, bundle_store):  # noqa: F811
    db = Database()
    root, _, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    digest = _bundle(operator, campaign, root).json()["bundle_digest"]
    stored = bundle_store / digest[7:] / "bundle.json"
    original = stored.read_bytes()
    altered = bytearray(original)
    altered[len(altered) // 2] ^= 1
    stored.write_bytes(bytes(altered))
    assert operator.get(f"{BASE}/{campaign}/bundles/{digest}").status_code == 409
    # Regenerating the same state must not paper over the damaged file.
    assert _bundle(operator, campaign, root).status_code == 409
    assert stored.read_bytes() == bytes(altered)
    stored.write_bytes(original)
    assert operator.get(f"{BASE}/{campaign}/bundles/{digest}").status_code == 200
    stored.unlink()
    assert operator.get(f"{BASE}/{campaign}/bundles/{digest}").status_code == 409


def test_bundle_reads_are_scoped_to_their_campaign(operator, bundle_store):  # noqa: F811
    db = Database()
    root, _, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    other = _create(operator, name="other")["campaign_id"]
    digest = _bundle(operator, campaign, root).json()["bundle_digest"]
    assert operator.get(f"{BASE}/{other}/bundles/{digest}").status_code == 404
    assert operator.get(f"{BASE}/{campaign}/bundles/sha256:{'0' * 64}").status_code == 404
    assert operator.get(f"{BASE}/{campaign}/bundles/not-a-digest").status_code == 422
    assert operator.get(f"{BASE}/{campaign}/bundles/..%2F..%2Fetc").status_code in (404, 422)
    assert _bundle(operator, campaign, "0" * 12).status_code == 404
    assert _bundle(operator, other, root).status_code == 404  # group not in that campaign
    assert _bundle(operator, campaign, root, include_poc="yes please").status_code == 422
    assert _bundle(operator, campaign, root, extra=True).status_code == 422


def test_group_without_finding_records_cannot_be_bundled(operator, bundle_store):  # noqa: F811
    campaign = _create(operator)["campaign_id"]
    key = _hex()
    Database().record_event("campaign:" + campaign, campaigns.FINDING_EVENT,
                            {"campaign_id": campaign, "research_key": key, "added_as": key},
                            actor="operator")
    assert _bundle(operator, campaign, key).status_code == 409
    assert not list(bundle_store.glob("*/bundle.json"))


def test_bundle_size_and_store_caps_refuse(operator, bundle_store, monkeypatch):  # noqa: F811
    db = Database()
    root, _, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    monkeypatch.setattr(config, "DISCLOSURE_BUNDLE_MAX_BYTES", 100)
    assert _bundle(operator, campaign, root).status_code == 422
    monkeypatch.setattr(config, "DISCLOSURE_BUNDLE_MAX_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr(config, "DISCLOSURE_BUNDLE_STORE_MAX_BYTES", 100)
    assert _bundle(operator, campaign, root).status_code == 422
    assert not list(bundle_store.glob("*/bundle.json"))
    assert operator.get(f"{BASE}/{campaign}").json()["findings"][0]["bundles_total"] == 0


def test_bundle_generation_touches_no_arena_and_opens_no_connection(
        operator, bundle_store, monkeypatch):  # noqa: F811
    db = Database()
    root, _, arenas = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    before = {arena: len(db.list_events(arena, limit=None)) for arena in arenas.values()}

    def no_network(*args, **kwargs):
        raise AssertionError("bundle generation opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    assert _bundle(operator, campaign, root, include_poc=True,
                   include_evidence=True).status_code == 201
    assert {arena: len(db.list_events(arena, limit=None)) for arena in arenas.values()} == before


def test_agents_are_refused_and_do_not_see_bundle_events(operator, bundle_store):  # noqa: F811
    from tests.test_campaigns import _client

    db = Database()
    root, _, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    digest = _bundle(operator, campaign, root).json()["bundle_digest"]
    agent = _client("agent")
    assert _bundle(agent, campaign, root).status_code == 403
    assert agent.get(f"{BASE}/{campaign}/bundles/{digest}").status_code == 403
    assert agent.get(f"{BASE}/{campaign}/bundles/not-a-digest").status_code == 403
    feed = agent.get("/events", params={"limit": 500, "type": campaigns.BUNDLE_EVENT})
    assert feed.status_code == 403  # FR-04: the cross-arena feed is operator-only
    assert digest not in feed.text
    seen = operator.get("/events", params={"limit": 500, "type": campaigns.BUNDLE_EVENT})
    assert any(event["payload"]["bundle_digest"] == digest for event in seen.json()["events"])


def test_the_bundle_file_hashes_to_its_digest(operator, bundle_store):  # noqa: F811
    """A reviewer checks the downloaded file with sha256sum; it must match as served."""
    import hashlib

    db = Database()
    root, _, _ = _evidenced_pair(db)  # the title holds non-ASCII text on purpose
    campaign = _campaign_with(operator, root)
    made = _bundle(operator, campaign, root).json()
    digest = made["bundle_digest"]
    response = operator.get(f"{BASE}/{campaign}/bundles/{digest}")
    assert response.status_code == 200
    assert "sha256:" + hashlib.sha256(response.content).hexdigest() == digest
    assert response.content == (bundle_store / digest[7:] / "bundle.json").read_bytes()
    assert response.headers["X-Bundle-Digest"] == digest
    assert response.headers["content-type"].startswith("application/json")
    assert "café".encode() in response.content and not response.content.endswith(b"\n")
    assert response.json() == made["bundle"]


def test_same_target_rerun_is_carried_into_the_bundle(operator, bundle_store):  # noqa: F811
    db = Database()
    root, _, _, _ = _pair(db, same_target=True)
    campaign = _campaign_with(operator, root)
    _disclose(operator, campaign, root, state="fixed")
    bundle = _bundle(operator, campaign, root).json()["bundle"]
    assert bundle["disclosure"]["state_supported_by_evidence"] is False
    assert any(line.startswith("Marked fixed, but the refuting run used the same target")
               for line in bundle["unresolved"])


def test_bundle_download_returns_the_same_snapshot_it_verified(operator, bundle_store, monkeypatch):  # noqa: F811
    from pathlib import Path
    import hashlib

    db = Database()
    root, _, _ = _evidenced_pair(db)
    campaign = _campaign_with(operator, root)
    created = _bundle(operator, campaign, root).json()
    digest = created["bundle_digest"]
    payload_path = campaigns._bundle_paths(digest)[0]
    original_read = Path.read_bytes
    reads = 0

    def change_after_read(path):
        nonlocal reads
        content = original_read(path)
        if path == payload_path:
            reads += 1
            if reads == 1:
                path.write_bytes(b'{"replaced":true}')
        return content

    monkeypatch.setattr(Path, "read_bytes", change_after_read)
    content = campaigns.get_bundle_bytes(db, campaign, digest)
    assert "sha256:" + hashlib.sha256(content).hexdigest() == digest
