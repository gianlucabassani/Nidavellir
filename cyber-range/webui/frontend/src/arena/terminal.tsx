import { useEffect, useRef, useState } from "react";
import type { ArenaData } from "../types";
import { getJson } from "../api";
import { Empty, Panel } from "../ui";
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

export function TerminalWorkbench({ arena }: { arena: ArenaData }) {
  return (
    <div className="terminal-grid">
      <NodeLogs arena={arena} />
    </div>
  );
}
