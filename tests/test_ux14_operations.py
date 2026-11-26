"""UX-14 (FR-19): the operations page's snapshot and orphan reclaim.

Operator-only. Every probe degrades to a reason. Labelled Docker resources
are grouped by arena and classified against this installation's records: only
leftovers of a destroyed (or failed) arena can be reclaimed; an arena this
installation does not know may be another installation's on the same host,
so it is listed and refused."""
import time
import uuid
from types import SimpleNamespace

import api
import operations
import tasks
from database import Database
from tests.research_support import active_arena, client


def _arena(status: str) -> str:
    db = Database()
    arena = uuid.uuid4().hex[:16]
    db.create_deployment(arena, f"ops-{arena[:6]}", "custom", provider=None, actor="test")
    path = {"active": ["deploying", "active"],
            "destroyed": ["deploying", "active", "destroying", "destroyed"],
            "failed": ["deploying", "failed"]}[status]
    for step in path:
        db.update_deployment(arena, status=step, actor="test")
    return arena


def test_snapshot_is_operator_only_and_degrades_without_docker(monkeypatch):
    from fastapi.testclient import TestClient

    assert TestClient(api.app).get("/system/operations").status_code == 401
    assert client("agent").get("/system/operations").status_code == 403
    snap = client("operator").get("/system/operations").json()
    assert set(snap) >= {"observed_at", "ready", "dependencies", "queues", "worker", "helpers",
                         "arenas", "docker", "stores", "migration", "backup"}
    assert snap["dependencies"]["database"] == "ok"
    assert snap["dependencies"]["docker"].startswith(("ok", "unavailable ("))
    assert snap["stores"][0]["name"] == "Database"
    assert {s["name"] for s in snap["stores"]} >= {"Evidence artifacts", "HTTP transactions"}
    assert snap["migration"]["head"] and snap["migration"]["up_to_date"] in (True, False)
    assert snap["backup"] == {"configured": False}
    text = str(snap)
    assert "redis://" not in text and "postgresql://" not in text


class _Item(SimpleNamespace):
    pass


def _client(groups):
    containers = [_Item(name=f"c-{lab}", status="running",
                        labels={operations.LABEL_LAB_ID: lab, "nidavellir.role": "victim"})
                  for lab in groups]
    networks = [_Item(labels={operations.LABEL_LAB_ID: lab}) for lab in groups]
    volumes = [_Item(attrs={"Labels": {operations.LABEL_LAB_ID: groups[0]}})]
    lister = lambda items: SimpleNamespace(list=lambda **_: items)  # noqa: E731
    return SimpleNamespace(containers=lister(containers), networks=lister(networks),
                           volumes=lister(volumes), images=lister([]))


def test_inventory_groups_by_arena_and_classifies_against_records():
    live, gone, broken = _arena("active"), _arena("destroyed"), _arena("failed")
    stranger = "not-ours-" + uuid.uuid4().hex[:8]
    records = {r["id"]: r for r in Database().list_deployments()}
    inv = operations.docker_inventory(_client([live, gone, broken, stranger]), records)
    states = {a["lab_id"]: (a["state"], a["reclaim"]) for a in inv["arenas"]}
    assert states[live] == ("live", None)
    assert states[gone] == ("leftover", "reclaim_orphan")
    assert states[broken] == ("failed", "destroy_lab")
    assert states[stranger] == ("unknown", None)
    assert inv["orphans"] == 2 and inv["unknown"] == 1
    first = next(a for a in inv["arenas"] if a["lab_id"] == live)
    assert first["containers"][0]["role"] == "victim" and first["networks"] == 1
    assert first["volumes"] == 1


def test_reclaim_uses_the_destroy_paths_and_refuses_live_or_unknown(monkeypatch):
    calls = []
    monkeypatch.setattr(api.reclaim_orphan, "delay", lambda lab, actor: calls.append(("reclaim", lab)))
    monkeypatch.setattr(api.destroy_lab, "delay", lambda lab: calls.append(("destroy", lab)))
    operator = client("operator")
    gone, broken, live = _arena("destroyed"), _arena("failed"), active_arena()
    assert operator.post(f"/system/operations/reclaim/{gone}").json()["path"] == "reclaim_orphan"
    assert operator.post(f"/system/operations/reclaim/{broken}").json()["path"] == "destroy_lab"
    assert calls == [("reclaim", gone), ("destroy", broken)]
    r = operator.post(f"/system/operations/reclaim/{live}")
    assert r.status_code == 409 and "live" in r.text
    r = operator.post("/system/operations/reclaim/someone-elses-arena")
    assert r.status_code == 409 and "another installation" in r.text
    assert operator.post("/system/operations/reclaim/bad%20id").status_code == 422
    assert client("agent").post(f"/system/operations/reclaim/{gone}").status_code == 403
    events = Database().list_events(lab_id=gone, limit=5, types=("orphan_reclaim_requested",))
    assert events and events[0]["payload"]["path"] == "reclaim_orphan"


def test_reclaim_task_destroys_by_label_only_for_destroyed_arenas(monkeypatch):
    destroyed = []

    class FakeProvider:
        def destroy(self, lab_id):
            destroyed.append(lab_id)
            return {"success": True}

    import providers.docker_local as docker_local

    monkeypatch.setattr(docker_local, "DockerLocalProvider", FakeProvider)
    gone, live = _arena("destroyed"), active_arena()
    assert tasks.reclaim_orphan(live)["success"] is False
    assert tasks.reclaim_orphan("unknown-arena")["success"] is False
    assert tasks.reclaim_orphan(gone, actor="admin") == {"success": True}
    assert destroyed == [gone]
    event = Database().list_events(lab_id=gone, limit=1, types=("orphan_reclaimed",))[0]
    assert event["payload"]["success"] is True and event["actor"] == "admin"


def test_worker_heartbeat_shows_a_dead_worker_on_the_next_read():
    import readiness

    store = {}
    redis = SimpleNamespace(get=lambda key: store.get(key))
    assert operations.heartbeat(redis)["alive"] is False  # never beat
    store[readiness.HEARTBEAT_KEY] = str(time.time())
    assert operations.heartbeat(redis)["alive"] is True
    store[readiness.HEARTBEAT_KEY] = str(time.time() - readiness.HEARTBEAT_MAX_AGE_SECONDS - 5)
    assert operations.heartbeat(redis)["alive"] is False  # stopped beating


def test_store_usage_is_bounded_and_backup_reads_a_mounted_directory(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").write_bytes(b"1234")
    (tmp_path / "y.bin").write_bytes(b"12")
    usage = operations.dir_usage(tmp_path, now=1e9)
    assert usage == {"bytes": 6, "files": 2, "present": True, "truncated": False}
    assert operations.dir_usage(tmp_path / "missing", now=1e9)["present"] is False
    monkeypatch.setenv("NIDAVELLIR_BACKUP_DIR", str(tmp_path))
    info = operations.backup()
    assert info["configured"] is True and info["latest"] in {"a", "y.bin"} and info["count"] == 2
