"""Tests for the R1 HTTP transaction store (slice 3)."""

import config
import pytest

import http_transactions as tx


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HTTP_TRANSACTIONS_DIR", tmp_path / "tx")
    monkeypatch.setattr(config, "HTTP_TRANSACTION_MAX_BYTES", 64 * 1024)
    monkeypatch.setattr(config, "HTTP_TRANSACTION_STORE_MAX_BYTES", 256 * 1024)


def _request(**over):
    base = {
        "node": "victim",
        "method": "GET",
        "path": "/login",
        "params": {"u": "admin"},
        "headers": {"X-Proof": "1"},
        "body": None,
    }
    base.update(over)
    return base


def _response(**over):
    base = {
        "status": 200,
        "reason": "OK",
        "http_version": "HTTP/1.1",
        "headers": {"content-type": "text/html"},
        "header_count": 1,
        "redirect_location": None,
        "body": "<html>ok</html>",
        "body_bytes": 13,
        "body_sha256": "sha256:" + "a" * 64,
        "truncated": False,
    }
    base.update(over)
    return base


def test_record_and_get_roundtrip_with_integrity():
    public = tx.record("arena-1", request=_request(), response=_response())
    assert public["kind"] == "http_transaction"
    assert public["digest"].startswith("sha256:")
    assert public["arena_id"] == "arena-1"

    manifest, envelope = tx.get("arena-1", public["digest"])
    assert manifest["digest"] == public["digest"]
    assert envelope["request"]["path"] == "/login"
    assert envelope["response"]["body"] == "<html>ok</html>"


def test_identical_resend_dedups_onto_one_record():
    first = tx.record("arena-1", request=_request(), response=_response())
    second = tx.record("arena-1", request=_request(), response=_response())
    assert first["digest"] == second["digest"]
    listed = tx.list_transactions("arena-1")
    assert listed["total"] == 1


def test_modified_replay_is_a_new_linked_record():
    parent = tx.record("arena-1", request=_request(), response=_response())
    replay = tx.record(
        "arena-1",
        request=_request(params={"u": "admin'"}),
        response=_response(status=500),
        replay_of=parent["digest"],
    )
    assert replay["digest"] != parent["digest"]
    assert replay["replay_of"] == parent["digest"]
    _, envelope = tx.get("arena-1", replay["digest"])
    assert envelope["request"]["params"] == {"u": "admin'"}


def test_envelope_exceeding_the_record_limit_is_refused(monkeypatch):
    monkeypatch.setattr(config, "HTTP_TRANSACTION_MAX_BYTES", 200)
    with pytest.raises(tx.HttpTransactionError, match="limit"):
        tx.record("arena-1", request=_request(body="x" * 400), response=_response())


def test_store_capacity_is_enforced(monkeypatch):
    monkeypatch.setattr(config, "HTTP_TRANSACTION_STORE_MAX_BYTES", 600)
    tx.record("arena-1", request=_request(), response=_response())
    with pytest.raises(tx.HttpTransactionError, match="capacity"):
        tx.record("arena-2", request=_request(), response=_response())


def test_records_are_arena_scoped():
    public = tx.record("arena-1", request=_request(), response=_response())
    with pytest.raises(tx.HttpTransactionError, match="not found"):
        tx.get("arena-other", public["digest"])


def test_corrupted_payload_is_detected():
    public = tx.record("arena-1", request=_request(), response=_response())
    payload_path, _ = tx._paths("arena-1", public["digest"])
    payload_path.write_bytes(b'{"schema":"tampered"}')
    with pytest.raises(tx.HttpTransactionError, match="integrity"):
        tx.get("arena-1", public["digest"])


def test_invalid_digest_is_rejected():
    with pytest.raises(tx.HttpTransactionError):
        tx.get("arena-1", "../../etc/passwd")


def test_list_is_newest_first_bounded_and_tolerates_torn_writes(tmp_path):
    import time

    digests = []
    for i in range(5):
        public = tx.record(
            "arena-1",
            request=_request(path=f"/p{i}"),
            response=_response(),
        )
        digests.append(public["digest"])
        time.sleep(0.002)
    # A torn write (manifest only) must not break listing.
    torn_dir = config.HTTP_TRANSACTIONS_DIR / "torn" / "aa"
    torn_dir.mkdir(parents=True)
    (torn_dir / "manifest.json").write_text('{"digest": "sha256:' + "b" * 64 + '"}')

    listed = tx.list_transactions("arena-1", limit=3)
    assert listed["total"] == 5
    assert len(listed["transactions"]) == 3
    returned = [t["digest"] for t in listed["transactions"]]
    assert returned == list(reversed(digests))[:3]
    page_two = tx.list_transactions("arena-1", limit=3, offset=2)
    assert [t["digest"] for t in page_two["transactions"]] == list(reversed(digests))[2:5]


def test_manifest_survives_payload_directory_listing_after_destroy():
    """Records live outside any arena lifecycle: nothing to clean here, but a
    record written for an arena whose DB row is gone stays fully readable."""
    public = tx.record("gone-arena", request=_request(), response=_response())
    manifest, envelope = tx.get("gone-arena", public["digest"])
    assert manifest["arena_id"] == "gone-arena"
    assert envelope["schema"] == "nidavellir/http-transaction/v1"
