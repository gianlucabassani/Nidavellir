import { useEffect, useRef, useState } from "react";
import type { ArenaData } from "../types";
import { getJson, postJson } from "../api";
import { DisabledReason, Empty, Panel } from "../ui";
import "./terminal.css";

// UX-13 (FR-18): the operator's shell and log tail for one arena node.

type LogLine = { ts: string; text: string };
const TAIL = 200;
const KEEP = 2000;
const FOLLOW_MS = 3000;

function epoch(ts: string) {
  const value = Date.parse(ts);
  return Number.isNaN(value) ? null : Math.floor(value / 1000);
}

/** Bounded, tailing log view: the first read is audited server-side; follow
 * reads ask only for lines after the last one seen. */
export function NodeLogs({ arena }: { arena: ArenaData }) {
  const active = arena.state === "active";
  const [node, setNode] = useState(arena.nodes[0]?.name || "");
  const [lines, setLines] = useState<LogLine[]>([]);
  const [error, setError] = useState("");
  const [follow, setFollow] = useState(true);
  const [atBottom, setAtBottom] = useState(true);
  const box = useRef<HTMLPreElement>(null);
  const since = useRef<number | null>(null);
  useEffect(() => {
    setLines([]);
    setError("");
    since.current = null;
  }, [arena.id, node]);
  useEffect(() => {
    if (!active || !node) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      const params = new URLSearchParams({ tail: String(TAIL) });
      if (since.current != null) params.set("since", String(since.current));
      try {
        const data = await getJson<{ lines: LogLine[] }>(
          `/api/console/arenas/${encodeURIComponent(arena.id)}/nodes/${encodeURIComponent(node)}/logs?${params}`,
        );
        if (stopped) return;
        setError("");
        if (data.lines.length) {
          const last = epoch(data.lines[data.lines.length - 1].ts);
          if (last != null) since.current = last;
          setLines((previous) => [...previous, ...data.lines].slice(-KEEP));
        }
      } catch (reason) {
        if (!stopped)
          setError(
            reason instanceof Error ? reason.message : "Log read failed",
          );
      }
      if (!stopped && follow && document.visibilityState === "visible")
        timer = setTimeout(read, FOLLOW_MS);
    };
    void read();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [arena.id, node, active, follow]);
  useEffect(() => {
    if (atBottom && box.current)
      box.current.scrollTop = box.current.scrollHeight;
  }, [lines, atBottom]);
  return (
    <Panel
      eyebrow="LOGS"
      title="Node log tail"
      className="terminal-panel"
      aside={
        <label className="terminal-follow">
          <input
            type="checkbox"
            checked={follow}
            onChange={(event) => setFollow(event.target.checked)}
          />
          Follow
        </label>
      }
    >
      {!active ? (
        <Empty
          title="Logs need a running arena"
          detail="Container logs are read live from the node; this arena is not active."
        />
      ) : (
        <>
          <div className="terminal-bar">
            <label>
              Node
              <select
                value={node}
                onChange={(event) => setNode(event.target.value)}
              >
                {arena.nodes.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <small>
              Last {TAIL} lines, then new lines every {FOLLOW_MS / 1000} s ·
              secrets redacted · opening a tail is audited
            </small>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <pre
            ref={box}
            className="terminal-output"
            aria-label={`Log of ${node}`}
            aria-live="off"
            tabIndex={0}
            onScroll={(event) => {
              const el = event.currentTarget;
              setAtBottom(
                el.scrollHeight - el.scrollTop - el.clientHeight < 24,
              );
            }}
          >
            {lines.length
              ? lines.map((line, index) => (
                  <span key={index} className="terminal-line">
                    <time>{line.ts.slice(11, 19)}</time> {line.text}
                    {"\n"}
                  </span>
                ))
              : "No log lines yet."}
          </pre>
          {!atBottom && (
            <button
              type="button"
              className="button button-outline"
              onClick={() => setAtBottom(true)}
            >
              Jump to newest
            </button>
          )}
        </>
      )}
    </Panel>
  );
}

type Entry = {
  id: number;
  node: string;
  command: string;
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
  error?: string;
  ms?: number;
  pending: boolean;
};

/** A line-oriented shell over the arena's `exec` action: every command is a
 * budgeted, audited span. Not a PTY: no interactive programs. */
export function OperatorShell({ arena }: { arena: ArenaData }) {
  const capability = arena.capabilities?.exec;
  const reason =
    arena.state !== "active"
      ? "The shell needs a running arena."
      : capability && capability.state !== "ready"
        ? `Exec is ${capability.state.replaceAll("_", " ")}${capability.reason ? `: ${capability.reason}` : ""}.`
        : "";
  const [node, setNode] = useState(
    arena.nodes.find((item) => item.foothold)?.name ||
      arena.nodes[0]?.name ||
      "",
  );
  const [command, setCommand] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const box = useRef<HTMLPreElement>(null);
  const counter = useRef(0);
  const history = entries.map((entry) => entry.command);
  const busy = entries.some((entry) => entry.pending);
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [entries]);
  async function run(event: React.FormEvent) {
    event.preventDefault();
    const text = command.trim();
    if (!text || reason || busy) return;
    const id = ++counter.current;
    const started = performance.now();
    setEntries((previous) =>
      [...previous, { id, node, command: text, pending: true }].slice(-200),
    );
    setCommand("");
    setCursor(null);
    let patch: Partial<Entry>;
    try {
      const result = await postJson<{
        exit_code: number | null;
        stdout: string;
        stderr: string;
      }>(`/api/console/arenas/${encodeURIComponent(arena.id)}/exec`, {
        node,
        command: text,
      });
      patch = result;
    } catch (failure) {
      patch = {
        error: failure instanceof Error ? failure.message : "Command failed",
      };
    }
    const ms = Math.round(performance.now() - started);
    setEntries((previous) =>
      previous.map((entry) =>
        entry.id === id ? { ...entry, ...patch, ms, pending: false } : entry,
      ),
    );
  }
  function recall(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    if (!history.length) return;
    event.preventDefault();
    const next =
      event.key === "ArrowUp"
        ? Math.max(0, (cursor ?? history.length) - 1)
        : (cursor ?? history.length) + 1;
    if (next >= history.length) {
      setCursor(null);
      setCommand("");
    } else {
      setCursor(next);
      setCommand(history[next]);
    }
  }
  return (
    <Panel eyebrow="SHELL" title="Operator shell" className="terminal-panel">
      <div className="terminal-bar">
        <label>
          Node
          <select
            value={node}
            onChange={(event) => setNode(event.target.value)}
          >
            {arena.nodes.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
                {item.foothold ? " (foothold)" : ""}
              </option>
            ))}
          </select>
        </label>
        <small>
          Each command is one exec action: budgeted, audited and on the
          timeline. No interactive programs.
        </small>
      </div>
      <pre
        ref={box}
        className="terminal-output"
        aria-label="Shell transcript"
        aria-live="polite"
        tabIndex={0}
      >
        {entries.length
          ? entries.map((entry) => (
              <span key={entry.id}>
                <span className="terminal-command">
                  {entry.node} $ {entry.command}
                </span>
                {"\n"}
                {entry.pending ? (
                  <span className="terminal-meta">running…{"\n"}</span>
                ) : (
                  <>
                    {entry.stdout}
                    {entry.stderr && (
                      <span className="terminal-error">{entry.stderr}</span>
                    )}
                    {entry.error && (
                      <span className="terminal-error">
                        {entry.error}
                        {"\n"}
                      </span>
                    )}
                    <span className="terminal-meta">
                      {entry.error
                        ? "not run"
                        : `exit ${entry.exit_code ?? "?"}`}{" "}
                      · {entry.ms} ms{"\n"}
                    </span>
                  </>
                )}
              </span>
            ))
          : "Commands and their output appear here."}
      </pre>
      <form className="terminal-form" onSubmit={run}>
        <input
          aria-label="Command"
          value={command}
          placeholder={reason ? "" : "id; uname -a"}
          onChange={(event) => setCommand(event.target.value)}
          onKeyDown={recall}
          disabled={Boolean(reason)}
          aria-describedby={reason ? "shell-why" : undefined}
          maxLength={4096}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          className="button"
          type="submit"
          disabled={Boolean(reason) || busy || !command.trim()}
          aria-describedby="shell-why"
        >
          {busy ? "Running…" : "Run"}
        </button>
      </form>
      {(reason || busy || !command.trim()) && (
        <DisabledReason id="shell-why">
          {reason ||
            (busy
              ? "Wait for the running command to finish."
              : "Enter a command to run.")}
        </DisabledReason>
      )}
    </Panel>
  );
}

export function TerminalWorkbench({ arena }: { arena: ArenaData }) {
  return (
    <div className="terminal-grid">
      <OperatorShell arena={arena} />
      <NodeLogs arena={arena} />
    </div>
  );
}
