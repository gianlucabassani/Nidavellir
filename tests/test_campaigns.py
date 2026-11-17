"""Research campaigns (NV-14, slice 1): deduplicated finding groups and disclosure state."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import api
import auth
import campaigns
from database import Database
from tests.test_finding_variants import (FIXED_EXPIRY, SCENARIO, _arena, _arena_with_recipe,
                                         _record_verdict)

BASE = "/research/campaigns"
# No field may claim absence or safety; states and outcomes are named for what they are.
CLAIM_WORDS = ("absen", "exhaust", "safe", "secure", "clean", "not_vulnerable")


def _client(role):
    db = Database()
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), name=f"campaign-{role}-{uuid.uuid4().hex[:6]}",
                      role=role)
    client = TestClient(api.app)
    client.headers["X-API-Key"] = key
    return client


@pytest.fixture()
def operator():
    return _client("operator")


def _hex():
    return uuid.uuid4().hex[:12]


OTHER_IMAGE = "sha256:" + "b" * 64


def _arena_with_image(db, name, image=OTHER_IMAGE):
    """An arena whose recipe pins a different target image: another version."""
    import copy

    arena = _arena(db, name)
    scenario = copy.deepcopy(SCENARIO)
    scenario["nodes"][0]["image"] = image
    api._record_lifecycle_recipe(name, scenario_name=name, scenario_config=scenario,
                                 requested_provider="docker-local", expires_at=FIXED_EXPIRY)
    return arena


def _pair(db, *, fixed_verdict="refuted", same_target=False):
    """A finding confirmed on one version and re-run on another, as NV-11 records it."""
    root, variant = _hex(), _hex()
    affected = _arena_with_recipe(db, "camp-affected-" + root[:6])
    fixed = (_arena_with_recipe if same_target else _arena_with_image)(
        db, "camp-fixed-" + root[:6])
    _record_verdict(db, affected, root, verdict="confirmed", reason="unauthorized_disclosure",
                    research_key=root)
    _record_verdict(db, fixed, variant, verdict=fixed_verdict, reason="access_denied",
                    variant_of=root, research_key=root)
    return root, variant, affected, fixed


def _create(operator, **overrides):
    body = {"name": "Vaultwarden 1.3x", "product": "vaultwarden", **overrides}
    response = operator.post(BASE, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _add(operator, campaign_id, finding_id):
    return operator.post(f"{BASE}/{campaign_id}/findings", json={"finding_id": finding_id})


def _disclose(operator, campaign_id, key, **body):
    return operator.post(f"{BASE}/{campaign_id}/findings/{key}/disclosure", json=body)


# --- boundaries --------------------------------------------------------------

def test_agent_keys_are_refused_on_every_route_before_any_lookup(operator):
    campaign = _create(operator)["campaign_id"]
    agent = _client("agent")
    key = "a" * 12
    for method, path, body in (
            ("post", BASE, {"name": "x", "product": "y"}),
            ("get", BASE, None),
            ("get", f"{BASE}/{campaign}", None),
            ("get", f"{BASE}/{'0' * 32}", None),
            ("post", f"{BASE}/{campaign}/findings", {"finding_id": key}),
            ("post", f"{BASE}/{campaign}/findings/{key}/disclosure", {"state": "reported"})):
        response = getattr(agent, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 403, (method, path, response.status_code)


def test_agents_cannot_read_campaign_events_from_the_feed(operator):
    db = Database()
    root, _, _, _ = _pair(db)
    campaign = _create(operator, note="operator-only campaign note")["campaign_id"]
    _add(operator, campaign, root)
    _disclose(operator, campaign, root, state="reported", note="sent to vendor privately")
    agent = _client("agent")
    # Bundle events are covered in tests/test_campaign_bundles.py.
    hidden = set(campaigns.EVENT_TYPES) - {campaigns.BUNDLE_EVENT}
    for kind in (None, *hidden):
        feed = agent.get("/events", params={"limit": 500, **({"type": kind} if kind else {})})
        # FR-04: the cross-arena feed is operator-only.
        assert feed.status_code == 403
        assert "sent to vendor privately" not in feed.text
        assert "operator-only campaign note" not in feed.text
    seen = {event["type"] for event in operator.get(
        "/events", params={"limit": 500}).json()["events"]}
    assert hidden <= seen


def test_campaign_changes_no_arena_or_budget_state(operator):
    db = Database()
    root, _, affected, fixed = _pair(db)
    before = {arena: (db.get_deployment(arena), len(db.list_events(arena, limit=None)))
              for arena in (affected, fixed)}
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    _disclose(operator, campaign, root, state="reported")
    operator.get(f"{BASE}/{campaign}")
    after = {arena: (db.get_deployment(arena), len(db.list_events(arena, limit=None)))
             for arena in (affected, fixed)}
    assert after == before
    assert {event["lab_id"] for event in db.list_events(limit=None, types=campaigns.EVENT_TYPES)
            if campaign in event["lab_id"]} == {"campaign:" + campaign}


# --- create, list, shape ------------------------------------------------------

def test_create_returns_the_summary_shape(operator):
    summary = _create(operator, note="  release history 1.35-1.37  ")
    assert set(summary) == {"schema", "campaign_id", "name", "product", "note", "created_at",
                            "actor", "findings", "by_disclosure_state", "unresolved"}
    assert summary["schema"] == "nidavellir/research-campaign/v1"
    assert len(summary["campaign_id"]) == 32 and summary["note"] == "release history 1.35-1.37"
    assert summary["findings"] == []
    assert summary["by_disclosure_state"] == {state: 0 for state in campaigns.DISCLOSURE_STATES}
    assert summary["unresolved"] == [campaigns.STANDING_NOTE]
    assert operator.get(f"{BASE}/{summary['campaign_id']}").json() == summary


@pytest.mark.parametrize("body", [
    {"name": "", "product": "p"}, {"name": "n"}, {"name": "n", "product": "p" * 121},
    {"name": "n", "product": "p", "extra": 1}, {"name": "bad\x07name", "product": "p"},
    {"name": "   ", "product": "p"}])
def test_invalid_create_is_refused(operator, body):
    assert operator.post(BASE, json=body).status_code == 422


def test_unknown_or_malformed_campaign_is_404(operator):
    assert operator.get(f"{BASE}/{'0' * 32}").status_code == 404
    assert operator.get(f"{BASE}/not-a-campaign").status_code == 404
    assert _add(operator, "0" * 32, "a" * 12).status_code == 404


def test_list_pages_newest_first(operator):
    created = [_create(operator, name=f"paged {index}")["campaign_id"] for index in range(3)]
    first = operator.get(BASE, params={"limit": 2}).json()
    assert [item["campaign_id"] for item in first["campaigns"]] == created[:0:-1]
    assert first["next_before"]
    rest = operator.get(BASE, params={"limit": 100, "before": first["next_before"]}).json()
    assert rest["campaigns"][0]["campaign_id"] == created[0]
    assert set(first["campaigns"][0]) == {"campaign_id", "name", "product", "created_at",
                                          "actor", "finding_groups"}


# --- one finding traced across versions ---------------------------------------

def test_pair_from_two_arenas_is_one_row_with_identities_by_verdict(operator):
    db = Database()
    root, variant, affected, fixed = _pair(db)
    campaign = _create(operator)["campaign_id"]
    added = _add(operator, campaign, variant)  # adding the variant adds the whole group
    assert added.status_code == 200 and added.json()["added"] is True
    assert added.json()["research_key"] == root
    summary = added.json()["campaign"]
    assert len(summary["findings"]) == 1
    row = summary["findings"][0]
    assert row["research_key"] == root and row["available"] is True
    assert [member["arena_id"] for member in row["members"]] == [affected, fixed]
    assert row["comparison"]["outcome"] == "disappeared_under_controls"
    identities = row["identities"]
    assert [item["arena_id"] for item in identities["affected"]] == [affected]
    assert [item["arena_id"] for item in identities["not_observed_under_controls"]] == [fixed]
    assert identities["unknown"] == []
    assert identities["affected"][0]["identity"]["images"]["target"]["image"].startswith("sha256:")
    assert row["disclosure"]["state"] == "internal" and row["disclosure_history"] == []
    assert row["state_supported_by_evidence"] is None
    assert row["bundles"] == [] and row["bundles_total"] == 0
    assert summary["by_disclosure_state"]["internal"] == 1


def test_adding_any_member_again_changes_nothing(operator):
    db = Database()
    root, variant, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    assert _add(operator, campaign, root).json()["added"] is True
    for again in (root, variant):
        repeat = _add(operator, campaign, again).json()
        assert repeat["added"] is False and len(repeat["campaign"]["findings"]) == 1
    events = db.list_events("campaign:" + campaign, limit=None,
                            types=(campaigns.FINDING_EVENT,))
    assert len(events) == 1
    assert operator.get(BASE, params={"limit": 100}).json()["campaigns"][0]["finding_groups"] == 1


def test_unlinked_findings_stay_separate_rows(operator):
    db = Database()
    first, _, _, _ = _pair(db)
    second, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, first)
    summary = _add(operator, campaign, second).json()["campaign"]
    assert [row["research_key"] for row in summary["findings"]] == [first, second]


def test_unknown_finding_is_404_and_malformed_is_422(operator):
    campaign = _create(operator)["campaign_id"]
    assert _add(operator, campaign, "0" * 12).status_code == 404
    assert _add(operator, campaign, "not-hex-id!!").status_code == 422
    assert _add(operator, campaign, "abc").status_code == 422


def test_member_without_a_readable_recipe_is_unknown(operator):
    db = Database()
    root, variant = _hex(), _hex()
    known = _arena_with_recipe(db, "camp-known-" + root[:6])
    bare = _arena(db, "camp-bare-" + root[:6])  # no lifecycle recipe: identity unknown
    _record_verdict(db, known, root, verdict="confirmed", reason="x", research_key=root)
    _record_verdict(db, bare, variant, verdict="refuted", reason="y", variant_of=root,
                    research_key=root)
    campaign = _create(operator)["campaign_id"]
    summary = _add(operator, campaign, root).json()["campaign"]
    row = summary["findings"][0]
    assert [item["arena_id"] for item in row["identities"]["unknown"]] == [bare]
    assert row["identities"]["not_observed_under_controls"] == []
    assert row["comparison"]["outcome"] == "unknown"
    assert any("evidence outcome across versions is unknown" in line
               for line in summary["unresolved"])


# --- disclosure state ----------------------------------------------------------

def test_states_append_and_history_keeps_every_entry(operator):
    db = Database()
    root, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    assert _disclose(operator, campaign, root, state="reported", reference="GHSA-demo",
                     note="reported to the maintainers").status_code == 200
    summary = _disclose(operator, campaign, root, state="fixed", note="1.37.3").json()
    row = summary["findings"][0]
    assert row["disclosure"]["state"] == "fixed" and row["disclosure"]["note"] == "1.37.3"
    assert [entry["state"] for entry in row["disclosure_history"]] == ["fixed", "reported"]
    assert row["disclosure_history"][1]["reference"] == "GHSA-demo"
    assert row["disclosure_history_total"] == 2
    assert all(entry["actor"] and entry["at"] for entry in row["disclosure_history"])
    assert summary["by_disclosure_state"]["fixed"] == 1
    assert summary["by_disclosure_state"]["internal"] == 0
    # Evidence shows the effect gone under matching controls: the state is supported.
    assert row["state_supported_by_evidence"] is True
    assert summary["unresolved"] == [campaigns.STANDING_NOTE]
    # The finding events themselves are untouched by any of this.
    assert operator.get(f"/findings/{root}").json()["comparison"]["outcome"] == \
        "disappeared_under_controls"


def test_fixed_without_supporting_evidence_is_allowed_but_visible(operator):
    db = Database()
    root = _hex()
    arena = _arena_with_recipe(db, "camp-single-" + root[:6])
    _record_verdict(db, arena, root, verdict="confirmed", reason="x", research_key=root)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    response = _disclose(operator, campaign, root, state="fixed")
    assert response.status_code == 200
    row = response.json()["findings"][0]
    assert row["disclosure"]["state"] == "fixed"
    assert row["state_supported_by_evidence"] is False
    assert any(f"{root}: marked fixed, but the recorded evidence outcome is unknown"
               in line for line in response.json()["unresolved"])


def test_fixed_is_not_supported_when_the_refuting_run_repeated_the_same_target(operator):
    """NV-11 reads `disappeared_under_controls` for any confirmed-then-refuted pair,
    also when the second run used the very same image (a flaky target, a used grant)."""
    db = Database()
    root, _, _, _ = _pair(db, same_target=True)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    summary = _disclose(operator, campaign, root, state="fixed").json()
    row = summary["findings"][0]
    assert row["comparison"]["outcome"] == "disappeared_under_controls"
    # Two arenas give two recipe digests even for one image, so that is not the test.
    assert row["comparison"]["identity_match"] == "different_recipe"
    assert row["state_supported_by_evidence"] is False
    assert (f"{root}: marked fixed, but the refuting run used the same target as the "
            "confirming run, so no other version was tested.") in summary["unresolved"]


def test_regressed_needs_a_confirmed_run_after_a_refuted_one_on_another_target(operator):
    db = Database()
    campaign = _create(operator)["campaign_id"]
    # Older version also confirmed, newer refuted: something was fixed, nothing regressed.
    root, old = _hex(), _hex()
    first = _arena_with_recipe(db, "camp-reg-root-" + root[:6])
    _record_verdict(db, first, root, verdict="confirmed", reason="x", research_key=root)
    older = _arena_with_image(db, "camp-reg-old-" + root[:6], "sha256:" + "c" * 64)
    _record_verdict(db, older, old, verdict="confirmed", reason="x", variant_of=root,
                    research_key=root)
    newer = _arena_with_image(db, "camp-reg-new-" + root[:6])
    _record_verdict(db, newer, _hex(), verdict="refuted", reason="y", variant_of=root,
                    research_key=root)
    _add(operator, campaign, root)
    summary = _disclose(operator, campaign, root, state="regressed",
                        note="claimed regression without a later confirmed run").json()
    row = summary["findings"][0]
    assert row["comparison"]["outcome"] == "still_observed"
    assert row["state_supported_by_evidence"] is False
    assert any("no confirmed run on a different target was recorded after a refuted one" in line
               for line in summary["unresolved"])
    # A later confirmed run on yet another target is a regression the evidence shows.
    latest = _arena_with_image(db, "camp-reg-latest-" + root[:6], "sha256:" + "d" * 64)
    _record_verdict(db, latest, _hex(), verdict="confirmed", reason="x", variant_of=root,
                    research_key=root)
    row = operator.get(f"{BASE}/{campaign}").json()["findings"][0]
    assert row["state_supported_by_evidence"] is True


def test_regressed_is_not_supported_without_a_run_that_first_held(operator):
    db = Database()
    still, _, _, _ = _pair(db, fixed_verdict="confirmed")
    gone, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    for key in (still, gone):
        _add(operator, campaign, key)
        assert _disclose(operator, campaign, key, state="regressed",
                         note="fix did not hold on re-run").status_code == 200
    rows = {row["research_key"]: row
            for row in operator.get(f"{BASE}/{campaign}").json()["findings"]}
    # Confirmed on both versions and never refuted: still observed, but nothing
    # ever held, so the evidence does not show a regression.
    assert rows[still]["comparison"]["outcome"] == "still_observed"
    assert rows[still]["state_supported_by_evidence"] is False
    assert rows[gone]["state_supported_by_evidence"] is False


@pytest.mark.parametrize("body", [
    {"state": "regressed"}, {"state": "regressed", "note": "too short"},
    {"state": "internal"}, {"state": "internal", "note": "         "},
    {"state": "wontfix"}, {"state": "reported", "note": "n" * 2001},
    {"state": "reported", "reference": "r" * 121}, {"state": "reported", "extra": True},
    {"state": "reported", "reference": "bad\x00ref"}, {}])
def test_invalid_disclosure_is_refused_and_records_nothing(operator, body):
    db = Database()
    root, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    assert _disclose(operator, campaign, root, **body).status_code == 422
    assert db.list_events("campaign:" + campaign, limit=None,
                          types=(campaigns.DISCLOSURE_EVENT,)) == []


def test_returning_to_internal_needs_and_keeps_a_reason(operator):
    db = Database()
    root, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    _disclose(operator, campaign, root, state="reported")
    row = _disclose(operator, campaign, root, state="internal",
                    note="reported by mistake, withdrawn").json()["findings"][0]
    assert row["disclosure"]["state"] == "internal"
    assert [entry["state"] for entry in row["disclosure_history"]] == ["internal", "reported"]


def test_disclosure_needs_the_group_to_be_in_this_campaign(operator):
    db = Database()
    root, _, _, _ = _pair(db)
    other, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    elsewhere = _create(operator, name="another")["campaign_id"]
    _add(operator, campaign, root)
    _add(operator, elsewhere, other)
    assert _disclose(operator, campaign, other, state="reported").status_code == 404
    assert _disclose(operator, campaign, "0" * 12, state="reported").status_code == 404
    # State is per campaign: the same group elsewhere is untouched.
    _add(operator, elsewhere, root)
    _disclose(operator, campaign, root, state="published")
    rows = {row["research_key"]: row
            for row in operator.get(f"{BASE}/{elsewhere}").json()["findings"]}
    assert rows[root]["disclosure"]["state"] == "internal"


def test_history_is_bounded_and_counts_everything(operator):
    db = Database()
    root, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    for index in range(campaigns.HISTORY_MAX + 3):
        _disclose(operator, campaign, root, state="reported", note=f"entry {index}")
    row = operator.get(f"{BASE}/{campaign}").json()["findings"][0]
    assert len(row["disclosure_history"]) == campaigns.HISTORY_MAX
    assert row["disclosure_history_total"] == campaigns.HISTORY_MAX + 3
    assert row["disclosure_history"][0]["note"] == f"entry {campaigns.HISTORY_MAX + 2}"


# --- what the summary never says ------------------------------------------------

def test_new_member_appears_without_touching_the_campaign(operator):
    """A later re-run reported with variant_of shows up because groups are read live."""
    db = Database()
    root, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)
    newer = _arena_with_recipe(db, "camp-newer-" + root[:6])
    _record_verdict(db, newer, _hex(), verdict="confirmed", reason="x", variant_of=root,
                    research_key=root)
    row = operator.get(f"{BASE}/{campaign}").json()["findings"][0]
    assert len(row["members"]) == 3
    assert row["comparison"]["outcome"] == "still_observed"
    assert newer in [item["arena_id"] for item in row["identities"]["affected"]]


def test_no_field_claims_absence_or_safety(operator):
    db = Database()
    root, _, _, _ = _pair(db)
    campaign = _create(operator)["campaign_id"]
    _add(operator, campaign, root)

    def names(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from names(item)
        elif isinstance(value, list):
            for item in value:
                yield from names(item)

    found = set(names(operator.get(f"{BASE}/{campaign}").json())) | set(
        names(operator.get(BASE).json()))
    assert not [name for name in found if any(word in name.lower() for word in CLAIM_WORDS)]
    assert "not_observed_under_controls" in found


def test_missing_finding_records_keep_the_row_and_say_so(operator):
    campaign = _create(operator)["campaign_id"]
    key = _hex()
    Database().record_event("campaign:" + campaign, campaigns.FINDING_EVENT,
                            {"campaign_id": campaign, "research_key": key, "added_as": key},
                            actor="operator")
    summary = operator.get(f"{BASE}/{campaign}").json()
    row = summary["findings"][0]
    assert row["available"] is False and row["members"] == [] and row["comparison"] is None
    assert f"{key}: its finding records are no longer available." in summary["unresolved"]
