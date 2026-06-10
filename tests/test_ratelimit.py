"""
Tests for API rate limiting (SECURITY gap #7, ROADMAP Phase 1).

The limiter is disabled suite-wide via RATE_LIMIT_ENABLED=false (conftest);
these tests flip it on explicitly to prove the 429 path, then restore it.
"""
import pytest

pytest.importorskip("slowapi")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
from database import Database  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    import api

    class _FakeTask:
        def delay(self, *args, **kwargs):
            return None

    monkeypatch.setattr(api, "deploy_lab", _FakeTask())
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="rl-tests", role="admin")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


def test_limiter_disabled_for_the_suite():
    import api

    assert api.limiter.enabled is False


def test_deploy_returns_429_past_the_limit(client):
    import api

    api.limiter.reset()
    api.limiter.enabled = True
    try:
        codes = [
            client.post(
                "/deploy",
                json={"scenario": "basic_pentest", "instance_id": f"rl-{i}"},
            ).status_code
            for i in range(12)  # default RATE_LIMIT_DEPLOY = 10/minute
        ]
        assert codes[0] == 200
        assert 429 in codes
    finally:
        api.limiter.enabled = False
        api.limiter.reset()
