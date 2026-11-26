// UX-19: the forge line. The gold spine is the target; time runs downward.
// Each actor is a strand that branches off the spine when it first acts. Steps
// sit on their strand: pills for tool calls (length = duration, colour =
// family), rings for model calls, red knots for failures and refusals, gold
// marks on the spine for submitted findings. A thread from a step to the spine
// means the step touched the target. Quiet time is compressed and long
// silences fold into one labelled line. A playhead replays the run.
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import type { Span } from "../types";
import { Icon } from "../shell/icons";
import "./forge-line.css";

export const FORGE_LIMIT = 600;
const FOLD_SECONDS = 180;
const MAX_STRANDS = 6;
const TOP = 112;
const HEAD = 88;

type Family = "http" | "exec" | "model" | "other";
const FINDING = new Set(["findings", "findings/manual"]);

function family(span: Span): Family {
  if (span.kind === "model") return "model";
  if (span.name.startsWith("http/")) return "http";
  if (span.name === "exec" || span.name.startsWith("exec/")) return "exec";
  return "other";
}
function touches(span: Span) {
  return (
    span.kind === "tool" &&
    (span.name.startsWith("http/") ||
      span.name === "exec" ||
      span.name.startsWith("browser/") ||
      span.name.startsWith("files/") ||
      span.name === "mitm/observe" ||
      FINDING.has(span.name))
  );
}
function parse(value: string | null | undefined) {
  if (!value) return 0;
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  const at = Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(at) ? 0 : at;
}
function clock(ms: number, seconds = true) {
  return new Date(ms).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
  });
}
function label(span: Span) {
  let detail = span.input_preview || "";
  try {
    const value: unknown = JSON.parse(detail);
    if (value && typeof value === "object" && !Array.isArray(value))
      detail = Object.values(value as Record<string, unknown>)
        .filter((item) => ["string", "number"].includes(typeof item))
        .join(" ");
  } catch {
    /* recorded as text */
  }
  if (FINDING.has(span.name)) return detail || "Finding submitted";
  const base = span.name === "exec" ? `$ ${detail}` : detail || span.name;
  return base.trim() || span.name;
}
const cut = (text: string, max: number) =>
  text.length > max ? `${text.slice(0, max - 1)}…` : text;
const clamp = (value: number, low: number, high: number) =>
  Math.max(low, Math.min(high, value));

type Layout = ReturnType<typeof layoutOf>;

function layoutOf(spans: Span[], width: number, liveNow: number | null) {
  const t0 = parse(spans[0]?.started_at);
  const at = (span: Span) => (parse(span.started_at) - t0) / 1000;
  const end = (span: Span) =>
    span.ended_at
      ? (parse(span.ended_at) - t0) / 1000
      : at(span) + (span.duration_ms || 0) / 1000;
  const lastEnd = Math.max(0, ...spans.map(end));
  const nowS = liveNow ? Math.max(lastEnd, (liveNow - t0) / 1000) : lastEnd;
  // Warped time: anchors at each distinct start; silences fold.
  const starts = [...new Set(spans.map(at))].sort((a, b) => a - b);
  const anchors: [number, number][] = [[0, TOP]];
  const gaps: { a: number; b: number; y0: number; y1: number }[] = [];
  let prev = 0;
  let y = TOP;
  let reach = 0;
  for (const s of starts) {
    if (s === 0) continue;
    reach = Math.max(
      reach,
      ...spans.filter((span) => at(span) <= prev).map(end),
    );
    if (s - prev >= FOLD_SECONDS && s - reach >= FOLD_SECONDS) {
      const y0 = y + clamp((reach - prev) * 3.2, 16, 40);
      anchors.push([reach, y0]);
      gaps.push({ a: reach, b: s, y0, y1: y0 + 72 });
      y = y0 + 72;
    } else y += clamp((s - prev) * 3.2, 22, 64);
    anchors.push([s, y]);
    prev = s;
  }
  anchors.push([Math.max(nowS, prev + 1), y + 36]);
  const Y = (s: number) => {
    for (let i = 1; i < anchors.length; i++)
      if (s <= anchors[i][0]) {
        const [a0, y0] = anchors[i - 1];
        const [a1, y1] = anchors[i];
        return y0 + ((s - a0) / (a1 - a0 || 1)) * (y1 - y0);
      }
    return anchors[anchors.length - 1][1];
  };
  const T = (py: number) => {
    for (let i = 1; i < anchors.length; i++)
      if (py <= anchors[i][1]) {
        const [a0, y0] = anchors[i - 1];
        const [a1, y1] = anchors[i];
        return a0 + ((py - y0) / (y1 - y0 || 1)) * (a1 - a0);
      }
    return anchors[anchors.length - 1][0];
  };
  // Strands: actors in order of first action, alternating sides.
  const order: string[] = [];
  for (const span of spans)
    if (!order.includes(span.actor)) order.push(span.actor);
  const named = order.slice(0, MAX_STRANDS);
  const strandOf = (actor: string) =>
    named.includes(actor) ? named.indexOf(actor) : MAX_STRANDS - 1;
  const cx = Math.round(width / 2);
  const gap = clamp(width / 10, 54, 90);
  const strands = named.map((actor, i) => {
    const side = i % 2 === 0 ? -1 : 1;
    const rank = Math.floor(i / 2);
    const x = cx + side * (gap + rank * 34);
    const first = spans.find((span) => strandOf(span.actor) === i);
    const last = [...spans]
      .reverse()
      .find((span) => strandOf(span.actor) === i);
    return {
      actor:
        i === MAX_STRANDS - 1 && order.length > MAX_STRANDS
          ? `${actor} +${order.length - MAX_STRANDS}`
          : actor,
      kind: first?.actor_kind || "agent",
      side,
      x,
      birth: Math.max(HEAD, Y(first ? at(first) : 0) - 26),
      until: last ? Y(end(last)) + 6 : TOP,
    };
  });
  return {
    t0,
    at,
    end,
    Y,
    T,
    gaps,
    strands,
    strandOf,
    cx,
    nowS,
    yNow: Y(nowS),
    height: Y(nowS) + 70,
  };
}

export function ForgeLine({
  spans,
  total,
  selectedId,
  onSelect,
  onKey,
  live,
}: {
  spans: Span[];
  total: number;
  selectedId: number | null;
  onSelect: (span: Span) => void;
  onKey: (event: KeyboardEvent) => void;
  live: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  const [now, setNow] = useState(Date.now());
  const [hover, setHover] = useState<{
    span: Span;
    x: number;
    y: number;
  } | null>(null);
  const [play, setPlay] = useState<{ y: number; on: boolean } | null>(null);
  const [speed, setSpeed] = useState(1);
  const shown = spans.length > FORGE_LIMIT ? spans.slice(-FORGE_LIMIT) : spans;
  useEffect(() => {
    const element = wrap.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setWidth(Math.max(320, Math.min(900, element.clientWidth))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(timer);
  }, [live]);
  const g: Layout | null = useMemo(
    () => (shown.length ? layoutOf(shown, width, live ? now : null) : null),
    [shown, width, live, now],
  );
  // Follow the newest step while not replaying.
  useEffect(() => {
    if (!play && scroller.current)
      scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [shown.length, play]);
  // Replay: the playhead moves down the page at a steady pace.
  useEffect(() => {
    if (!play?.on || !g) return;
    let frame = 0;
    let last = performance.now();
    const step = (ts: number) => {
      const dt = Math.min(64, ts - last);
      last = ts;
      setPlay((current) => {
        if (!current?.on) return current;
        const y = Math.min(g.yNow, current.y + (dt / 1000) * 120 * speed);
        if (scroller.current)
          scroller.current.scrollTop = y - scroller.current.clientHeight * 0.6;
        return y >= g.yNow ? { y: g.yNow, on: false } : { y, on: true };
      });
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [play?.on, g, speed]);

  if (!g)
    return (
      <div className="fg-line-empty" ref={wrap}>
        <p>
          No steps yet. Actions by agents and operators appear here as they
          happen.
        </p>
      </div>
    );
  const playY = play ? play.y : g.yNow;
  const future = (y: number) => y > playY + 0.5;
  const ticks: { y: number; t: number }[] = [];
  let lastTick = -99;
  for (let s = 0; s <= g.nowS; s += 10) {
    const y = g.Y(s);
    if (
      y - lastTick < 58 ||
      g.gaps.some((gap) => y > gap.y0 - 4 && y < gap.y1 + 4)
    )
      continue;
    lastTick = y;
    ticks.push({ y, t: g.t0 + s * 1000 });
  }
  const rail = (x: number, from: number, to: number, cls: string) => {
    const parts: ReactElement[] = [];
    let y = from;
    g.gaps.forEach((gap, i) => {
      if (gap.y0 > y && gap.y0 < to) {
        parts.push(
          <line
            key={`a${i}`}
            className={cls}
            x1={x}
            x2={x}
            y1={y}
            y2={gap.y0}
          />,
        );
        parts.push(
          <line
            key={`f${i}`}
            className={`${cls} fold`}
            x1={x}
            x2={x}
            y1={gap.y0 + 5}
            y2={gap.y1 - 5}
          />,
        );
        y = gap.y1;
      }
    });
    parts.push(
      <line
        key="z"
        className={cls}
        x1={x}
        x2={x}
        y1={y}
        y2={Math.max(y, to)}
      />,
    );
    return parts;
  };
  // Side labels with leader lines; pushed down to avoid each other, dropped if too far.
  const labels: {
    span: Span;
    want: number;
    y: number;
    x: number;
    side: number;
  }[] = [];
  const lastY: Record<number, number> = {};
  for (const span of shown) {
    if (!touches(span)) continue;
    const strand = g.strands[g.strandOf(span.actor)];
    if (!strand || Math.abs(strand.x - g.cx) > 100) continue; // inner strands only
    const y0 = g.Y(g.at(span));
    const h = Math.max(g.Y(g.end(span)) - y0, 9);
    const want = y0 + h / 2;
    const y = Math.max(want, (lastY[strand.side] ?? -99) + 16);
    if (y - want > 44) continue;
    lastY[strand.side] = y;
    labels.push({ span, want, y, x: strand.x, side: strand.side });
  }
  const labelRoom = Math.max(18, Math.floor((g.cx - 160) / 6.6));
  const W = width;
  return (
    <div className="forge-line" ref={wrap}>
      <div className="fg-line-bar">
        <button
          type="button"
          className="button button-outline"
          onClick={() =>
            setPlay((current) =>
              current?.on
                ? { ...current, on: false }
                : {
                    y: current && current.y < g.yNow - 1 ? current.y : TOP - 20,
                    on: true,
                  },
            )
          }
        >
          <Icon name={play?.on ? "x" : "bolt"} size={14} />
          {play?.on ? "Pause replay" : "Replay"}
        </button>
        <input
          type="range"
          aria-label="Scrub through the run"
          min={TOP - 20}
          max={Math.ceil(g.yNow)}
          value={Math.round(playY)}
          onChange={(event) =>
            setPlay({ y: Number(event.target.value), on: false })
          }
        />
        <span className="fg-clock">{clock(g.t0 + g.T(playY) * 1000)}</span>
        <div className="seg" role="group" aria-label="Replay speed">
          {[1, 2, 4].map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={speed === value}
              onClick={() => setSpeed(value)}
            >
              {value}×
            </button>
          ))}
        </div>
        {play && (
          <button
            type="button"
            className="inline-action"
            onClick={() => setPlay(null)}
          >
            {live ? "Back to live" : "Show all"}
          </button>
        )}
        {spans.length > FORGE_LIMIT && (
          <span className="fg-cap">
            Newest {FORGE_LIMIT} of {total} steps · the list view holds all
          </span>
        )}
      </div>
      <div
        className="fg-line-scroll"
        ref={scroller}
        tabIndex={0}
        role="group"
        aria-label={`Forge line, ${shown.length} steps. Arrow keys move the selection.`}
        onKeyDown={onKey}
      >
        <svg
          className="fg-svg"
          width={W}
          height={g.height}
          viewBox={`0 0 ${W} ${g.height}`}
        >
          <defs>
            <filter
              id="fg-glow"
              filterUnits="userSpaceOnUse"
              x={-40}
              y={-40}
              width={W + 80}
              height={g.height + 80}
            >
              <feGaussianBlur stdDeviation="3.5" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <linearGradient
              id="fg-spine"
              gradientUnits="userSpaceOnUse"
              x1="0"
              x2="0"
              y1="0"
              y2={g.height}
            >
              <stop offset="0" stopColor="var(--gold)" stopOpacity=".55" />
              <stop offset="1" stopColor="var(--gold)" />
            </linearGradient>
            <clipPath id="fg-clip">
              <rect x={-40} y={0} width={W + 80} height={Math.max(0, playY)} />
            </clipPath>
          </defs>
          {ticks.map((tick) => (
            <g key={tick.y} className="fg-tick">
              <text x={4} y={tick.y + 4}>
                {clock(tick.t)}
              </text>
              <line x1={62} x2={70} y1={tick.y} y2={tick.y} />
            </g>
          ))}
          {g.gaps.map((gap) => (
            <text
              key={gap.a}
              className="fg-gap"
              x={g.cx}
              y={(gap.y0 + gap.y1) / 2 + 4}
              textAnchor="middle"
            >
              {Math.round((gap.b - gap.a) / 60)} min with nothing running
            </text>
          ))}
          {g.strands.map((strand) => (
            <g key={strand.actor} className="fg-head">
              <text
                className="h1"
                x={strand.x}
                y={22}
                textAnchor={strand.side < 0 ? "end" : "start"}
              >
                {cut(strand.actor, 22)}
              </text>
              <text
                x={strand.x}
                y={38}
                textAnchor={strand.side < 0 ? "end" : "start"}
              >
                {strand.kind}
              </text>
            </g>
          ))}
          <text className="h1" x={g.cx} y={22} textAnchor="middle">
            target
          </text>
          <ellipse className="fg-ring" cx={g.cx} cy={HEAD} rx={15} ry={5} />
          <text className="fg-start" x={g.cx} y={HEAD - 14} textAnchor="middle">
            Started {clock(g.t0)}
          </text>
          <g clipPath="url(#fg-clip)">
            {rail(g.cx, HEAD, g.yNow, "fg-spine")}
            {g.strands.map((strand) => {
              const d = strand.x - g.cx;
              const y0 = strand.birth;
              const until = Math.min(strand.until, g.yNow);
              return (
                <g key={strand.actor}>
                  <path
                    className="fg-strand"
                    d={`M${g.cx} ${y0} C${g.cx + d * 0.55} ${y0},${strand.x} ${y0 + 4},${strand.x} ${y0 + 18}`}
                  />
                  {rail(strand.x, y0 + 18, until, "fg-strand")}
                  {until < g.yNow - 8 && (
                    <line
                      className="fg-strand idle"
                      x1={strand.x}
                      x2={strand.x}
                      y1={until}
                      y2={g.yNow}
                    />
                  )}
                </g>
              );
            })}
          </g>
          {labels.map(({ span, want, y, x, side }) => {
            const lx = x + side * 26;
            const failed = span.status !== "ok";
            return (
              <g
                key={`l${span.id}`}
                className={`fg-label ${FINDING.has(span.name) ? "find" : ""} ${failed ? "err" : ""} ${span.id === selectedId ? "sel" : ""} ${future(want) ? "fut" : ""}`}
                onClick={() => onSelect(span)}
              >
                <path
                  d={`M${x + side * 9} ${want} L${lx - side * 16} ${want} L${lx - side * 5} ${y}`}
                />
                <text x={lx} y={y + 4} textAnchor={side < 0 ? "end" : "start"}>
                  {failed ? "◆ " : ""}
                  {cut(label(span), labelRoom)}
                </text>
              </g>
            );
          })}
          {shown.map((span) => {
            const strand = g.strands[g.strandOf(span.actor)];
            if (!strand) return null;
            const fam = family(span);
            const x = strand.x;
            const sd = strand.side;
            const y0 = g.Y(g.at(span));
            const h = Math.max(g.Y(g.end(span)) - y0, 9);
            const ym = y0 + h / 2;
            const failed = span.status !== "ok";
            const finding = FINDING.has(span.name) && !failed;
            const colour = failed ? "var(--bad)" : `var(--t-${fam})`;
            const ys = ym + 9;
            return (
              <g
                key={span.id}
                className={`fg-ev ${span.id === selectedId ? "sel" : ""} ${future(y0) ? "fut" : ""}`}
                onPointerEnter={(event) =>
                  setHover({ span, x: event.clientX, y: event.clientY })
                }
                onPointerMove={(event) =>
                  setHover({ span, x: event.clientX, y: event.clientY })
                }
                onPointerLeave={() => setHover(null)}
                onClick={() => onSelect(span)}
              >
                <rect
                  x={x - 14}
                  y={y0 - 3}
                  width={28}
                  height={h + 6}
                  fill="transparent"
                />
                {touches(span) && (
                  <>
                    <path
                      className={`fg-thread ${span.name === "mitm/observe" ? "watch" : ""}`}
                      stroke={colour}
                      d={`M${x - sd * 5} ${ym} C${x - sd * 37} ${ym},${g.cx + sd * 34} ${ys},${g.cx + sd * 5} ${ys}`}
                    />
                    {finding ? (
                      <g>
                        <circle
                          cx={g.cx}
                          cy={ys}
                          r={8.5}
                          className="fg-fruit"
                          filter="url(#fg-glow)"
                        />
                        <path
                          d={`M${g.cx} ${ys - 4}l4 4-4 4-4-4z`}
                          className="fg-fruit-core"
                        />
                      </g>
                    ) : (
                      <circle
                        cx={g.cx}
                        cy={ys}
                        r={2.6}
                        fill={colour}
                        className="fg-touch"
                      />
                    )}
                  </>
                )}
                {span.kind === "model" ? (
                  <circle
                    className="fg-model"
                    cx={x}
                    cy={ym}
                    r={3.6}
                    stroke={colour}
                  />
                ) : (
                  <rect
                    className="fg-pill"
                    x={x - 4.5}
                    y={y0}
                    width={9}
                    height={h}
                    rx={4.5}
                    fill={finding ? "var(--gold)" : colour}
                  />
                )}
                {failed && (
                  <rect
                    className="fg-knot"
                    x={-5}
                    y={-5}
                    width={10}
                    height={10}
                    rx={1.5}
                    transform={`translate(${x} ${ym}) rotate(45)`}
                  />
                )}
                {!span.ended_at && span.duration_ms == null && live && (
                  <circle cx={x} cy={y0 + h} r={4} className="fg-running" />
                )}
              </g>
            );
          })}
          <g
            transform={`translate(0 ${Math.max(HEAD, playY)})`}
            className="fg-now"
          >
            {live && !play && <circle className="halo" cx={g.cx} r={7} />}
            <circle cx={g.cx} r={6.5} className="dot" filter="url(#fg-glow)" />
            <text x={g.cx} y={26} textAnchor="middle">
              {(live && !play ? "Now " : "") + clock(g.t0 + g.T(playY) * 1000)}
            </text>
          </g>
        </svg>
      </div>
      <div className="fg-legend">
        <span>
          <i className="sp spine" /> Target
        </span>
        <span>
          <i className="sp strand" /> Agent or operator
        </span>
        <span>
          <i className="sp pill fam-http" /> HTTP
        </span>
        <span>
          <i className="sp pill fam-exec" /> Shell
        </span>
        <span>
          <i className="sp pill fam-other" /> Other tool
        </span>
        <span>
          <i className="sp ring" /> Model call
        </span>
        <span>
          <i className="sp knot" /> Failed or refused
        </span>
        <span>
          <i className="sp fruit" /> Finding
        </span>
        <span className="fg-legend-note">
          A thread to the spine means the step touched the target · quiet time
          is compressed
        </span>
      </div>
      {hover && (
        <div
          className="fg-tip"
          role="tooltip"
          style={{
            left: Math.min(hover.x + 14, window.innerWidth - 300),
            top: hover.y + 14,
          }}
        >
          <b>{hover.span.name}</b>
          <span>{cut(label(hover.span), 120)}</span>
          <small>
            {hover.span.actor} · {clock(parse(hover.span.started_at))} ·{" "}
            {hover.span.duration_ms == null
              ? "running"
              : `${hover.span.duration_ms} ms`}
            {hover.span.status !== "ok"
              ? ` · ${hover.span.status.replace("_", " ")}`
              : ""}
          </small>
        </div>
      )}
    </div>
  );
}
