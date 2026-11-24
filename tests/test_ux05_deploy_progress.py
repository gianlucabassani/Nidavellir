"""UX-05: launch progress is reported as `deploy_phase` events.

The worker wraps a deploy in a reporting context; providers mark phase
boundaries; the console projects the latest state per phase. Progress is
best-effort and operator-only.
"""
import deploy_progress
import event_visibility
from providers import mock as mock_provider


class _Db:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def record_event(self, instance_id, kind, payload, actor=None):
        if self.fail:
            raise RuntimeError("database down")
        self.events.append((instance_id, kind, dict(payload), actor))


def _phases(db):
    return [(p["phase"], p["state"]) for _, kind, p, _ in db.events if kind == deploy_progress.EVENT]


def test_phase_closes_the_previous_one_and_failed_marks_the_open_phase():
    db = _Db()
    with deploy_progress.reporting(db, "arena-1"):
        deploy_progress.phase("network")
        deploy_progress.phase("nodes", total=2)
        deploy_progress.mark("pull", "started", image="nginx:1.27")
        deploy_progress.mark("pull", "done", image="nginx:1.27")
        deploy_progress.failed("boom")
    assert _phases(db) == [
        ("network", "started"), ("network", "done"), ("nodes", "started"),
        ("pull", "started"), ("pull", "done"), ("nodes", "failed"),
    ]
    assert all(actor == "worker" and iid == "arena-1" for iid, _, _, actor in db.events)


def test_outside_a_reporting_context_providers_record_nothing():
    deploy_progress.phase("network")
    deploy_progress.done()
    deploy_progress.failed("x")


def test_a_progress_write_failure_never_fails_the_deploy():
    with deploy_progress.reporting(_Db(fail=True), "arena-1"):
        deploy_progress.phase("network")
        deploy_progress.done()


def test_mock_provider_reports_network_pull_and_nodes(monkeypatch):
    monkeypatch.setattr(mock_provider, "MOCK_DEPLOY_DELAY", 0)
    db = _Db()
    with deploy_progress.reporting(db, "arena-1"):
        result = mock_provider.MockProvider().deploy(
            {"nodes": [{"name": "victim", "image": "nginx"}]}, "arena-1")
    assert result["success"]
    assert _phases(db) == [
        ("network", "started"), ("network", "done"), ("nodes", "started"),
        ("pull", "started"), ("pull", "done"), ("nodes", "done"),
    ]


def test_deploy_phase_events_stay_hidden_from_agents():
    for stance in ("attacker", "defender", None):
        assert deploy_progress.EVENT not in event_visibility.visible_event_types(stance)


def test_console_projects_the_latest_state_per_phase_in_display_order():
    import pytest
    pytest.importorskip("flask_wtf")
    import tests.test_webui  # noqa: F401  (puts the webui on sys.path)
    from app import _console_deploy_phases

    newest_first = [
        {"ts": "t4", "payload": {"phase": "nodes", "state": "done"}},
        {"ts": "t3", "payload": {"phase": "pull", "state": "done", "image": "nginx"}},
        {"ts": "t2", "payload": {"phase": "nodes", "state": "started", "total": 2}},
        {"ts": "t1", "payload": {"phase": "network", "state": "started"}},
        {"ts": "t0", "payload": {"phase": "bogus", "state": "started"}},
    ]
    phases = _console_deploy_phases(newest_first)
    assert [(p["phase"], p["state"]) for p in phases] == [
        ("network", "started"), ("pull", "done"), ("nodes", "done")]
    nodes = phases[2]
    assert nodes["started_at"] == "t2" and nodes["ts"] == "t4" and nodes["total"] == 2
