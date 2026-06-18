"""
Model backends for the CyberGuard reference harness — bring your own model.

One harness, any model. Two backends cover the field:
  - `anthropic`        — the native Anthropic SDK (keeps Claude's adaptive
                          thinking). Key: ANTHROPIC_API_KEY.
  - openai-compatible  — the OpenAI SDK pointed at any `base_url`. This single
                          backend drives DeepSeek, Gemini (its OpenAI endpoint),
                          local models (Ollama / vLLM / LM Studio), and OpenAI.

Each backend converts the gateway's MCP tools to its provider's tool/function
schema and runs a small tool-use loop, calling a shared `dispatch(name, args)`
(provided by agent.py) to actually invoke the gateway. The model + key are
yours — CyberGuard ships no AI (see VISION.md scope boundary).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# --- provider presets --------------------------------------------------------
# `kind` picks the backend; `provider` is the logical label the platform shows
# (drives the model bubble's logo). Override any field with CLI flags / env.


@dataclass
class Preset:
    kind: str               # "anthropic" | "openai"
    provider: str           # UI label / logo key
    model: str              # default model id (override with --model)
    base_url: str | None = None
    key_env: str = ""
    key_optional: bool = False  # local models often need no key


PRESETS: dict[str, Preset] = {
    "anthropic": Preset("anthropic", "anthropic", "claude-opus-4-8",
                        None, "ANTHROPIC_API_KEY"),
    "openai": Preset("openai", "openai", "gpt-4o",
                     "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "deepseek": Preset("openai", "deepseek", "deepseek-chat",
                       "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "gemini": Preset("openai", "gemini", "gemini-2.0-flash",
                     "https://generativelanguage.googleapis.com/v1beta/openai/",
                     "GEMINI_API_KEY"),
    "ollama": Preset("openai", "ollama", "llama3.1",
                     "http://localhost:11434/v1", "OLLAMA_API_KEY", key_optional=True),
    # generic local / self-hosted OpenAI-compatible server — set --base-url
    # (or LLM_BASE_URL) and --model.
    "local": Preset("openai", "local", "",
                    None, "LLM_API_KEY", key_optional=True),
}

PROVIDER_CHOICES = sorted(PRESETS)


class BackendError(RuntimeError):
    pass


def make_backend(args):
    """Resolve --provider/--model/--base-url/--api-key into a ready backend."""
    if args.provider not in PRESETS:
        raise BackendError(f"unknown provider {args.provider!r}; choose one of {PROVIDER_CHOICES}")
    p = PRESETS[args.provider]
    model = args.model or p.model
    base_url = args.base_url or os.getenv("LLM_BASE_URL") or p.base_url
    api_key = args.api_key or (os.getenv(p.key_env) if p.key_env else None)

    if not model:
        raise BackendError(f"provider {args.provider!r} needs a model — pass --model")
    if p.kind == "openai" and not base_url:
        raise BackendError(f"provider {args.provider!r} needs a base URL — pass --base-url "
                           "(or set LLM_BASE_URL)")
    if not api_key and not p.key_optional:
        raise BackendError(f"missing API key — set {p.key_env} or pass --api-key "
                           f"(bring your own key for {args.provider!r})")

    if p.kind == "anthropic":
        return AnthropicBackend(model=model, provider=p.provider, api_key=api_key)
    return OpenAICompatibleBackend(
        model=model, provider=p.provider, base_url=base_url,
        api_key=api_key or "not-needed",  # local servers ignore the key
    )


# --- Anthropic (native) ------------------------------------------------------


class AnthropicBackend:
    """Native Anthropic SDK with adaptive thinking — the Claude-optimized path."""

    def __init__(self, model: str, provider: str, api_key: str | None):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - import guard
            raise BackendError("the 'anthropic' package is required for --provider anthropic "
                               "(pip install -r requirements.txt)") from e
        self.model = model
        self.provider = provider
        self.label = f"{provider}:{model}"
        self._client = anthropic.AsyncAnthropic(api_key=api_key)  # key from env if None

    @staticmethod
    def _tools(mcp_tools) -> list[dict]:
        return [
            {"name": t.name, "description": t.description or "",
             "input_schema": t.inputSchema or {"type": "object", "properties": {}}}
            for t in mcp_tools
        ]

    async def run(self, *, system, kickoff, mcp_tools, dispatch, max_steps, log) -> None:
        tools = self._tools(mcp_tools)
        messages: list[dict] = [{"role": "user", "content": kickoff}]
        for step in range(1, max_steps + 1):
            log.step(step, max_steps)
            resp = await self._client.messages.create(
                model=self.model, max_tokens=8192, system=system,
                thinking={"type": "adaptive", "display": "summarized"},
                tools=tools, messages=messages,
            )
            if resp.stop_reason == "refusal":
                log.note("the model declined this request — stopping")
                return
            for block in resp.content:
                if block.type == "thinking" and block.thinking:
                    log.thinking(block.thinking)
                elif block.type == "text" and block.text.strip():
                    log.say(block.text.strip())
            # Replay the full assistant turn (thinking blocks included) verbatim —
            # the API requires it to continue an adaptive-thinking conversation.
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                log.note("engagement complete — the agent ended its turn")
                return
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    text, is_error = await dispatch(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": text, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        log.note(f"reached the {max_steps}-step cap — stopping")


# --- OpenAI-compatible (DeepSeek / Gemini / local / OpenAI) ------------------


class OpenAICompatibleBackend:
    """OpenAI Chat Completions + function calling against any `base_url`.

    Works with any server that speaks the OpenAI tool-calling API: DeepSeek,
    Gemini's OpenAI-compatible endpoint, Ollama / vLLM / LM Studio, OpenAI.
    (The chosen model must support tool/function calling.)
    """

    def __init__(self, model: str, provider: str, base_url: str, api_key: str):
        try:
            from openai import AsyncOpenAI
        except ImportError as e:  # pragma: no cover - import guard
            raise BackendError("the 'openai' package is required for OpenAI-compatible "
                               "providers (pip install -r requirements.txt)") from e
        self.model = model
        self.provider = provider
        self.label = f"{provider}:{model}"
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    @staticmethod
    def _tools(mcp_tools) -> list[dict]:
        return [
            {"type": "function", "function": {
                "name": t.name, "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            }}
            for t in mcp_tools
        ]

    async def run(self, *, system, kickoff, mcp_tools, dispatch, max_steps, log) -> None:
        tools = self._tools(mcp_tools)
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": kickoff},
        ]
        for step in range(1, max_steps + 1):
            log.step(step, max_steps)
            resp = await self._client.chat.completions.create(
                model=self.model, messages=messages, tools=tools,
                tool_choice="auto", max_tokens=2048,
            )
            msg = resp.choices[0].message
            if msg.content and msg.content.strip():
                log.say(msg.content.strip())

            assistant: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            messages.append(assistant)

            if not msg.tool_calls:
                log.note("engagement complete — the agent ended its turn")
                return
            for tc in msg.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                text, _is_error = await dispatch(tc.function.name, arguments)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
        log.note(f"reached the {max_steps}-step cap — stopping")
