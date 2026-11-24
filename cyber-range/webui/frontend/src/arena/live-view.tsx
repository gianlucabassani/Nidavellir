import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getJson, postJson } from "../api";
import type { ArenaData, EvidenceData, Span } from "../types";
import { formatObserved, getJsonSafe } from "../ui";
import "./live-view.css";

// OBS-05: the agent live view, the main screen of an active arena. Spans arrive
// on the arena's push stream (OBS-04); history loads once. The list is
// virtualized by hand (fixed row height) so a 5,000-span run stays smooth.

export type SpanFeed = {
  subscribe: (listener: (spans: Span[]) => void) => () => void;
};
type Binding = { agent_name: string; stance: string | null; paused: boolean };

const ROW = 34;
const OVERSCAN = 12;
const WATERFALL_MAX = 2000;

function ms(value: number | null | undefined) {
  if (value == null) return "—";
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`;
}

function time(value: string | null | undefined) {
  if (!value) return 0;
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function elapsed(fromMs: number, now: number) {
  if (!fromMs) return "—";
  const s = Math.max(0, Math.round((now - fromMs) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}

function Gauge({
  label,
  value,
  max,
  text,
}: {
  label: string;
  value: number | null;
  max: number | null;
  text: string;
}) {
  const ratio =
    value != null && max ? Math.max(0, Math.min(1, value / max)) : null;
  return (
    <div className="live-gauge">
      <small>{label}</small>
      <div
        className={`live-gauge-bar ${ratio != null && ratio < 0.2 ? "low" : ""}`}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max ?? 0}
        aria-valuenow={value ?? 0}
        aria-valuetext={text}
      >
        <span style={{ width: `${ratio == null ? 0 : ratio * 100}%` }} />
      </div>
      <strong>{text}</strong>
    </div>
  );
}

export function AgentLiveView({
  arena,
  feed,
  onStop,
}: {
  arena: ArenaData;
  feed: SpanFeed;
  onStop: () => void;
}) {
  const id = encodeURIComponent(arena.id);
  const [spans, setSpans] = useState<Span[]>([]);
  const [loadError, setLoadError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [follow, setFollow] = useState(true);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [actor, setActor] = useState("");
  const [text, setText] = useState("");
  const [agentView, setAgentView] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(520);
  const [now, setNow] = useState(Date.now());
  const [signals, setSignals] = useState<EvidenceData["signals"]>([]);
  const [pending, setPending] = useState("");
  const list = useRef<HTMLDivElement>(null);

  const merge = useCallback((incoming: Span[]) => {
    if (!incoming.length) return;
    setSpans((current) => {
      const last = current.length ? current[current.length - 1].id : 0;
      // Stream frames are ordered; anything not newer is already known.
      const fresh = incoming.filter((span) => span.id > last);
      if (fresh.length === incoming.length && !current.length) return incoming;
      if (!fresh.length) {
        const known = new Set(current.map((span) => span.id));
        const late = incoming.filter((span) => !known.has(span.id));
        return late.length
          ? [...current, ...late].sort((a, b) => a.id - b.id)
          : current;
      }
      return [...current, ...fresh];
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    getJson<{ spans: Span[] }>(`/api/console/arenas/${id}/spans?limit=5000`)
      .then((data) => {
        if (!cancelled) merge(data.spans);
      })
      .catch((reason: unknown) => {
        if (!cancelled)
          setLoadError(
            reason instanceof Error
              ? reason.message
              : "Span timeline unavailable",
          );
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id, merge]);
  useEffect(() => feed.subscribe(merge), [feed, merge]);

  const loadBindings = useCallback(() => {
    void getJsonSafe<{ bindings: Binding[] }>(
      `/api/arenas/${id}/bindings`,
    ).then((data) => {
      if (data) setBindings(data.bindings);
    });
  }, [id]);
  useEffect(loadBindings, [loadBindings, arena.events[0]?.id]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000); // clock only
    return () => window.clearInterval(timer);
  }, []);

  const actors = useMemo(
    () => [...new Set(spans.map((span) => span.actor))].sort(),
    [spans],
  );
  const kinds = useMemo(
    () => [...new Set(spans.map((span) => span.kind))].sort(),
    [spans],
  );
  const visible = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return spans.filter(
      (span) =>
        (!agentView || span.visibility === "agent") &&
        (!kind || span.kind === kind) &&
        (!status || span.status === status) &&
        (!actor || span.actor === actor) &&
        (!needle ||
          `${span.name} ${span.actor} ${span.status} ${span.error_class || ""} ${span.input_preview || ""}`
            .toLowerCase()
            .includes(needle)),
    );
  }, [spans, agentView, kind, status, actor, text]);

  // Follow live: keep the newest span in view as frames arrive.
  useEffect(() => {
    const element = list.current;
    if (!follow || !element) return;
    element.scrollTop = element.scrollHeight;
    setScrollTop(element.scrollTop);
  }, [visible.length, follow]);
  useEffect(() => {
    const element = list.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setHeight(element.clientHeight || 520),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const selectedIndex =
    selected == null ? -1 : visible.findIndex((span) => span.id === selected);
  const current = selectedIndex >= 0 ? visible[selectedIndex] : null;
  useEffect(() => {
    if (!current) return;
    void getJsonSafe<EvidenceData>(`/api/console/arenas/${id}/evidence`).then(
      (data) => {
        if (data) setSignals(data.signals || []);
      },
    );
  }, [id, current?.id]);

  function select(index: number) {
    const span = visible[Math.max(0, Math.min(visible.length - 1, index))];
    if (!span) return;
    setSelected(span.id);
    setFollow(false);
    const element = list.current;
    if (element) {
      const top = visible.indexOf(span) * ROW;
      if (top < element.scrollTop) element.scrollTop = top;
      else if (top + ROW > element.scrollTop + element.clientHeight)
        element.scrollTop = top + ROW - element.clientHeight;
    }
  }
  function onKey(event: React.KeyboardEvent) {
    const page = Math.max(1, Math.floor(height / ROW) - 1);
    const moves: Record<string, number> = {
      ArrowDown: selectedIndex + 1,
      ArrowUp: selectedIndex < 0 ? visible.length - 1 : selectedIndex - 1,
      PageDown: selectedIndex + page,
      PageUp: selectedIndex - page,
      Home: 0,
      End: visible.length - 1,
    };
    if (event.key in moves) {
      event.preventDefault();
      select(moves[event.key]);
    } else if (event.key === "Escape") {
      setSelected(null);
    }
  }

  async function togglePause(binding: Binding) {
    setPending(binding.agent_name);
    try {
      await postJson(
        `/api/arenas/${id}/bindings/${encodeURIComponent(binding.agent_name)}/${binding.paused ? "resume" : "pause"}`,
        {},
      );
      loadBindings();
    } finally {
      setPending("");
    }
  }

  const start = Math.max(0, Math.floor(scrollTop / ROW) - OVERSCAN);
  const end = Math.min(
    visible.length,
    Math.ceil((scrollTop + height) / ROW) + OVERSCAN,
  );
  const firstAt = spans.length ? time(spans[0].started_at) : 0;
  const last = spans[spans.length - 1];
  const failures = spans.filter((span) => span.status !== "ok").length;
  const deadline = time(arena.expires_at);
  const remainingMs = deadline ? deadline - now : null;
  const windowMs = deadline && firstAt ? deadline - firstAt : null;
  const active = arena.state === "active";

  return (
    <div className="live-view">
      <header className="live-header" aria-label="Agent status">
        <div className="live-who">
          <small>CONNECTED</small>
          {bindings.length ? (
            bindings.map((binding) => (
              <div key={binding.agent_name} className="live-agent">
                <strong>{binding.agent_name}</strong>
                <span>{binding.stance || "unrestricted"}</span>
                <span
                  className={`status status-${binding.paused ? "warning" : "success"}`}
                >
                  <i aria-hidden="true" />
                  {binding.paused ? "paused" : "active"}
                </span>
                {active && (
                  <button
                    type="button"
                    className="button button-outline"
                    disabled={pending === binding.agent_name}
                    onClick={() => void togglePause(binding)}
                  >
                    {pending === binding.agent_name
                      ? "Working…"
                      : binding.paused
                        ? "Resume"
                        : "Pause"}
                  </button>
                )}
              </div>
            ))
          ) : (
            <span>No agent bound. Connect one from Agent access.</span>
          )}
        </div>
        <div className="live-now">
          <small>CURRENT STEP</small>
          <strong>
            {last
              ? `${last.name} · ${last.actor}`
              : "Waiting for the first action"}
          </strong>
          <span>
            Elapsed {elapsed(firstAt, now)} · {spans.length} spans · {failures}{" "}
            not ok
          </span>
        </div>
        <Gauge
          label="Actions left"
          value={arena.budget.remaining}
          max={arena.budget.cap}
          text={
            arena.budget.remaining == null
              ? "Unavailable"
              : `${arena.budget.remaining} of ${arena.budget.cap ?? "?"}`
          }
        />
        <Gauge
          label="Time left"
          value={remainingMs == null ? null : Math.max(0, remainingMs)}
          max={windowMs}
          text={
            remainingMs == null
              ? "No deadline"
              : elapsed(now - Math.max(0, remainingMs), now)
          }
        />
        {active && (
          <button
            type="button"
            className="button button-danger live-stop"
            onClick={onStop}
          >
            Stop research
          </button>
        )}
      </header>

      <Waterfall
        spans={visible}
        selected={selected}
        onSelect={(span) => select(visible.indexOf(span))}
      />

      <div className="live-filters" role="group" aria-label="Filter spans">
        <label>
          Kind
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">All</option>
            {kinds.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">All</option>
            <option value="ok">ok</option>
            <option value="error">error</option>
            <option value="denied">denied</option>
            <option value="budget_refused">budget refused</option>
          </select>
        </label>
        <label>
          Actor
          <select
            value={actor}
            onChange={(event) => setActor(event.target.value)}
          >
            <option value="">All</option>
            {actors.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label className="live-search">
          Search
          <input
            type="search"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Tool, actor, error or input"
          />
        </label>
        <label className="live-check">
          <input
            type="checkbox"
            checked={follow}
            onChange={(event) => setFollow(event.target.checked)}
          />
          Follow live
        </label>
        <label className="live-check">
          <input
            type="checkbox"
            checked={agentView}
            onChange={(event) => setAgentView(event.target.checked)}
          />
          Agent's view
        </label>
      </div>

      <div className="live-body">
        <div className="live-list-frame">
          <div className="live-row live-row-head" aria-hidden="true">
            <span>Time</span>
            <span>Tool</span>
            <span>Status</span>
            <span>Duration</span>
            <span>Actor</span>
          </div>
          <div
            ref={list}
            className="live-list"
            role="listbox"
            tabIndex={0}
            aria-label={`Span timeline, ${visible.length} spans`}
            aria-activedescendant={current ? `span-${current.id}` : undefined}
            onKeyDown={onKey}
            onScroll={(event) => {
              const element = event.currentTarget;
              setScrollTop(element.scrollTop);
              const atBottom =
                element.scrollHeight -
                  element.scrollTop -
                  element.clientHeight <
                ROW;
              if (!atBottom && follow) setFollow(false);
            }}
          >
            <div style={{ height: visible.length * ROW, position: "relative" }}>
              {visible.slice(start, end).map((span, offset) => (
                <div
                  key={span.id}
                  id={`span-${span.id}`}
                  role="option"
                  aria-selected={span.id === selected}
                  className={`live-row live-status-${span.status} ${span.id === selected ? "selected" : ""}`}
                  style={{ top: (start + offset) * ROW }}
                  onClick={() => select(start + offset)}
                >
                  <span>
                    {new Date(time(span.started_at)).toLocaleTimeString()}
                  </span>
                  <span>
                    <i
                      className={`live-kind live-kind-${span.kind}`}
                      aria-hidden="true"
                    />
                    {span.name}
                    {span.visibility === "operator" && (
                      <em className="live-tag">operator</em>
                    )}
                  </span>
                  <span className="live-status">
                    {span.status.replace("_", " ")}
                  </span>
                  <span>{ms(span.duration_ms)}</span>
                  <span>{span.actor}</span>
                </div>
              ))}
            </div>
            {!visible.length && (
              <p className="live-empty">
                {loadError ||
                  (loaded
                    ? "No spans yet. Actions by agents and operators appear here as they happen."
                    : "Loading the timeline…")}
              </p>
            )}
          </div>
        </div>
        <Inspector arena={arena} span={current} signals={signals} />
      </div>
    </div>
  );
}

function Waterfall({
  spans,
  selected,
  onSelect,
}: {
  spans: Span[];
  selected: number | null;
  onSelect: (span: Span) => void;
}) {
  const shown = spans.slice(-WATERFALL_MAX);
  const bars = useMemo(() => {
    if (!shown.length) return { rows: [], lanes: 0, from: 0, span: 1 };
    const from = time(shown[0].started_at);
    const to = Math.max(
      ...shown.map((s) => time(s.started_at) + (s.duration_ms || 0)),
      from + 1,
    );
    const laneEnds: number[] = [];
    const rows = shown.map((s) => {
      const begin = time(s.started_at);
      const finish = begin + Math.max(s.duration_ms || 0, 1);
      let lane = laneEnds.findIndex((endAt) => endAt <= begin);
      if (lane < 0) lane = laneEnds.push(finish) - 1;
      else laneEnds[lane] = finish;
      return { s, lane, begin, finish };
    });
    return { rows, lanes: laneEnds.length, from, span: to - from };
  }, [shown]);
  if (!bars.rows.length) return null;
  const lanes = Math.min(bars.lanes, 8);
  return (
    <figure
      className="live-waterfall"
      aria-label="Time and concurrency of the visible spans"
    >
      <svg
        viewBox={`0 0 1000 ${lanes * 7 + 2}`}
        preserveAspectRatio="none"
        role="img"
        aria-hidden="true"
      >
        {bars.rows
          .filter((row) => row.lane < 8)
          .map(({ s, lane, begin, finish }) => (
            <rect
              key={s.id}
              className={`live-bar live-status-${s.status} ${s.id === selected ? "selected" : ""}`}
              x={((begin - bars.from) / bars.span) * 1000}
              y={lane * 7 + 1}
              width={Math.max(1.5, ((finish - begin) / bars.span) * 1000)}
              height={5}
              onClick={() => onSelect(s)}
            />
          ))}
      </svg>
      <figcaption>
        {shown.length} spans over {ms(bars.span)} · peak concurrency{" "}
        {bars.lanes}
        {spans.length > WATERFALL_MAX ? ` · latest ${WATERFALL_MAX} shown` : ""}
      </figcaption>
    </figure>
  );
}

function Inspector({
  arena,
  span,
  signals,
}: {
  arena: ArenaData;
  span: Span | null;
  signals: EvidenceData["signals"];
}) {
  if (!span)
    return (
      <aside className="live-inspector" aria-label="Span inspector">
        <p className="live-empty">
          Select a span (click, or arrow keys in the list) to inspect its
          request, response and effect.
        </p>
      </aside>
    );
  const attrs = span.attrs || {};
  const transaction =
    typeof attrs["nv.transaction_digest"] === "string"
      ? (attrs["nv.transaction_digest"] as string)
      : null;
  const finding =
    typeof attrs["nv.finding_id"] === "string"
      ? (attrs["nv.finding_id"] as string)
      : null;
  const budget = attrs["nv.budget_outcome"] as string | undefined;
  const begin = time(span.started_at);
  const finish = begin + (span.duration_ms || 0);
  const near = signals.filter((signal) => {
    const at = time(signal.ts);
    return at >= begin - 1000 && at <= finish + 10000;
  });
  const tokensIn = attrs["gen_ai.usage.input_tokens"];
  const tokensOut = attrs["gen_ai.usage.output_tokens"];
  const base = `/console/arena/${encodeURIComponent(arena.id)}`;
  return (
    <aside className="live-inspector" aria-label="Span inspector">
      <h3>
        {span.name}{" "}
        <span className={`live-status live-status-${span.status}`}>
          {span.status.replace("_", " ")}
        </span>
      </h3>
      <dl>
        <dt>Actor</dt>
        <dd>
          {span.actor} · {span.actor_kind}
          {span.stance ? ` · ${span.stance}` : ""}
        </dd>
        <dt>When</dt>
        <dd>
          {formatObserved(span.started_at)} · {ms(span.duration_ms)}
        </dd>
        <dt>Kind</dt>
        <dd>
          {span.kind}
          {attrs["nv.self_reported"] ? " · self-reported" : ""}
          {span.visibility === "operator" ? " · operator-only" : ""}
        </dd>
        {span.error_class && (
          <>
            <dt>Error</dt>
            <dd>{span.error_class}</dd>
          </>
        )}
        {budget && (
          <>
            <dt>Budget</dt>
            <dd>
              {budget === "spent"
                ? "1 action spent"
                : budget === "released"
                  ? "Reservation released"
                  : "Outcome unknown (charged)"}
            </dd>
          </>
        )}
        {span.status === "budget_refused" && (
          <>
            <dt>Budget</dt>
            <dd>Refused: no action spent</dd>
          </>
        )}
        {(tokensIn != null || tokensOut != null) && (
          <>
            <dt>Tokens</dt>
            <dd>
              {String(tokensIn ?? "?")} in · {String(tokensOut ?? "?")} out
            </dd>
          </>
        )}
        {transaction && (
          <>
            <dt>Transaction</dt>
            <dd>
              <a
                href={`${base}?tab=http&digest=${encodeURIComponent(transaction)}`}
              >
                {transaction.slice(0, 19)}… ↗
              </a>
            </dd>
          </>
        )}
        {finding && (
          <>
            <dt>Finding</dt>
            <dd>
              <a href={`${base}?tab=findings`}>{finding} ↗</a>
            </dd>
          </>
        )}
      </dl>
      <h4>Request</h4>
      <pre>{span.input_preview || "No input recorded."}</pre>
      <h4>Response · target-side effect</h4>
      <pre>{span.output_preview || "No output recorded."}</pre>
      <h4>Monitor signals around this call</h4>
      {near.length ? (
        <ul className="live-signals">
          {near.map((signal, index) => (
            <li key={`${signal.ts}-${index}`}>
              <strong>{signal.severity || "unrated"}</strong>{" "}
              {signal.summary || signal.kind} · {signal.node || "arena"}
            </li>
          ))}
        </ul>
      ) : (
        <p className="live-empty">None recorded within 10 s of this call.</p>
      )}
      <p className="live-digests">
        in {span.input_digest?.slice(0, 19) || "—"} · out{" "}
        {span.output_digest?.slice(0, 19) || "—"}
      </p>
    </aside>
  );
}
