"""
JSON-mode plumbing for ``model_chat`` (used by the scenario generator).

Verifies that ``json_mode=True`` reaches the provider correctly — OpenAI-compatible
providers (incl. Gemini's OpenAI endpoint) get ``response_format`` and Anthropic
gets the assistant ``{`` prefill with the brace re-emitted — by stubbing the shared
``_streaming_post`` (so no real HTTP) and capturing the request body.
"""
import json

import model_chat


class _FakeStream:
    """Minimal stand-in for a streaming requests.Response."""

    def __init__(self, lines):
        self._lines = lines
        self.headers = {}
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    def close(self):
        pass


def _capture(monkeypatch, lines):
    captured = {}

    def fake_streaming_post(url, headers, body):
        captured["url"] = url
        captured["body"] = body
        yield "open", _FakeStream(lines)

    monkeypatch.setattr(model_chat, "_streaming_post", fake_streaming_post)
    return captured


def test_openai_compat_json_mode_sets_response_format(monkeypatch):
    line = "data: " + json.dumps({"choices": [{"delta": {"content": "{}"}}]})
    captured = _capture(monkeypatch, [line, "data: [DONE]"])
    out = model_chat.complete_chat(
        "gemini", "gemini-2.0-flash", "k",
        "Output ONLY JSON.", [{"role": "user", "content": "hi"}], json_mode=True,
    )
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert out == "{}"


def test_openai_compat_no_json_mode_omits_response_format(monkeypatch):
    line = "data: " + json.dumps({"choices": [{"delta": {"content": "hello"}}]})
    captured = _capture(monkeypatch, [line, "data: [DONE]"])
    model_chat.complete_chat(
        "openai", "gpt", "k", "sys", [{"role": "user", "content": "hi"}],
    )
    assert "response_format" not in captured["body"]


def test_anthropic_json_mode_prefills_brace_and_reemits(monkeypatch):
    # The provider continues from the prefilled "{" — it returns the rest only.
    cont = json.dumps({"type": "content_block_delta", "delta": {"text": '"ok": 1}'}})
    captured = _capture(monkeypatch, ["data: " + cont])
    out = model_chat.complete_chat(
        "anthropic", "claude", "k", "sys", [{"role": "user", "content": "hi"}],
        json_mode=True,
    )
    assert captured["body"]["messages"][-1] == {"role": "assistant", "content": "{"}
    assert out == '{"ok": 1}'          # leading brace re-emitted → complete JSON
    assert json.loads(out) == {"ok": 1}


def test_anthropic_no_json_mode_has_no_prefill(monkeypatch):
    cont = json.dumps({"type": "content_block_delta", "delta": {"text": "plain reply"}})
    captured = _capture(monkeypatch, ["data: " + cont])
    out = model_chat.complete_chat(
        "anthropic", "claude", "k", "sys", [{"role": "user", "content": "hi"}],
    )
    assert captured["body"]["messages"][-1]["role"] == "user"
    assert out == "plain reply"
