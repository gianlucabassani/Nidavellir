"""NV-03 durable job, authorization, confinement contract and recovery tests."""
import io
import tarfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy")

import poc_execution  # noqa: E402
from database import Database  # noqa: E402


def _active_docker_arena(db, arena_id, *, outputs=None):
    db.create_deployment(
        arena_id, arena_id, "custom", provider="docker-local",
        effective_provider="docker-local", expires_at=datetime.now() + timedelta(hours=1),
    )
    db.update_deployment(arena_id, status="deploying")
    db.update_deployment(
        arena_id, status="active",
        outputs=outputs or {
            "node_jump_name": "nv-jump", "node_jump_ssh_command": "docker exec nv-jump sh",
            "node_web_name": "nv-web", "node_web_private_ip": "172.30.0.2",
            "node_web_ports": {"80": "49000"},
        },
    )
    return arena_id


def _create_job(
    db, arena_id, *, key="poc-key-0001", digest=None, principal="operator",
    target_policy=None, limits=None,
):
    payload, actual_digest = poc_execution.canonical_payload("print('ok')\n", [])
    return db.create_poc_job(
        job_id=f"job-{key}", arena_id=arena_id, principal=principal,
        principal_role="operator", binding_stance=None, idempotency_key=key,
        input_digest=digest or actual_digest, payload=payload,
        runner_image="runner@test",
        target_node=target_policy and target_policy.get("node"),
        target_policy=target_policy, limits=limits or {"timeout_seconds": 5},
        deadline=datetime.now() + timedelta(minutes=1),
        max_arena_jobs=2, max_global_jobs=8,
    )


def test_input_identity_covers_exact_source_and_selected_file_bytes():
    first, digest = poc_execution.canonical_payload(
        "print('proof')\n", [{"path": "corpus/request.bin", "content": b"abc"}]
    )
    second, changed = poc_execution.canonical_payload(
        "print('proof')\n", [{"path": "corpus/request.bin", "content": b"abd"}]
    )
    assert digest.startswith("sha256:") and digest != changed
    assert first["files"][0]["sha256"].startswith("sha256:")
    assert second["files"][0]["bytes"] == 3
    with pytest.raises(ValueError, match="below"):
        poc_execution.canonical_payload("print(1)", [{"path": "../secret", "content": b"x"}])


def test_durable_admission_is_idempotent_conflict_safe_and_releases_slots():
    db = Database()
    arena = _active_docker_arena(db, "poc-db-admission")
    first, created = _create_job(db, arena)
    assert created is True and first["state"] == "queued"
    same, created = _create_job(db, arena)
    assert created is False and same["id"] == first["id"]
    with pytest.raises(ValueError, match="different input"):
        _create_job(db, arena, digest="sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="different input"):
        _create_job(db, arena, target_policy={"node": "web", "ip": "172.30.0.2"})
    with pytest.raises(ValueError, match="different input"):
        _create_job(db, arena, principal="another-agent")

    assert db.claim_poc_job(first["id"], "worker-1") is True
    assert db.claim_poc_job(first["id"], "worker-2") is False
    assert db.finish_poc_job(
        first["id"], state="succeeded", result={"stdout": "ok"},
        cleanup_state="complete",
    ) is True
    finished = db.get_poc_job(first["id"])
    assert finished["state"] == "succeeded" and finished["result"]["stdout"] == "ok"


def test_queued_cancel_is_terminal_and_never_claimed():
    db = Database()
    arena = _active_docker_arena(db, "poc-db-cancel")
    job, _ = _create_job(db, arena, key="poc-key-cancel")
    cancelled = db.request_cancel_poc_job(job["id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["cleanup_state"] == "not_started"
    assert db.claim_poc_job(job["id"], "late-worker") is False


def test_admission_rechecks_arena_after_destroy_transition():
    db = Database()
    arena = _active_docker_arena(db, "poc-admit-destroy")
    db.update_deployment(arena, status="destroying")
    with pytest.raises(ValueError, match="no longer active"):
        _create_job(db, arena, key="poc-admit-destroy")
    assert db.list_poc_jobs(arena) == []


def test_competing_admission_and_cancel_claim_are_atomic():
    db = Database()
    arena = _active_docker_arena(db, "poc-concurrent-" + uuid.uuid4().hex)

    def admit(index):
        try:
            return _create_job(db, arena, key=f"{arena}-{index}")[0]
        except ValueError as exc:
            assert "capacity" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        admitted = [job for job in pool.map(admit, range(6)) if job]
    assert len(admitted) == 2
    for job in admitted:
        with ThreadPoolExecutor(max_workers=2) as pool:
            claim = pool.submit(db.claim_poc_job, job["id"], "race-worker")
            cancel = pool.submit(db.request_cancel_poc_job, job["id"])
            claimed = claim.result()
            cancel.result()
        stored = db.get_poc_job(job["id"])
        assert stored["cancel_requested"]
        assert stored["state"] == ("running" if claimed else "cancelled")
        if claimed:
            db.finish_poc_job(job["id"], state="cancelled")


def test_reaper_retries_terminal_cleanup_and_expires_queued_jobs(monkeypatch):
    import tasks
    from models import PocJob

    db = Database()
    arena = _active_docker_arena(db, "poc-cleanup-retry")
    failed, _ = _create_job(db, arena, key="poc-cleanup-retry")
    db.claim_poc_job(failed["id"], "lost-worker")
    db.finish_poc_job(failed["id"], state="failed", cleanup_state="incomplete")
    queued, _ = _create_job(db, arena, key="poc-expired-queue")
    with db._session() as session:
        session.get(PocJob, queued["id"]).deadline = datetime.now() - timedelta(seconds=1)
        session.commit()
    cleaned = []
    monkeypatch.setattr(tasks.Orchestrator, "cleanup_poc_job",
                        lambda _self, job_id: cleaned.append(job_id) or {"success": True})
    monkeypatch.setattr(tasks.destroy_lab, "delay", lambda *_args: None)
    monkeypatch.setattr(tasks.run_poc_job, "delay", lambda *_args: None)
    monkeypatch.setattr(tasks.reset_arena, "delay", lambda *_args: None)
    tasks.reap_labs.run()
    assert failed["id"] in cleaned
    assert db.get_poc_job(failed["id"])["cleanup_state"] == "complete"
    assert db.get_poc_job(queued["id"])["state"] == "cancelled"
    assert not db.list_poc_cleanup_obligations()


@pytest.mark.parametrize("name,kind", [
    ("artifacts/link", tarfile.SYMTYPE),
    ("artifacts/hardlink", tarfile.LNKTYPE),
    ("artifacts/pipe", tarfile.FIFOTYPE),
    ("../escape", tarfile.REGTYPE),
    ("/absolute", tarfile.REGTYPE),
])
def test_artifact_collection_refuses_unsafe_entries(name, kind):
    from providers.docker_local import DockerLocalProvider

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = "/etc/passwd" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
        archive.addfile(info)

    class Api:
        def exec_create(self, *_args, **_kwargs):
            return {"Id": "artifact-reader"}

        def exec_start(self, *_args, **_kwargs):
            return iter([(raw.getvalue(), None)])

        def exec_inspect(self, *_args):
            return {"ExitCode": 0}

    class Client:
        api = Api()

    class Container:
        id = "untrusted-output"

    artifacts, error = DockerLocalProvider(client=Client())._poc_artifacts(Container())
    assert artifacts == [] and error


def test_api_submission_is_bound_target_scoped_idempotent_and_body_free(monkeypatch):
    from fastapi.testclient import TestClient
    import api
    import auth

    db = Database()
    arena = _active_docker_arena(db, "poc-api-arena")
    other = _active_docker_arena(db, "poc-api-other")
    key = auth.generate_api_key()
    db.create_api_key(auth.hash_api_key(key), "poc-agent", "agent")
    db.record_event(arena, "agent_binding", {
        "agent_name": "poc-agent", "stance": "attacker", "granted_by": "test",
    })
    client = TestClient(api.app, headers={"X-API-Key": key})
    queued = []
    monkeypatch.setattr(api.run_poc_job, "delay", lambda job_id: queued.append(job_id))

    body = {
        "source": "print('submission-secret')\n", "target_node": "web",
        "idempotency_key": "api-poc-key-1", "timeout_seconds": 5,
    }
    response = client.post(f"/arenas/{arena}/poc-jobs", json=body)
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    assert job["target_policy"]["node"] == "web"
    assert job["target_policy"]["raw_tcp"] == "unsupported"
    assert queued == [job["id"]]
    repeated = client.post(f"/arenas/{arena}/poc-jobs", json=body)
    assert repeated.status_code == 202 and repeated.json()["created"] is False
    assert client.get(f"/arenas/{other}/poc-jobs/{job['id']}").status_code == 404
    events = db.list_events(arena, types=("poc_job_submitted",))
    assert events and "submission-secret" not in str(events[0]["payload"])
    # Keep the process-wide test database free of active work for later reaper
    # tests. Production cleanup is exercised independently by the worker test.
    assert client.post(f"/arenas/{arena}/poc-jobs/{job['id']}/cancel").status_code == 200


def test_worker_records_digests_and_verified_cleanup(monkeypatch):
    import tasks

    db = Database()
    arena = _active_docker_arena(db, "poc-worker-success")
    job, _ = _create_job(db, arena, key="poc-key-worker")

    def fake_run(_self, _arena, _job, _payload, _target, _limits, cancel_check=None, start_guard=None):
        assert cancel_check() is False
        assert callable(start_guard)
        return {
            "success": True, "state": "succeeded", "exit_code": 0,
            "stdout": "proof", "stderr": "", "stdout_sha256": "sha256:" + "a" * 64,
            "stderr_sha256": "sha256:" + "b" * 64, "artifacts": [],
            "runner_image_id": "sha256:runner", "cleanup": {"success": True},
        }

    monkeypatch.setattr(tasks.Orchestrator, "run_poc", fake_run)
    result = tasks.run_poc_job.run(job["id"])
    assert result == {"success": True, "state": "succeeded"}
    stored = db.get_poc_job(job["id"])
    assert stored["cleanup_state"] == "complete"
    assert stored["runner_image_id"] == "sha256:runner"
    event = db.list_events(arena, types=("poc_job_finished",))[0]
    assert event["payload"]["stdout_sha256"] == "sha256:" + "a" * 64
    assert "proof" not in str(event["payload"])


def test_docker_runner_has_no_ip_network_and_relay_is_fixed_to_owned_target(monkeypatch):
    import config
    from providers.docker_local import DockerLocalProvider, LABEL_POC_JOB

    class Image:
        id = "sha256:runner-image"
        attrs = {"Os": "linux", "Architecture": "amd64"}

    class Images:
        def get(self, name):
            assert name == config.POC_RUNNER_IMAGE
            return Image()

    class Volume:
        def __init__(self, name, labels):
            self.name, self.labels, self.removed = name, labels, False

        def remove(self, force=False):
            self.removed = True

    class Volumes:
        def __init__(self):
            self.items = []

        def create(self, name, labels):
            value = Volume(name, labels)
            self.items.append(value)
            return value

        def list(self, filters):
            key, value = filters["label"].split("=", 1)
            return [v for v in self.items if not v.removed and v.labels.get(key) == value]

    class Container:
        def __init__(self, kwargs):
            self.id = f"container-{len(kwargs)}"
            self.kwargs = kwargs
            self.labels = kwargs["labels"]
            self.attrs = {"State": {"Status": "created", "ExitCode": 0, "OOMKilled": False}}
            self.removed = False

        def start(self):
            self.attrs["State"]["Status"] = "running"

        def reload(self):
            return None

        def logs(self, stdout=True, stderr=True):
            return b"proof\n" if stdout and not stderr else b""

        def exec_run(self, _command):
            class Result:
                exit_code = 0
                output = b"0"
            return Result()

        def get_archive(self, path):
            raise RuntimeError("not found")

        def kill(self):
            self.attrs["State"]["Status"] = "exited"

        def remove(self, force=False):
            self.removed = True

    class Containers:
        def __init__(self):
            self.items = []

        def create(self, **kwargs):
            value = Container(kwargs)
            self.items.append(value)
            return value

        def list(self, all=False, filters=None):
            key, value = filters["label"].split("=", 1)
            return [c for c in self.items if not c.removed and c.labels.get(key) == value]

    class Client:
        def __init__(self):
            self.images, self.volumes, self.containers = Images(), Volumes(), Containers()
            self.networks = Volumes()
            self.api = self.Api(self)

        class Api:
            class Stream:
                def __init__(self, client):
                    self._sock = self
                    self.client = client
                    self.data = b""

                def sendall(self, data):
                    self.data += data
                    assert b"main.py" in data and b".ready" in data

                def shutdown(self, _how):
                    self.client.containers.items[-1].attrs["State"]["Status"] = "exited"

                def recv(self, _size):
                    return b""

                def close(self):
                    return None

            def __init__(self, client):
                self.client = client
                self.commands = {}

            def exec_create(self, _container_id, command, **kwargs):
                assert command in (
                    ["tar", "-x", "-f", "-", "-C", "/workspace"],
                    ["/bin/tar", "-c", "-f", "-", "-C", "/workspace", "artifacts"],
                )
                assert kwargs["user"] == "65532:65532"
                if command[1] == "-x":
                    assert kwargs["stdin"] is True
                else:
                    assert kwargs["stdout"] is True and kwargs["stderr"] is True
                exec_id = "exec-input" if command[1] == "-x" else "exec-artifacts"
                self.commands[exec_id] = command
                return {"Id": exec_id}

            def exec_start(self, exec_id, **_kwargs):
                if exec_id == "exec-artifacts":
                    archive_bytes = io.BytesIO()
                    with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
                        info = tarfile.TarInfo("artifacts/proof.txt")
                        info.size = len(b"proof")
                        archive.addfile(info, io.BytesIO(b"proof"))
                    return iter([(archive_bytes.getvalue(), None)])
                return self.Stream(self.client)

            def exec_inspect(self, _exec_id):
                return {"ExitCode": 0}

    class Target:
        attrs = {"NetworkSettings": {"Networks": {
            "nidavellir-arena123-lab": {"IPAddress": "172.30.0.2"}
        }}}

        def reload(self):
            return None

    client = Client()
    provider = DockerLocalProvider(client=client)
    monkeypatch.setattr(provider, "_find_node_container", lambda *_args: Target())
    payload, _ = poc_execution.canonical_payload("print('proof')\n", [])
    outcome = provider.run_poc(
        "arena123-rest", "job-confined", payload,
        {"node": "web", "ip": "172.30.0.2", "port": 80, "scheme": "http"},
        {"timeout_seconds": 2, "memory_mb": 64, "cpu_millis": 250,
         "pids": 16, "workspace_bytes": 2 * 1024 * 1024},
    )
    assert outcome["success"] is True
    relay, runner = client.containers.items
    assert relay.kwargs["network"] == "nidavellir-arena123-lab"
    assert relay.kwargs["command"][-7:] == [
        "--host", "172.30.0.2", "--port", "80", "--scheme", "http", "--timeout", "2"
    ][-7:]
    assert runner.kwargs["network_mode"] == "none"
    assert runner.kwargs["network_disabled"] is True
    assert runner.kwargs["cap_drop"] == ["ALL"]
    assert runner.kwargs["read_only"] is True
    assert runner.kwargs["security_opt"] == ["no-new-privileges:true"]
    assert outcome["artifacts"][0]["path"] == "artifacts/proof.txt"
    assert outcome["artifacts"][0]["content_b64"] == "cHJvb2Y="
    assert all(c.removed for c in client.containers.items)
    assert all(v.removed for v in client.volumes.items)
    assert LABEL_POC_JOB in runner.labels


def test_docker_runner_preserves_early_cancel_terminal_state(monkeypatch):
    import config
    from providers.docker_local import DockerLocalProvider

    class Image:
        id = "sha256:runner-image"
        attrs = {"Os": "linux", "Architecture": "amd64"}

    class Images:
        def get(self, name):
            assert name == config.POC_RUNNER_IMAGE
            return Image()

    class EmptyResources:
        def list(self, **_kwargs):
            return []

    class Client:
        images = Images()
        containers = EmptyResources()
        volumes = EmptyResources()
        networks = EmptyResources()

    provider = DockerLocalProvider(client=Client())
    payload, _ = poc_execution.canonical_payload("print('never runs')\n", [])
    outcome = provider.run_poc(
        "arena-cancel", "job-early-cancel", payload, None,
        {"timeout_seconds": 2, "memory_mb": 64, "cpu_millis": 250,
         "pids": 16, "workspace_bytes": 2 * 1024 * 1024},
        cancel_check=lambda: True,
    )
    assert outcome["state"] == "cancelled"
    assert outcome["cancelled"] is True
    assert outcome["cleanup"]["success"] is True
