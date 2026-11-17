"""FR-07 (B12): /health is liveness; unauthenticated /ready reflects DB, Redis and
(docker-local, non-mock) a recent worker heartbeat.

The live Accept line — stopping Redis or PostgreSQL turns /ready to 503 within one
health-check interval — is modelled here by failing the probes; the container-level
check is an operator live gate.
"""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import readiness  # noqa: E402


class FakeRedis:
    def __init__(self, up=True):
        self.up = up
        self.store = {}

    def ping(self):
        if not self.up:
            raise ConnectionError("down")
        return True

    def get(self, key):
        if not self.up:
            raise ConnectionError("down")
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value


def _ok():
    return None


def _down():
    raise OSError("db down")


def test_ready_when_all_answer():
    r = FakeRedis()
    readiness.write_heartbeat(r, now=1000.0)
    ok, checks = readiness.check_readiness(_ok, lambda: r, require_worker=True, now=1010.0)
    assert ok and checks == {"database": "ok", "redis": "ok", "worker": "ok"}


@pytest.mark.parametrize("db, redis_up, beat_age, failing", [
    (_down, True, 1, "database"),
    (_ok, False, 1, "redis"),
    (_ok, True, None, "worker"),
    (_ok, True, readiness.HEARTBEAT_MAX_AGE_SECONDS + 1, "worker"),
])
def test_not_ready(db, redis_up, beat_age, failing):
    r = FakeRedis()
    if beat_age is not None:
        readiness.write_heartbeat(r, now=1000.0)
    r.up = redis_up
    ok, checks = readiness.check_readiness(db, lambda: r, require_worker=True,
                                           now=1000.0 + (beat_age or 0))
    assert not ok and checks[failing] != "ok"


def test_worker_not_required_for_mock_or_other_providers():
    assert readiness.heartbeat_required("docker-local", mock_mode=False)
    assert not readiness.heartbeat_required("docker-local", mock_mode=True)
    assert not readiness.heartbeat_required("mock", mock_mode=False)
    ok, checks = readiness.check_readiness(_ok, FakeRedis, require_worker=False)
    assert ok and "worker" not in checks


@pytest.fixture()
def anon_client():
    import api

    return TestClient(api.app)


def test_ready_endpoint_is_unauthenticated_and_503_without_redis(anon_client, monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda url=None: FakeRedis(up=False))
    resp = anon_client.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready" and body["checks"]["database"] == "ok"
    assert "redis://" not in resp.text


def test_ready_endpoint_200_when_dependencies_answer(anon_client, monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda url=None: FakeRedis())
    resp = anon_client.get("/ready")
    assert resp.status_code == 200, resp.text  # MOCK_MODE: no worker beat required
    assert anon_client.get("/health").json() == {"status": "ok"}


def test_compose_healthcheck_uses_ready():
    from pathlib import Path

    import yaml

    base = yaml.safe_load((Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text())
    assert base["services"]["orchestrator"]["healthcheck"]["test"][-1].endswith("/ready")
