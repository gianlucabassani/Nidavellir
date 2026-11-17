"""
LLM Dockerfile synthesis with a verified-build loop (M1-3, ADR-0008 tier-3 /
Repo2Run). The prompt build + extraction are pure; the verified loop is driven
with fake model + build callables (no network, no docker).
"""
import dockerfile_synth as ds
import pytest

_INTRO = {"language": "python", "base_runtime": {"kind": "python", "version": "3.12"},
          "declared_ports": [5000], "run_hints": ["flask run"], "readme_excerpt": "run with flask"}

_GOOD_DF = "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\nEXPOSE 5000\nCMD [\"flask\", \"run\", \"--host=0.0.0.0\"]"


# --- prompt building ----------------------------------------------------------

def test_build_messages_grounds_on_introspection():
    system, messages = ds.build_messages(_INTRO)
    assert "FROM" in system and "foreground" in system.lower()
    content = messages[0]["content"]
    assert "python" in content and "5000" in content


def test_build_messages_appends_failure_history_on_retry():
    history = [{"dockerfile": "FROM bad\n", "error": "unable to find image 'bad'"}]
    _, messages = ds.build_messages(_INTRO, history)
    content = messages[0]["content"]
    assert "Attempt 1 FAILED" in content
    assert "unable to find image 'bad'" in content
    assert "Fix the specific error" in content


# --- Dockerfile extraction ----------------------------------------------------

def test_extract_plain_dockerfile():
    assert ds.extract_dockerfile(_GOOD_DF).startswith("FROM python:3.12-slim")


def test_extract_strips_fences_and_prose():
    reply = "Here is your Dockerfile:\n```dockerfile\n" + _GOOD_DF + "\n```\nEnjoy!"
    out = ds.extract_dockerfile(reply)
    assert out.startswith("FROM python") and "```" not in out and "Enjoy" not in out


def test_extract_anchors_to_first_from_dropping_preamble():
    out = ds.extract_dockerfile("Sure, here it is:\n" + _GOOD_DF)
    assert out.startswith("FROM python:3.12-slim")


def test_extract_errors_on_no_dockerfile():
    with pytest.raises(ds.SynthError):
        ds.extract_dockerfile("I cannot help with that.")
    with pytest.raises(ds.SynthError):
        ds.extract_dockerfile("")


# --- the verified-build loop --------------------------------------------------

def test_loop_returns_first_green_build():
    calls = []
    result = ds.synthesize_verified_dockerfile(
        complete_fn=lambda s, m: _GOOD_DF,
        build_fn=lambda df: (calls.append(df) or (True, "Successfully built")),
        introspection=_INTRO,
    )
    assert result["ok"] is True
    assert result["dockerfile"].startswith("FROM python")
    assert len(result["attempts"]) == 1 and result["attempts"][0]["ok"]
    assert len(calls) == 1  # stopped after the first green build


def test_loop_retries_on_failure_then_succeeds():
    # first build fails, model fixes it on the 2nd attempt (fed the error)
    replies = iter(["FROM broken\nCMD x", _GOOD_DF])
    builds = iter([(False, "step 1: image 'broken' not found"), (True, "ok")])
    seen_prompts = []

    def complete(system, messages):
        seen_prompts.append(messages[0]["content"])
        return next(replies)

    result = ds.synthesize_verified_dockerfile(
        complete, lambda df: next(builds), _INTRO, max_attempts=3,
    )
    assert result["ok"] is True
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["ok"] is False and result["attempts"][1]["ok"] is True
    # the 2nd prompt was told about the 1st failure (rollback → fix loop)
    assert "FAILED" in seen_prompts[1] and "broken" in seen_prompts[1]


def test_loop_gives_up_after_max_attempts_without_claiming_success():
    result = ds.synthesize_verified_dockerfile(
        lambda s, m: "FROM broken", lambda df: (False, "boom"), _INTRO, max_attempts=2,
    )
    assert result["ok"] is False
    assert result["dockerfile"] is None      # never returns an unverified Dockerfile
    assert len(result["attempts"]) == 2
    assert "2 attempt" in result["error"]


def test_loop_stops_on_unparseable_reply():
    # a reply with no Dockerfile ends the loop as a failed attempt (no infinite retry)
    result = ds.synthesize_verified_dockerfile(
        lambda s, m: "sorry, cannot", lambda df: (True, "ok"), _INTRO, max_attempts=3,
    )
    assert result["ok"] is False
    assert len(result["attempts"]) == 1
    assert "no usable Dockerfile" in result["attempts"][0]["error"]


# --- POST /repos/synthesize-dockerfile endpoint -------------------------------

from fastapi.testclient import TestClient  # noqa: E402


class _FakeProvider:
    def __init__(self, results):
        self._results = iter(results)

    def verify_build_dockerfile(self, repo, ref, dockerfile_text, **kw):
        return next(self._results)


@pytest.fixture()
def synth_client(monkeypatch):
    import api
    import auth
    import config
    import model_chat
    from database import Database

    monkeypatch.setattr(config, "ALLOW_SOURCE_BUILD", True)
    monkeypatch.setattr("database.Database.get_decrypted_model_credential",
                        lambda self, owner: {"provider": "anthropic", "model": "c", "api_key": "k"})
    # a repo with NO deterministic build → synthesis applies
    monkeypatch.setattr(api.repo_introspect, "introspect",
                        lambda repo, ref=None: {"repo": repo, "language": "python",
                                                "build_system": "language-native",
                                                "declared_ports": [5000], "indicators": ["requirements.txt"]})
    monkeypatch.setattr(model_chat, "complete_chat", lambda *a, **k: _GOOD_DF)
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="synth-op", role="operator")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c, monkeypatch, api


def test_synthesize_endpoint_returns_verified_dockerfile(synth_client):
    c, monkeypatch, api = synth_client
    monkeypatch.setattr(api, "get_provider", lambda name=None: _FakeProvider([(True, "Successfully built")]))
    r = c.post("/repos/synthesize-dockerfile", json={"repo": "https://github.com/o/p"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["synthesized"] is True
    assert body["dockerfile"].startswith("FROM python")
    assert body["build_plan"]["strategy"] == "buildpack"  # language-native python → buildpack (none-executable)


def test_synthesize_endpoint_reports_failure_after_retries(synth_client):
    c, monkeypatch, api = synth_client
    monkeypatch.setattr(api, "get_provider",
                        lambda name=None: _FakeProvider([(False, "err1"), (False, "err2")]))
    r = c.post("/repos/synthesize-dockerfile", json={"repo": "https://github.com/o/p", "max_attempts": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and body["dockerfile"] is None
    assert len(body["attempts"]) == 2


def test_synthesize_endpoint_short_circuits_when_repo_ships_dockerfile(synth_client):
    c, monkeypatch, api = synth_client
    monkeypatch.setattr(api.repo_introspect, "introspect",
                        lambda repo, ref=None: {"repo": repo, "build_system": "dockerfile",
                                                "indicators": ["Dockerfile"]})
    r = c.post("/repos/synthesize-dockerfile", json={"repo": "https://github.com/o/p"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["synthesized"] is False and body["ok"] is True
    assert "no synthesis needed" in body["note"]


def test_synthesize_endpoint_requires_model_and_gate(monkeypatch):
    import api
    import auth
    import config
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="synth-op2", role="operator")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    # gate off → 409
    monkeypatch.setattr(config, "ALLOW_SOURCE_BUILD", False)
    assert c.post("/repos/synthesize-dockerfile", json={"repo": "https://github.com/o/p"}).status_code == 409
    # gate on but no model → 409
    monkeypatch.setattr(config, "ALLOW_SOURCE_BUILD", True)
    monkeypatch.setattr("database.Database.get_decrypted_model_credential", lambda self, o: None)
    assert c.post("/repos/synthesize-dockerfile", json={"repo": "https://github.com/o/p"}).status_code == 409


def test_synthesize_endpoint_is_operator_only():
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name="synth-agent", role="agent")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    assert c.post("/repos/synthesize-dockerfile", json={"repo": "https://github.com/o/p"}).status_code == 403
