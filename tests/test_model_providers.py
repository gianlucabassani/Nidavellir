"""
Companion model-provider breadth tests (BACKLOG P3-4).

Covers the OpenAI-compatible base resolver (`model_verify.openai_base`) — the
new OpenRouter / HuggingFace presets and the generic `NIDAVELLIR_MODEL_BASE_URL`
override that revives `local`/`custom` — plus verify routing. This is the OPERATOR
companion path; the BYO-agent path is unaffected.
"""
import model_verify


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_named_presets_resolve():
    assert model_verify.openai_base("openrouter") == "https://openrouter.ai/api/v1"
    assert model_verify.openai_base("huggingface") == "https://router.huggingface.co/v1"
    assert model_verify.openai_base("openai") == "https://api.openai.com/v1"


def test_generic_base_url_override(monkeypatch):
    # local/custom have no preset -> resolve from the env override.
    monkeypatch.delenv("NIDAVELLIR_MODEL_BASE_URL", raising=False)
    assert model_verify.openai_base("local") is None
    assert model_verify.openai_base("custom") is None
    monkeypatch.setenv("NIDAVELLIR_MODEL_BASE_URL", "http://vllm.internal:8000/v1")
    assert model_verify.openai_base("local") == "http://vllm.internal:8000/v1"
    assert model_verify.openai_base("custom") == "http://vllm.internal:8000/v1"


def test_verify_routes_openrouter_with_bearer(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Resp(200)

    monkeypatch.setattr(model_verify.requests, "get", fake_get)
    out = model_verify.verify_credential("openrouter", "anthropic/claude-3.5", "sk-or-xxx")
    assert out["verified"] is True and out["checked"] is True
    assert seen["url"] == "https://openrouter.ai/api/v1/models"
    assert seen["headers"]["Authorization"] == "Bearer sk-or-xxx"


def test_verify_huggingface_rejects_bad_key(monkeypatch):
    monkeypatch.setattr(model_verify.requests, "get", lambda url, headers=None, timeout=None: _Resp(401))
    out = model_verify.verify_credential("huggingface", "meta-llama/x", "hf_bad")
    assert out["verified"] is False and out["checked"] is True


def test_verify_local_unchecked_without_override(monkeypatch):
    monkeypatch.delenv("NIDAVELLIR_MODEL_BASE_URL", raising=False)
    out = model_verify.verify_credential("local", "some-model", "k")
    assert out["checked"] is False
    assert "NIDAVELLIR_MODEL_BASE_URL" in out["detail"]


def test_verify_local_checked_with_override(monkeypatch):
    monkeypatch.setenv("NIDAVELLIR_MODEL_BASE_URL", "http://host:1234/v1")
    monkeypatch.setattr(model_verify.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(200))
    out = model_verify.verify_credential("local", "m", "k")
    assert out["verified"] is True and out["checked"] is True


def test_verify_per_call_base_url_wins_over_preset(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        return _Resp(200)

    monkeypatch.setattr(model_verify.requests, "get", fake_get)
    # openrouter HAS a preset, but a per-connection base_url overrides it.
    model_verify.verify_credential("openrouter", "m", "k", base_url="https://gw.internal/v1")
    assert seen["url"] == "https://gw.internal/v1/models"
