"""
Field-B deploy observability: a failed deploy must leave an audit trail (a
`deploy_failed` event with phase/kind), and a *crashed* deploy task must record
the failure instead of leaving the arena stuck in 'deploying'.
"""
from database import Database


def _orch_returning(result):
    class _Orch:
        def __init__(self, provider=None, provider_name=None):
            pass

        def deploy(self, *a, **k):
            return result

    return _Orch


def _orch_raising(exc):
    class _Orch:
        def __init__(self, provider=None, provider_name=None):
            pass

        def deploy(self, *a, **k):
            raise exc

    return _Orch


def test_returned_failure_records_deploy_failed_event(monkeypatch):
    import tasks

    db = Database()
    db.create_deployment("obs-fail-1", "lab", "container_web_pentest", provider="docker-local")
    monkeypatch.setattr(tasks, "Orchestrator", _orch_returning(
        {"success": False, "error": "image not found: ghost/img:latest",
         "phase": "start node containers", "error_kind": "image_not_found"}
    ))

    tasks.deploy_lab("obs-fail-1", "container_web_pentest", "lab", provider="docker-local")

    dep = db.get_deployment("obs-fail-1")
    assert dep["status"] == "failed"
    assert "ghost/img" in dep["error"]
    evts = [e for e in db.list_events("obs-fail-1") if e["type"] == "deploy_failed"]
    assert evts, "a deploy_failed event must be recorded for the failure"
    payload = evts[0]["payload"]
    assert payload["phase"] == "start node containers"
    assert payload["error_kind"] == "image_not_found"
    assert payload["provider"] == "docker-local"


def test_crashed_deploy_is_recorded_not_left_deploying(monkeypatch):
    import tasks

    db = Database()
    db.create_deployment("obs-crash-1", "lab", "container_web_pentest", provider="docker-local")
    monkeypatch.setattr(tasks, "Orchestrator", _orch_raising(RuntimeError("celery boom")))

    tasks.deploy_lab("obs-crash-1", "container_web_pentest", "lab", provider="docker-local")

    dep = db.get_deployment("obs-crash-1")
    assert dep["status"] == "failed"          # NOT stuck in 'deploying'
    evts = [e for e in db.list_events("obs-crash-1") if e["type"] == "deploy_failed"]
    assert evts and evts[0]["payload"]["phase"] == "task"
    assert "celery boom" in evts[0]["payload"]["error"]
