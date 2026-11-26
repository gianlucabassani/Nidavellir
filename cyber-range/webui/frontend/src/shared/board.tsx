import { useEffect, useMemo, useState } from "react";
import { getJson } from "../api";
import {
  Empty,
  ErrorState,
  formatObserved,
  Loading,
  PageHead,
  Panel,
  Status,
} from "../ui";

// OBS-06: what are my agents doing, across every live arena. The snapshot is
// pushed by the orchestrator after platform activity; idle detection uses the
// browser clock against each arena's last action.

type BoardArena = {
  id: string;
  name: string;
  scenario: string | null;
  state: string;
  expires_at: string | null;
  agents: { name: string; stance: string | null; paused: boolean }[];
  last_action: {
    name: string;
    actor: string;
    status: string;
    at: string;
  } | null;
  recent_actions: number;
  error_rate: number | null;
  budget: { remaining: number | null; cap: number | null; stopped: boolean };
  trial: {
    id: string;
    evaluation_id: string;
    state: string;
    seed: number;
  } | null;
};
type InboxItem = {
  key: string;
  kind:
    "arena_failed" | "verdict" | "budget_exhausted" | "stop" | "trial_finished";
  text: string;
  at: string | null;
  arena_id: string | null;
  arena_name?: string | null;
  evaluation_id?: string;
};
export type Board = {
  observed_at: string;
  idle_minutes: number;
  arenas: BoardArena[];
  inbox: InboxItem[];
};

const DISMISSED_KEY = "nidavellir-board-dismissed";

function parse(value: string | null | undefined) {
  if (!value) return 0;
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  const at = Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(at) ? 0 : at;
}

export function ago(value: string | null | undefined, now: number) {
  const at = parse(value);
  if (!at) return "never";
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
}

// UX-16: one board stream per tab, shared by the top bar, the board page and
// the Research summary. It opens with the first subscriber and closes with
// the last.
type BoardState = { board: Board | null; error: string; live: boolean };
let shared: BoardState = { board: null, error: "", live: false };
const subscribers = new Set<(state: BoardState) => void>();
let stream: EventSource | null = null;

function publish(next: Partial<BoardState>) {
  shared = { ...shared, ...next };
  subscribers.forEach((listener) => listener(shared));
}

function openBoard() {
  getJson<Board>("/api/console/board")
    .then((data) => {
      if (stream && !shared.board) publish({ board: data, error: "" });
    })
    .catch((reason: unknown) => {
      if (stream)
        publish({
          error:
            reason instanceof Error
              ? reason.message
              : "Agents board unavailable",
        });
    });
  stream = new EventSource("/api/console/board/stream");
  stream.onopen = () => publish({ live: true });
  stream.onerror = () => publish({ live: false });
  stream.addEventListener("board", (message) =>
    publish({ board: JSON.parse((message as MessageEvent).data), error: "" }),
  );
}

export function useBoard() {
  const [state, setState] = useState<BoardState>(shared);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    subscribers.add(setState);
    if (!stream) openBoard();
    else setState(shared);
    const clock = window.setInterval(() => setNow(Date.now()), 15000); // idle clock only
    return () => {
      subscribers.delete(setState);
      window.clearInterval(clock);
      if (!subscribers.size && stream) {
        stream.close();
        stream = null;
        shared = { board: null, error: "", live: false };
      }
    };
  }, []);
  return { ...state, now };
}

export function isIdle(arena: BoardArena, board: Board, now: number) {
  if (arena.state !== "active" || !arena.agents.length) return false;
  const last = parse(arena.last_action?.at) || 0;
  return !last || now - last > board.idle_minutes * 60000;
}

export function readDismissed(): string[] {
  try {
    return JSON.parse(localStorage.getItem(DISMISSED_KEY) || "[]");
  } catch {
    return [];
  }
}

// UX-16: the top bar's attention count follows dismissals made on the board.
const DISMISSED_EVENT = "nv:board-dismissed";

/** Dismiss inbox items in this browser; every open view follows. */
export function dismissInbox(keys: string[]): string[] {
  const next = [...new Set([...readDismissed(), ...keys])].slice(-500);
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
  } catch {
    /* storage may be unavailable */
  }
  window.dispatchEvent(new Event(DISMISSED_EVENT));
  return next;
}

export function onDismissedChange(listener: (keys: string[]) => void) {
  const handler = () => listener(readDismissed());
  window.addEventListener(DISMISSED_EVENT, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(DISMISSED_EVENT, handler);
    window.removeEventListener("storage", handler);
  };
}

function ArenaRows({
  board,
  now,
  limit,
}: {
  board: Board;
  now: number;
  limit?: number;
}) {
  const rows = useMemo(
    () =>
      [...board.arenas]
        .sort((a, b) => parse(b.last_action?.at) - parse(a.last_action?.at))
        .slice(0, limit ?? board.arenas.length),
    [board, limit],
  );
  if (!rows.length)
    return (
      <Empty
        title="No live arenas"
        detail="Launch an arena or start an evaluation; its agents appear here as they act."
      />
    );
  return (
    <div className="board-table" role="table" aria-label="Live arenas">
      <div className="board-row board-head" role="row">
        <span role="columnheader">Arena</span>
        <span role="columnheader">Agent</span>
        <span role="columnheader">Last action</span>
        <span role="columnheader">Errors</span>
        <span role="columnheader">Budget</span>
      </div>
      {rows.map((arena) => {
        const idle = isIdle(arena, board, now);
        const ratio =
          arena.budget.remaining != null && arena.budget.cap
            ? arena.budget.remaining / arena.budget.cap
            : null;
        return (
          <div
            className={`board-row ${idle ? "board-idle" : ""}`}
            role="row"
            key={arena.id}
          >
            <span role="cell">
              <a
                href={`/console/arena/${encodeURIComponent(arena.id)}?tab=live`}
              >
                {arena.name}
              </a>
              <Status value={arena.budget.stopped ? "stopped" : arena.state} />
              {arena.trial && (
                <a
                  className="board-trial"
                  href={`/console/evaluations/${encodeURIComponent(arena.trial.evaluation_id)}`}
                >
                  trial seed {arena.trial.seed} · {arena.trial.state}
                </a>
              )}
            </span>
            <span role="cell">
              {arena.agents.length
                ? arena.agents.map((agent) => (
                    <span key={agent.name} className="board-agent">
                      {agent.name} <small>{agent.stance || "any"}</small>
                      {agent.paused && <em>paused</em>}
                    </span>
                  ))
                : "No agent"}
            </span>
            <span role="cell">
              {arena.last_action ? (
                <>
                  <strong
                    className={`board-last board-${arena.last_action.status}`}
                  >
                    {arena.last_action.name}
                  </strong>
                  <small>
                    {arena.last_action.actor} · {ago(arena.last_action.at, now)}
                  </small>
                </>
              ) : (
                <small>No action yet</small>
              )}
              {idle && (
                <em className="board-flag">
                  idle &gt; {board.idle_minutes} min
                </em>
              )}
            </span>
            <span role="cell">
              {arena.error_rate == null
                ? "—"
                : `${Math.round(arena.error_rate * 100)}%`}
              <small>{arena.recent_actions} recent</small>
            </span>
            <span role="cell">
              <span className="board-meter" aria-hidden="true">
                <span
                  style={{
                    width: `${ratio == null ? 0 : Math.max(0, Math.min(1, ratio)) * 100}%`,
                  }}
                  className={ratio != null && ratio < 0.2 ? "low" : ""}
                />
              </span>
              <small>
                {arena.budget.remaining == null
                  ? "Unavailable"
                  : `${arena.budget.remaining} of ${arena.budget.cap}`}
              </small>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Inbox({ board, now }: { board: Board; now: number }) {
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const items = board.inbox.filter((item) => !dismissed.includes(item.key));
  useEffect(() => onDismissedChange(setDismissed), []);
  const dismiss = (keys: string[]) => setDismissed(dismissInbox(keys));
  return (
    <Panel
      eyebrow="ATTENTION"
      title="Needs a human"
      className="board-inbox"
      aside={
        items.length ? (
          <button
            type="button"
            className="button button-outline"
            onClick={() => dismiss(items.map((item) => item.key))}
          >
            Dismiss all
          </button>
        ) : undefined
      }
    >
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item.key} className={`board-inbox-${item.kind}`}>
              <span className="board-kind">{item.kind.replace("_", " ")}</span>
              <span>
                {item.text}
                <small>
                  {item.arena_name || item.arena_id || "platform"} ·{" "}
                  {ago(item.at, now)}
                </small>
              </span>
              {item.arena_id && (
                <a
                  className="inline-action"
                  href={`/console/arena/${encodeURIComponent(item.arena_id)}?tab=live`}
                >
                  Open ↗
                </a>
              )}
              <button
                type="button"
                className="board-dismiss"
                aria-label={`Dismiss: ${item.text}`}
                onClick={() => dismiss([item.key])}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <Empty
          title="Nothing waiting"
          detail="Failed arenas, verdicts, budget exhaustion, stops and finished trials appear here."
        />
      )}
    </Panel>
  );
}

export function AgentsBoard() {
  const { board, error, live, now } = useBoard();
  if (!board && error)
    return (
      <ErrorState message={error} refresh={() => window.location.reload()} />
    );
  if (!board) return <Loading />;
  const idle = board.arenas.filter((arena) => isIdle(arena, board, now)).length;
  return (
    <>
      <PageHead
        overline="RESEARCH / AGENTS BOARD"
        title="What are my agents doing"
        subtitle={`${board.arenas.length} live arenas · ${board.arenas.reduce((n, a) => n + a.agents.length, 0)} agents · ${idle} idle · ${live ? "live" : "reconnecting"}`}
        observed={board.observed_at}
        action={
          <a
            className="button button-outline"
            href="/console/activity?section=audit"
          >
            Full audit trail ↗
          </a>
        }
      />
      <div className="board-layout">
        <Panel
          eyebrow="LIVE ARENAS"
          title="Agents at work"
          className="board-main"
        >
          <ArenaRows board={board} now={now} />
        </Panel>
        <Inbox board={board} now={now} />
      </div>
    </>
  );
}

/** Compact live board for the Research and Agents pages. */
export function BoardSummary({ eyebrow }: { eyebrow: string }) {
  const { board, error, now } = useBoard();
  return (
    <Panel
      eyebrow={eyebrow}
      title="Agents board"
      className="board-summary"
      aside={
        board && board.inbox.length ? (
          <span className="tiny-tag">{board.inbox.length} NEED ATTENTION</span>
        ) : undefined
      }
    >
      {error && !board ? (
        <Empty title="Board unavailable" detail={error} />
      ) : !board ? (
        <Empty title="Loading the board" detail="Fetching live arenas." />
      ) : (
        <ArenaRows board={board} now={now} limit={5} />
      )}
      <div className="panel-foot">
        <span>
          {board
            ? `Updated ${formatObserved(board.observed_at)} · pushed live`
            : "Pushed live from the platform"}
        </span>
        <a className="inline-action" href="/console/board">
          Open the board ↗
        </a>
      </div>
    </Panel>
  );
}
