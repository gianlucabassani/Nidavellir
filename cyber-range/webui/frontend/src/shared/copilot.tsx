// UX-20 (ADR-0020): the Copilot panel. Docked at the right under the top bar,
// resizable, and open across navigation. Chats are stored per operator. Each
// answer may come with "Looked up" chips (read-only lookups the server ran) and
// at most one proposed change. A proposal is applied here, by the operator,
// through the console's own endpoint; the copilot never acts.
import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { getJson, jsonRequest, postJson } from "../api";
import { DisabledReason, formatObserved } from "../ui";
import { Icon } from "../shell/icons";
import "./copilot.css";

type Connection = {
  configured: boolean;
  provider?: string;
  model?: string;
  base_url?: string;
};
type ChatSummary = { id: string; title: string; updated_at: string };
type Proposal = {
  id: number | null;
  action: "extend_arena" | "stop_research" | "resume_research";
  arena_id: string;
  seconds?: number;
  reason?: string;
  state: "pending" | "applied" | "denied" | "failed";
  detail?: string | null;
};
type Item =
  | { kind: "user"; key: string; text: string; page?: string | null }
  | {
      kind: "lookup";
      key: string;
      name: string;
      ok: boolean;
      pending?: boolean;
    }
  | { kind: "answer"; key: string; text: string; failed?: boolean }
  | { kind: "proposal"; key: string; proposal: Proposal }
  | { kind: "notice"; key: string; text: string };
type StoredMessage = {
  id: number;
  role: "user" | "lookup" | "assistant" | "proposal";
  text: string | null;
  data: Record<string, unknown> | null;
  created_at: string;
};

const PROVIDERS = [
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
const WIDTH_KEY = "nidavellir-copilot-width";
const LOOKUP_LABEL: Record<string, string> = {
  arena_summary: "arena summary",
  arena_activity: "arena activity",
  findings: "findings",
  agents_board: "agents board",
  search: "search",
};
const STARTERS: {
  icon: Parameters<typeof Icon>[0]["name"];
  title: string;
  text: string;
}[] = [
  {
    icon: "pulse",
    title: "How is this arena going?",
    text: "Summarise this arena: activity, failures, budget and findings.",
  },
  {
    icon: "agent",
    title: "What are my agents doing?",
    text: "Which agents are connected right now and what is each doing?",
  },
  {
    icon: "flag",
    title: "What needs my decision?",
    text: "Which findings still need my verdict, most severe first?",
  },
  {
    icon: "clock",
    title: "Will the budget last?",
    text: "At the current pace, will this arena's budget last until it expires?",
  },
];

function describe(proposal: Proposal) {
  if (proposal.action === "extend_arena")
    return `Extend ${proposal.arena_id} by ${(proposal.seconds || 0) / 60} minutes`;
  if (proposal.action === "stop_research")
    return `Stop research on ${proposal.arena_id}`;
  return `Resume research on ${proposal.arena_id}`;
}

/** Restricted rendering of model text: no HTML; **bold**, `code`, and links
 *  only to this console. Everything else stays plain text. */
function Rich({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, index) => {
        const parts: ReactNode[] = [];
        const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
        let last = 0;
        let match: RegExpExecArray | null;
        while ((match = pattern.exec(line))) {
          if (match.index > last) parts.push(line.slice(last, match.index));
          const token = match[0];
          if (token.startsWith("**"))
            parts.push(<b key={match.index}>{token.slice(2, -2)}</b>);
          else if (token.startsWith("`"))
            parts.push(<code key={match.index}>{token.slice(1, -1)}</code>);
          else {
            const [, label, href] = /\[([^\]]+)\]\(([^)]+)\)/.exec(token) || [];
            parts.push(
              href && /^\/console(\/|\?|$)/.test(href) ? (
                <a key={match.index} href={href}>
                  {label}
                </a>
              ) : (
                <span key={match.index}>{label}</span>
              ),
            );
          }
          last = match.index + token.length;
        }
        if (last < line.length) parts.push(line.slice(last));
        const bullet = /^\s*[-*]\s+/.test(line);
        return (
          <Fragment key={index}>
            {bullet ? (
              <span className="cp-li">
                {parts.map((p, i) =>
                  i === 0 && typeof p === "string"
                    ? p.replace(/^\s*[-*]\s+/, "")
                    : p,
                )}
              </span>
            ) : (
              <span className="cp-line">{parts.length ? parts : " "}</span>
            )}
          </Fragment>
        );
      })}
    </>
  );
}

function pageContext() {
  const path = window.location.pathname;
  const arena = path.startsWith("/console/arena/")
    ? decodeURIComponent(path.slice("/console/arena/".length))
    : null;
  const heading =
    document.querySelector("#main h1")?.textContent?.trim() || "This page";
  const tab = new URLSearchParams(window.location.search).get("tab");
  return {
    label: arena ? `Arena ${heading}${tab ? ` · ${tab}` : ""}` : heading,
    arena_id: arena,
  };
}

function fromStored(messages: StoredMessage[]): Item[] {
  return messages.map((message) => {
    const key = `m${message.id}`;
    if (message.role === "user")
      return {
        kind: "user",
        key,
        text: message.text || "",
        page:
          (message.data?.page as { label?: string } | undefined)?.label || null,
      };
    if (message.role === "lookup")
      return {
        kind: "lookup",
        key,
        name: String(message.data?.name || "lookup"),
        ok: message.data?.ok !== false,
      };
    if (message.role === "proposal") {
      const data = message.data || {};
      return {
        kind: "proposal",
        key,
        proposal: {
          ...(data.proposal as Omit<Proposal, "id" | "state">),
          id: message.id,
          state: (data.state as Proposal["state"]) || "pending",
          detail: (data.detail as string | null) || null,
        },
      };
    }
    return { kind: "answer", key, text: message.text || "" };
  });
}

export function CopilotPanel() {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"chat" | "history" | "connect">("chat");
  const [connection, setConnection] = useState<Connection | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [chatId, setChatId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [chats, setChats] = useState<ChatSummary[] | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [withPage, setWithPage] = useState(false);
  const [page, setPage] = useState(pageContext);
  const [width, setWidth] = useState(() => {
    try {
      return Math.max(
        380,
        Math.min(760, Number(localStorage.getItem(WIDTH_KEY)) || 460),
      );
    } catch {
      return 460;
    }
  });
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);

  useEffect(() => setSlot(document.getElementById("assistant-slot")), []);
  const refreshConnection = useCallback(async () => {
    setConnectionError("");
    try {
      setConnection(await getJson<Connection>("/api/model-connection"));
    } catch (error) {
      setConnectionError(
        error instanceof Error ? error.message : "Model status unavailable",
      );
    }
  }, []);
  useEffect(() => {
    void refreshConnection();
  }, [refreshConnection]);
  // The page context follows navigation while the panel stays open.
  useEffect(() => {
    const sync = () => window.setTimeout(() => setPage(pageContext()), 120);
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  useEffect(() => {
    if (!open) return;
    setPage(pageContext());
    composer.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [items, busy]);
  useEffect(() => () => request.current?.abort(), []);

  function close() {
    setOpen(false);
    launcher.current?.focus();
  }
  async function loadChats() {
    try {
      setChats(
        (await getJson<{ chats: ChatSummary[] }>("/api/console/copilot/chats"))
          .chats,
      );
    } catch {
      setChats([]);
    }
  }
  async function openChat(id: string) {
    request.current?.abort();
    const chat = await getJson<{
      id: string;
      title: string;
      messages: StoredMessage[];
    }>(`/api/console/copilot/chats/${encodeURIComponent(id)}`);
    setChatId(chat.id);
    setTitle(chat.title);
    setItems(fromStored(chat.messages));
    setView("chat");
  }
  function newChat() {
    request.current?.abort();
    setChatId(null);
    setTitle("");
    setItems([]);
    setView("chat");
    window.setTimeout(() => composer.current?.focus(), 0);
  }
  async function deleteChat(id: string) {
    await jsonRequest(
      "DELETE",
      `/api/console/copilot/chats/${encodeURIComponent(id)}`,
    );
    if (id === chatId) newChat();
    await loadChats();
  }

  async function send(text: string) {
    text = text.trim();
    if (!text || busy || !connection?.configured) return;
    setInput("");
    setBusy(true);
    const controller = new AbortController();
    request.current = controller;
    const sentPage = withPage ? pageContext() : null;
    const stamp = Date.now();
    setItems((current) => [
      ...current,
      { kind: "user", key: `u${stamp}`, text, page: sentPage?.label || null },
    ]);
    let answerKey = "";
    try {
      let id = chatId;
      if (!id) {
        const chat = await postJson<{ id: string; title: string }>(
          "/api/console/copilot/chats",
          {},
        );
        id = chat.id;
        setChatId(id);
      }
      const response = await fetch(
        `/api/console/copilot/chats/${encodeURIComponent(id)}/turn`,
        {
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
            text,
            ...(sentPage ? { page: sentPage } : {}),
          }),
        },
      );
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname)}`,
        );
        return;
      }
      if (!response.ok || !response.body)
        throw Error(`Copilot request failed (${response.status})`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";
      answerKey = `a${stamp}`;
      const handle = (event: Record<string, unknown>) => {
        if (event.type === "lookup")
          setItems((current) => [
            ...current,
            {
              kind: "lookup",
              key: `l${stamp}-${current.length}`,
              name: String(event.name),
              ok: event.ok !== false,
            },
          ]);
        else if (event.type === "delta") {
          answer += String(event.text || "");
          setItems((current) => {
            const rest = current.filter((item) => item.key !== answerKey);
            return [
              ...rest,
              {
                kind: "answer",
                key: answerKey,
                text: answer.replace(/```nv-proposal[\s\S]*$/, "").trimEnd(),
              },
            ];
          });
        } else if (event.type === "done") {
          setItems((current) => {
            const rest = current.filter((item) => item.key !== answerKey);
            const next: Item[] = [
              ...rest,
              {
                kind: "answer",
                key: answerKey,
                text: String(event.text || ""),
              },
            ];
            if (event.proposal)
              next.push({
                kind: "proposal",
                key: `p${stamp}`,
                proposal: event.proposal as Proposal,
              });
            if (event.notice)
              next.push({
                kind: "notice",
                key: `n${stamp}`,
                text: String(event.notice),
              });
            return next;
          });
        } else if (event.type === "error") {
          setItems((current) => [
            ...current.filter((item) => item.key !== answerKey),
            {
              kind: "answer",
              key: answerKey,
              text: String(event.message || "The copilot failed."),
              failed: true,
            },
          ]);
        }
      };
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline: number;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (line) handle(JSON.parse(line));
        }
      }
      if (buffer.trim()) handle(JSON.parse(buffer));
      if (!title) setTitle(text.length > 58 ? `${text.slice(0, 57)}…` : text);
    } catch (error) {
      setItems((current) => [
        ...current.filter((item) => item.key !== answerKey),
        {
          kind: "answer",
          key: `e${stamp}`,
          text: controller.signal.aborted
            ? "Stopped. Ask again whenever you like."
            : error instanceof Error
              ? error.message
              : "The copilot failed.",
          failed: true,
        },
      ]);
    } finally {
      if (request.current === controller) request.current = null;
      setBusy(false);
    }
  }

  async function decide(proposal: Proposal, apply: boolean) {
    const update = (state: Proposal["state"], detail: string | null) =>
      setItems((current) =>
        current.map((item) =>
          item.kind === "proposal" && item.proposal.id === proposal.id
            ? { ...item, proposal: { ...item.proposal, state, detail } }
            : item,
        ),
      );
    let state: Proposal["state"] = "denied";
    let detail: string | null = null;
    if (apply) {
      const arena = encodeURIComponent(proposal.arena_id);
      try {
        if (proposal.action === "extend_arena")
          await postJson(`/api/console/arenas/${arena}/extend`, {
            seconds: proposal.seconds,
          });
        else
          await postJson(`/api/console/arenas/${arena}/research-gate`, {
            action: proposal.action === "stop_research" ? "stop" : "resume",
            reason:
              `Applied from a copilot proposal: ${proposal.reason || describe(proposal)}`.slice(
                0,
                500,
              ),
          });
        state = "applied";
        detail = `Applied at ${new Date().toLocaleTimeString()}`;
      } catch (error) {
        state = "failed";
        detail =
          error instanceof Error ? error.message : "The action was refused";
      }
    }
    update(state, detail);
    if (proposal.id != null)
      try {
        await postJson(
          `/api/console/copilot/proposals/${proposal.id}/decision`,
          {
            state,
            ...(detail ? { detail } : {}),
          },
        );
      } catch {
        /* the action's own result is what matters; the record can lag */
      }
  }

  function startResize(event: React.PointerEvent) {
    event.preventDefault();
    const move = (moveEvent: PointerEvent) =>
      setWidth(
        Math.max(
          380,
          Math.min(
            Math.min(760, window.innerWidth - 80),
            window.innerWidth - moveEvent.clientX,
          ),
        ),
      );
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setWidth((current) => {
        try {
          localStorage.setItem(WIDTH_KEY, String(current));
        } catch {
          /* storage may be unavailable */
        }
        return current;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  const ready = !!connection?.configured;
  const launcherButton = (
    <button
      ref={launcher}
      type="button"
      className="assistant-launcher"
      aria-expanded={open}
      aria-controls="copilot-panel"
      aria-label="Copilot"
      title={
        ready
          ? `Copilot: ${connection?.provider} / ${connection?.model}`
          : "Copilot: no model connected"
      }
      onClick={() => (open ? close() : setOpen(true))}
    >
      <Icon name="sparkles" />
      <span className="assistant-launcher-label">Copilot</span>
      <i
        className={`assistant-dot ${ready ? "connected" : connection || connectionError ? "missing" : "checking"}`}
        aria-hidden="true"
      />
    </button>
  );

  return (
    <>
      {slot ? createPortal(launcherButton, slot) : launcherButton}
      {open && (
        <>
          <div className="cp-scrim" onClick={close} aria-hidden="true" />
          <aside
            id="copilot-panel"
            className="cp"
            aria-label="Copilot"
            style={{ ["--cp-w" as string]: `${width}px` }}
          >
            <div
              className="cp-grip"
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize copilot"
              onPointerDown={startResize}
            />
            <header className="cp-bar">
              <span className="cp-mark" aria-hidden="true">
                <Icon name="sparkles" size={13} />
              </span>
              <div className="cp-tt">
                <b>Copilot</b>
                <small>
                  {view === "chat" && title
                    ? title
                    : ready
                      ? `${connection?.model} · your connection`
                      : "No model connected"}
                </small>
              </div>
              <div className="cp-tools">
                <button
                  type="button"
                  aria-label="Chats"
                  title="Chats"
                  aria-pressed={view === "history"}
                  onClick={() => {
                    if (view === "history") setView("chat");
                    else {
                      setView("history");
                      void loadChats();
                    }
                  }}
                >
                  <Icon name="clock" size={14} />
                </button>
                <button
                  type="button"
                  aria-label="New chat"
                  title="New chat"
                  onClick={newChat}
                >
                  <Icon name="plus" size={14} />
                </button>
                <button
                  type="button"
                  aria-label="Model connection"
                  title="Model connection"
                  aria-pressed={view === "connect"}
                  onClick={() =>
                    setView(view === "connect" ? "chat" : "connect")
                  }
                >
                  <Icon name="gear" size={14} />
                </button>
                <button
                  type="button"
                  aria-label="Close copilot"
                  title="Close"
                  onClick={close}
                >
                  <Icon name="x" size={14} />
                </button>
              </div>
            </header>
            {view === "connect" ? (
              <ConnectionForm
                connection={connection}
                error={connectionError}
                onSaved={async () => {
                  await refreshConnection();
                  setView("chat");
                }}
              />
            ) : view === "history" ? (
              <div className="cp-hist">
                {chats == null ? (
                  <p className="cp-quiet">Loading your chats…</p>
                ) : chats.length ? (
                  <ul>
                    {chats.map((chat) => (
                      <li
                        key={chat.id}
                        className={chat.id === chatId ? "on" : ""}
                      >
                        <button
                          type="button"
                          onClick={() => void openChat(chat.id)}
                        >
                          <span>{chat.title}</span>
                          <small>{formatObserved(chat.updated_at)}</small>
                        </button>
                        <button
                          type="button"
                          className="cp-del"
                          aria-label={`Delete chat: ${chat.title}`}
                          title="Delete"
                          onClick={() => void deleteChat(chat.id)}
                        >
                          <Icon name="x" size={12} />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="cp-quiet">
                    No chats yet. Your conversations are kept here.
                  </p>
                )}
                <div className="cp-planned">
                  <span className="feature-tag">Planned</span> An agent inbox
                  chat that collects alerts and finding briefs.
                </div>
              </div>
            ) : (
              <>
                <div
                  className="cp-log"
                  ref={log}
                  role="log"
                  aria-label="Copilot messages"
                  aria-busy={busy}
                >
                  {!items.length && (
                    <div className="cp-empty">
                      <div className="label">Ask about this console</div>
                      <h3>What do you want to know?</h3>
                      <p>
                        Answers come from your own model, which can read arenas,
                        agents, findings and evaluations. Changes are proposed;
                        nothing runs until you apply it.
                      </p>
                      <div className="cp-starters">
                        {STARTERS.map((starter) => (
                          <button
                            key={starter.title}
                            type="button"
                            disabled={!ready}
                            onClick={() => void send(starter.text)}
                          >
                            <Icon name={starter.icon} />
                            <b>{starter.title}</b>
                            <small>{starter.text}</small>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {groupItems(items).map((group) =>
                    group.kind === "lookups" ? (
                      <div key={group.key} className="cl cl-a">
                        <span className="who" aria-hidden="true">
                          <Icon name="sparkles" size={12} />
                        </span>
                        <div className="looks">
                          {group.items.map((item) => (
                            <span
                              key={item.key}
                              className={`look ${item.ok ? "" : "bad"}`}
                            >
                              <Icon name={item.ok ? "check" : "x"} size={11} />
                              Looked up {LOOKUP_LABEL[item.name] || item.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <Message
                        key={group.item.key}
                        item={group.item}
                        busy={busy}
                        onDecide={decide}
                      />
                    ),
                  )}
                  {busy &&
                    !items.some(
                      (item) =>
                        item.kind === "answer" && item.key.startsWith("a"),
                    ) && (
                      <div className="cl cl-a">
                        <span className="who" aria-hidden="true">
                          <Icon name="sparkles" size={12} />
                        </span>
                        <p
                          className="cp-dots"
                          role="status"
                          aria-label="The copilot is answering"
                        >
                          <i />
                          <i />
                          <i />
                        </p>
                      </div>
                    )}
                </div>
                <form
                  className="cp-input"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void send(input);
                  }}
                >
                  <div className="cp-ctx">
                    {withPage ? (
                      <span className="chip on">
                        <Icon name="target" size={12} />
                        {page.label}
                        <button
                          type="button"
                          aria-label="Stop sending this page"
                          onClick={() => setWithPage(false)}
                        >
                          <Icon name="x" size={11} />
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="chip add"
                        onClick={() => setWithPage(true)}
                      >
                        <Icon name="plus" size={12} />
                        Add this page as context
                      </button>
                    )}
                    <span className="cp-quiet">
                      {withPage
                        ? "Sent with your next message"
                        : "Nothing from this page is sent"}
                    </span>
                  </div>
                  <div className="cp-box">
                    <textarea
                      ref={composer}
                      rows={1}
                      maxLength={4000}
                      value={input}
                      disabled={!ready}
                      onChange={(event) => setInput(event.target.value)}
                      placeholder={
                        ready
                          ? "Ask, or describe what you want to change…"
                          : "Connect a model to ask questions"
                      }
                      aria-label="Message"
                      onKeyDown={(event) => {
                        if (
                          event.key === "Enter" &&
                          !event.shiftKey &&
                          !event.nativeEvent.isComposing
                        ) {
                          event.preventDefault();
                          void send(input);
                        }
                      }}
                    />
                    {busy ? (
                      <button
                        type="button"
                        className="cp-send stop"
                        aria-label="Stop"
                        onClick={() => request.current?.abort()}
                      >
                        <Icon name="x" size={15} />
                      </button>
                    ) : (
                      <button
                        type="submit"
                        className="cp-send"
                        aria-label="Send message"
                        disabled={!ready || !input.trim()}
                      >
                        <Icon name="arrow" size={15} />
                      </button>
                    )}
                  </div>
                  {!ready ? (
                    <DisabledReason id="cp-why">
                      No model is connected.{" "}
                      <button
                        type="button"
                        className="inline-action"
                        onClick={() => setView("connect")}
                      >
                        Connect one
                      </button>
                      .
                    </DisabledReason>
                  ) : (
                    <p className="cp-quiet">
                      Enter to send · Shift+Enter for a new line · answers can
                      be wrong; check before you act
                    </p>
                  )}
                </form>
              </>
            )}
          </aside>
        </>
      )}
    </>
  );
}

type Group =
  | { kind: "lookups"; key: string; items: Extract<Item, { kind: "lookup" }>[] }
  | { kind: "one"; item: Item };

function groupItems(items: Item[]): Group[] {
  const out: Group[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (item.kind === "lookup") {
      if (last && last.kind === "lookups") last.items.push(item);
      else out.push({ kind: "lookups", key: item.key, items: [item] });
    } else out.push({ kind: "one", item });
  }
  return out;
}

function Message({
  item,
  busy,
  onDecide,
}: {
  item: Item;
  busy: boolean;
  onDecide: (proposal: Proposal, apply: boolean) => void;
}) {
  if (item.kind === "user")
    return (
      <div className="cl cl-u">
        <span className="who" aria-hidden="true">
          You
        </span>
        <div className="txt">
          {item.text}
          {item.page && (
            <small className="cp-sent-page">with page: {item.page}</small>
          )}
        </div>
      </div>
    );
  if (item.kind === "notice")
    return (
      <p className="cp-notice" role="note">
        {item.text}
      </p>
    );
  if (item.kind === "proposal") {
    const p = item.proposal;
    return (
      <div className="cl cl-a">
        <span className="who" aria-hidden="true">
          <Icon name="sparkles" size={12} />
        </span>
        <div className={`cp-prop ${p.state}`}>
          <div className="cp-prop-head">
            <span className="label">Proposed change</span>
            <span
              className={`status status-${p.state === "applied" ? "success" : p.state === "failed" ? "danger" : p.state === "denied" ? "muted" : "warning"}`}
            >
              <i aria-hidden="true" />
              {p.state === "pending" ? "waiting for you" : p.state}
            </span>
          </div>
          <b>{describe(p)}</b>
          {p.reason && <p>{p.reason}</p>}
          {p.state === "pending" ? (
            <div className="cp-prop-acts">
              <button
                type="button"
                className="button button-gold"
                disabled={busy}
                onClick={() => onDecide(p, true)}
              >
                <Icon name="check" size={14} /> Apply
              </button>
              <button
                type="button"
                className="button button-outline"
                disabled={busy}
                onClick={() => onDecide(p, false)}
              >
                Deny
              </button>
              <small>Runs as you, only when you apply it.</small>
            </div>
          ) : (
            <p className="cp-quiet">
              {p.detail || (p.state === "denied" ? "Nothing was changed." : "")}
            </p>
          )}
        </div>
      </div>
    );
  }
  if (item.kind === "answer")
    return (
      <div className={`cl cl-a ${item.failed ? "failed" : ""}`}>
        <span className="who" aria-hidden="true">
          <Icon name={item.failed ? "x" : "sparkles"} size={12} />
        </span>
        <div className="txt cp-rich">
          <Rich text={item.text} />
        </div>
      </div>
    );
  return null;
}

function ConnectionForm({
  connection,
  error,
  onSaved,
}: {
  connection: Connection | null;
  error: string;
  onSaved: () => Promise<void>;
}) {
  const [provider, setProvider] = useState(connection?.provider || "openai");
  const [model, setModel] = useState(connection?.model || "");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(connection?.base_url || "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(error);
  return (
    <form
      className="cp-connect"
      onSubmit={async (event) => {
        event.preventDefault();
        if (saving) return;
        setSaving(true);
        setMessage("");
        try {
          await jsonRequest("PUT", "/api/model-connection", {
            provider,
            model: model.trim(),
            api_key: key,
            base_url: baseUrl.trim() || null,
          });
          setKey("");
          await onSaved();
        } catch (reason) {
          setMessage(
            reason instanceof Error
              ? reason.message
              : "Connection could not be saved",
          );
        } finally {
          setSaving(false);
        }
      }}
    >
      <div className="label">Your model connection</div>
      <p className="cp-quiet">
        {connection?.configured
          ? `Connected: ${connection.provider} / ${connection.model}. Save to change it.`
          : "The copilot uses your own model and key. The key is stored encrypted and never shown again."}
      </p>
      {message && (
        <p className="form-error" role="alert">
          {message}
        </p>
      )}
      <label>
        Provider
        <select
          value={provider}
          onChange={(event) => setProvider(event.target.value)}
        >
          {PROVIDERS.map((item) => (
            <option key={item}>{item}</option>
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
      <div className="cp-connect-acts">
        <button type="submit" className="button button-gold" disabled={saving}>
          {saving ? "Saving…" : "Save connection"}
        </button>
        <a className="inline-action" href="/console/settings">
          More in settings
        </a>
      </div>
    </form>
  );
}
