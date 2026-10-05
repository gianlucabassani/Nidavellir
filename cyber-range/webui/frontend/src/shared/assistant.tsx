import { useEffect, useRef, useState } from "react";
import { getJson, jsonRequest } from "../api";
import "./assistant.css";

type Connection = {
  configured: boolean;
  provider?: string;
  model?: string;
  base_url?: string;
};
type Message = {
  role: "user" | "assistant";
  content: string;
  failed?: boolean;
};
const providers = [
  "openai",
  "anthropic",
  "openrouter",
  "gemini",
  "deepseek",
  "huggingface",
  "ollama",
  "local",
  "custom",
];

export function ResearchAssistant({ arenaId }: { arenaId: string | null }) {
  const [open, setOpen] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [configure, setConfigure] = useState(false);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const history = useRef<Message[]>([]);
  const request = useRef<AbortController | null>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);

  async function refreshConnection(signal?: AbortSignal) {
    setConnectionError("");
    try {
      const value = await getJson<Connection>("/api/model-connection", signal);
      setConnection(value);
      if (value.configured) {
        setProvider(value.provider || "openai");
        setModel(value.model || "");
        setBaseUrl(value.base_url || "");
      }
    } catch (error) {
      if (!signal?.aborted)
        setConnectionError(
          error instanceof Error ? error.message : "Model status unavailable",
        );
    }
  }
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void refreshConnection(controller.signal);
    composer.current?.focus();
    return () => controller.abort();
  }, [open]);
  useEffect(() => {
    request.current?.abort();
    request.current = null;
    history.current = [];
    setMessages([]);
    setInput("");
    setBusy(false);
  }, [arenaId]);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages, open]);
  function close() {
    setOpen(false);
    setConfigure(false);
    setKey("");
    launcher.current?.focus();
  }
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open]);
  async function saveConnection(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setConnectionError("");
    try {
      await jsonRequest("PUT", "/api/model-connection", {
        provider,
        model: model.trim(),
        api_key: key,
        base_url: baseUrl.trim() || null,
      });
      setKey("");
      setConfigure(false);
      await refreshConnection();
    } catch (error) {
      setConnectionError(
        error instanceof Error
          ? error.message
          : "Connection could not be saved",
      );
    } finally {
      setSaving(false);
    }
  }
  async function send() {
    const text = input.trim();
    if (!text || busy || !connection?.configured) return;
    const controller = new AbortController();
    request.current = controller;
    const user: Message = { role: "user", content: text };
    const previous = history.current.slice(-28);
    setMessages((current) => [
      ...current,
      user,
      { role: "assistant", content: "" },
    ]);
    setInput("");
    setBusy(true);
    let reply = "";
    try {
      const response = await fetch("/api/copilot", {
        method: "POST",
        credentials: "same-origin",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken":
            document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
              ?.content || "",
        },
        body: JSON.stringify({
          arena_id: arenaId,
          messages: [...previous, user],
        }),
      });
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
        );
        throw Error("Session expired");
      }
      if (!response.ok)
        throw Error(`Assistant request failed (${response.status})`);
      if (!response.body) throw Error("No reply stream received");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        reply += decoder.decode(value, { stream: true });
        if (reply.length > 131072) {
          await reader.cancel();
          throw Error(
            "Reply exceeded the display limit. Try a narrower question.",
          );
        }
        if (request.current === controller)
          setMessages((current) => [
            ...current.slice(0, -1),
            { role: "assistant", content: reply },
          ]);
      }
      reply += decoder.decode();
      if (
        !reply.trim() ||
        /^\s*\[co-pilot\]/m.test(reply) ||
        reply.startsWith("[model]")
      )
        throw Error(reply || "The model returned an empty reply.");
      if (request.current === controller) {
        history.current = [
          ...previous,
          user,
          { role: "assistant", content: reply },
        ];
        setMessages((current) => [
          ...current.slice(0, -1),
          { role: "assistant", content: reply },
        ]);
      }
    } catch (error) {
      if (request.current === controller)
        setMessages((current) => [
          ...current.slice(0, -1),
          {
            role: "assistant",
            content: controller.signal.aborted
              ? "Reply stopped. You can send another question."
              : error instanceof Error
                ? error.message
                : "Assistant connection failed",
            failed: true,
          },
        ]);
    } finally {
      if (request.current === controller) {
        request.current = null;
        setBusy(false);
      }
    }
  }
  return (
    <>
      <button
        ref={launcher}
        className="assistant-launcher"
        type="button"
        aria-expanded={open}
        aria-controls="research-assistant"
        onClick={() => (open ? close() : setOpen(true))}
        aria-label="Research assistant"
        title="Research assistant"
      >
        <span aria-hidden="true">✧</span>
        <span className="assistant-launcher-label">Research assistant</span>
      </button>
      {open && (
        <aside
          id="research-assistant"
          className="research-assistant"
          aria-label="Research assistant"
        >
          <header>
            <div>
              <strong>Research assistant</strong>
              <small>
                {arenaId
                  ? `Arena ${arenaId.slice(0, 8)} · advisory support`
                  : "General research support"}
              </small>
            </div>
            <button
              type="button"
              aria-label="Close research assistant"
              onClick={close}
            >
              ×
            </button>
          </header>
          <div className="assistant-model">
            <span>
              {connection?.configured
                ? `${connection.provider} / ${connection.model}`
                : connection
                  ? "No model connected"
                  : "Checking model connection…"}
            </span>
            <button
              type="button"
              onClick={() => {
                setConfigure(!configure);
                setKey("");
              }}
            >
              {connection?.configured ? "Change" : "Connect model"}
            </button>
          </div>
          {connectionError && (
            <div className="assistant-error" role="alert">
              {connectionError}{" "}
              <button type="button" onClick={() => void refreshConnection()}>
                Retry status
              </button>
            </div>
          )}
          {configure && (
            <form className="assistant-connection" onSubmit={saveConnection}>
              <label>
                Provider
                <select
                  aria-label="Provider"
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                >
                  {providers.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Model
                <input
                  required
                  maxLength={128}
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="Your model identifier"
                />
              </label>
              <label>
                API key
                <input
                  type="password"
                  autoComplete="off"
                  maxLength={512}
                  required={!["ollama", "local", "custom"].includes(provider)}
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                />
              </label>
              <label>
                Endpoint URL
                <input
                  type="url"
                  required={["local", "custom"].includes(provider)}
                  maxLength={512}
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  placeholder="Optional provider endpoint"
                />
              </label>
              <button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save connection"}
              </button>
              <a href="/console/settings">Connection settings ↗</a>
            </form>
          )}
          <div
            className="assistant-log"
            ref={log}
            aria-label="Conversation"
            aria-busy={busy}
          >
            {!messages.length && (
              <div className="assistant-empty">
                <strong>Support alongside your work.</strong>
                <p>
                  Ask about the arena status, plan a test, or interpret
                  observations. Your connected model provides advice.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setInput(
                      arenaId
                        ? "Summarize this arena's status and suggest what I should inspect next."
                        : "Help me plan a reproducible vulnerability research session.",
                    );
                    composer.current?.focus();
                  }}
                >
                  Suggest next steps ↗
                </button>
              </div>
            )}
            {messages.map((message, index) => (
              <div
                className={`assistant-message ${message.role}${message.failed ? " failed" : ""}`}
                key={index}
              >
                <small>
                  {message.role === "user"
                    ? "YOU"
                    : message.failed
                      ? "CONNECTION"
                      : "ASSISTANT"}
                </small>
                <p>{message.content || "Thinking…"}</p>
              </div>
            ))}
          </div>
          <div className="assistant-progress" role="status">
            {busy
              ? "Receiving reply…"
              : connectionError && !connection
                ? "Model status unavailable."
                : !connection
                  ? "Checking model connection…"
                  : !connection.configured
                    ? "Connect a model to ask questions."
                    : messages.length
                      ? "Conversation kept while you switch Arena tools."
                      : "Ready for your question."}
          </div>
          <form
            className="assistant-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <textarea
              ref={composer}
              rows={2}
              maxLength={8000}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about your research…"
              aria-label="Message to research assistant"
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <div>
              <button
                type="button"
                disabled={busy || !messages.length}
                onClick={() => {
                  history.current = [];
                  setMessages([]);
                }}
              >
                Clear chat
              </button>
              {busy ? (
                <button type="button" onClick={() => request.current?.abort()}>
                  Stop reply
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!connection?.configured || !input.trim()}
                >
                  Send ↗
                </button>
              )}
            </div>
          </form>
        </aside>
      )}
    </>
  );
}
