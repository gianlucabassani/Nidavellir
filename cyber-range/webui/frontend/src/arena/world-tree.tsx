// UX-22: the world tree. The run grows upward from its roots (the start) to
// the crown (now). The trunk is the agent itself: its own bookkeeping, model
// calls and steps that belong to no route. Each route it pursues, a declared
// hypothesis or else a target path, is a branch that sprouts when the route
// starts and grows while it is worked. Steps are leaves coloured by family; a
// failure is a red leaf. A branch ends in fruit when it produced a finding,
// withers when its hypothesis was refuted, and keeps a bud while still open.
// Self-reported gateway calls that duplicate an enforced call are folded into
// it. Quiet time is compressed; long silences show as a ring in the trunk.
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { Span } from "../types";
import { Icon } from "../shell/icons";
import "./world-tree.css";

export const TREE_LIMIT = 600;
const FOLD_SECONDS = 180;
const CROWN = 92; // space above "now"
const ROOTS = 118; // space below the start
const LANE = 44;
const TRUNK_GAP = 72;
const TWIN_MS = 3000;
const MIN_PATH_STEPS = 3;

type Family = "http" | "exec" | "model" | "other";
type Outcome = "finding" | "refuted" | "open" | "done";
const FINDING = new Set(["findings", "findings/manual", "report_finding"]);

const isSelf = (span: Span) => span.attrs?.["nv.self_reported"] === true;
function family(span: Span): Family {
  if (span.kind === "model") return "model";
  if (span.name.startsWith("http/") || span.name === "http_request")
    return "http";
  if (
    span.name === "exec" ||
    span.name.startsWith("exec/") ||
    span.name === "run_command"
  )
    return "exec";
  return "other";
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
const cut = (text: string, max: number) =>
  text.length > max ? `${text.slice(0, Math.max(1, max - 1))}…` : text;
const clamp = (value: number, low: number, high: number) =>
  Math.max(low, Math.min(high, value));
const grab = (text: string | null, pattern: RegExp) =>
  (text || "").match(pattern)?.[1] ?? null;

// Previews are capped server-side, so fields are read with patterns that
// survive a truncated JSON document.
const hypothesisOf = (span: Span) =>
  grab(span.input_preview, /"hypothesis_id"\s*:\s*"([^"]{1,64})"/);
function declared(span: Span) {
  const id =
    grab(
      span.input_preview,
      /"contract"\s*:\s*\{[\s\S]*?"id"\s*:\s*"([^"]{1,64})"/,
    ) || grab(span.input_preview, /"(?:hypothesis_)?id"\s*:\s*"([^"]{1,64})"/);
  const claim =
    grab(span.input_preview, /"title"\s*:\s*"([^"]{1,240})/) ||
    grab(span.input_preview, /"invariant"\s*:\s*"([^"]{1,240})/) ||
    grab(span.input_preview, /"expected_observable"\s*:\s*"([^"]{1,240})/);
  return { id, claim };
}
function pathRoute(span: Span) {
  const path = grab(span.input_preview, /"path"\s*:\s*"([^"]{1,512})"/);
  if (!path) return null;
  const parts = path.split(/[?#]/)[0].split("/").filter(Boolean);
  return parts.length ? `/${parts.slice(0, 2).join("/")}` : "/";
}
export function stepLabel(span: Span) {
  let detail = span.input_preview || "";
  try {
    const value: unknown = JSON.parse(detail);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const record = value as Record<string, unknown>;
      detail =
        [record.method, record.path, record.command, record.cmd, record.title]
          .filter((item) => typeof item === "string")
          .join(" ") ||
        Object.values(record)
          .filter((item) => ["string", "number"].includes(typeof item))
          .join(" ");
    }
  } catch {
    detail =
      [
        grab(detail, /"method"\s*:\s*"([^"]+)"/),
        grab(detail, /"path"\s*:\s*"([^"]+)"/),
        grab(detail, /"command"\s*:\s*"([^"]{1,200})/),
        grab(detail, /"title"\s*:\s*"([^"]{1,200})/),
      ]
        .filter(Boolean)
        .join(" ") || detail;
  }
  if (FINDING.has(span.name)) return detail || "Finding submitted";
  const base = family(span) === "exec" ? `$ ${detail}` : detail || span.name;
  return base.trim() || span.name;
}

type Route = {
  key: string;
  name: string;
  claim: string | null;
  actor: string;
  hypothesis: boolean;
  steps: Span[];
  findings: Span[];
  outcome: Outcome;
  start: number;
  end: number;
  side: number;
  col: number;
  x: number;
  birth: number;
  tip: number;
  rise: number;
};

/** Which spans are drawn, which route each belongs to, and the routes. */
export function routesOf(spans: Span[]) {
  // Fold self-reported twins of enforced calls into the enforced span.
  const enforced = spans.filter((span) => !isSelf(span));
  const twinOf = new Map<number, number>();
  for (const span of spans) {
    if (!isSelf(span)) continue;
    const at = parse(span.started_at);
    const hyp = hypothesisOf(span);
    const twin = enforced.find(
      (other) =>
        other.actor === span.actor &&
        Math.abs(parse(other.started_at) - at) <= TWIN_MS &&
        hypothesisOf(other) === hyp &&
        family(other) === family(span) &&
        FINDING.has(other.name) === FINDING.has(span.name),
    );
    if (twin) twinOf.set(span.id, twin.id);
  }
  const drawn = spans.filter((span) => !twinOf.has(span.id));
  const actors: string[] = [];
  for (const span of drawn)
    if (!actors.includes(span.actor)) actors.push(span.actor);
  // Route keys: a declared hypothesis wins; else an HTTP path prefix.
  const declaredBy = new Map<string, string | null>();
  const outcomes = new Map<string, string>();
  const keyOf = new Map<number, string>();
  const counts = new Map<string, number>();
  for (const span of drawn) {
    let key: string | null = null;
    if (span.name === "register_hypothesis") {
      const { id, claim } = declared(span);
      if (id) {
        key = `h:${id}`;
        if (!declaredBy.has(`${span.actor}|${key}`))
          declaredBy.set(`${span.actor}|${key}`, claim);
      }
    } else {
      const hyp = hypothesisOf(span);
      if (hyp) key = `h:${hyp}`;
      else if (family(span) === "http") {
        const path = pathRoute(span);
        if (path) key = `p:${path}`;
      }
    }
    if (span.name === "mark_hypothesis_tested" && key) {
      const outcome = grab(
        span.input_preview,
        /"outcome"\s*:\s*"([^"]{1,32})"/,
      );
      if (outcome) outcomes.set(`${span.actor}|${key}`, outcome);
    }
    if (!key) continue;
    const full = `${span.actor}|${key}`;
    keyOf.set(span.id, full);
    counts.set(full, (counts.get(full) ?? 0) + 1);
  }
  // Path routes need a few steps to earn a branch; findings join the route
  // their actor was working on just before.
  for (const [id, full] of keyOf)
    if (full.includes("|p:") && (counts.get(full) ?? 0) < MIN_PATH_STEPS)
      keyOf.delete(id);
  const lastRoute = new Map<string, string>();
  for (const span of drawn) {
    const full = keyOf.get(span.id);
    if (full) lastRoute.set(span.actor, full);
    else if (FINDING.has(span.name) && lastRoute.has(span.actor))
      keyOf.set(span.id, lastRoute.get(span.actor)!);
  }
  const routes = new Map<string, Route>();
  for (const span of drawn) {
    const full = keyOf.get(span.id);
    if (!full) continue;
    let route = routes.get(full);
    if (!route) {
      const raw = full.slice(full.indexOf("|") + 1);
      route = {
        key: full,
        name: raw.slice(2),
        claim: declaredBy.get(full) ?? null,
        actor: span.actor,
        hypothesis: raw.startsWith("h:"),
        steps: [],
        findings: [],
        outcome: "open",
        start: parse(span.started_at),
        end: parse(span.started_at),
        side: 0,
        col: 0,
        x: 0,
        birth: 0,
        tip: 0,
        rise: 0,
      };
      routes.set(full, route);
    }
    route.steps.push(span);
    if (FINDING.has(span.name) && span.status === "ok")
      route.findings.push(span);
    route.end = Math.max(
      route.end,
      span.ended_at ? parse(span.ended_at) : parse(span.started_at),
    );
  }
  for (const route of routes.values()) {
    const outcome = outcomes.get(route.key);
    route.outcome = route.findings.length
      ? "finding"
      : outcome === "refuted" || outcome === "unsupported"
        ? "refuted"
        : outcome
          ? "done"
          : "open";
  }
  // Only actors that own routes split the tree; their names then prefix them.
  const owners = actors.filter((actor) =>
    [...routes.values()].some((route) => route.actor === actor),
  );
  if (owners.length > 1)
    for (const route of routes.values())
      route.name = `${route.actor} · ${route.name}`;
  return {
    drawn,
    twinOf,
    keyOf,
    routes: [...routes.values()],
    actors: owners,
  };
}

function layoutOf(
  spans: Span[],
  width: number,
  liveNow: number | null,
  k = 1,
  ky = k,
) {
  const { drawn, twinOf, keyOf, routes, actors } = routesOf(spans);
  const t0 = parse(drawn[0]?.started_at);
  const at = (span: Span) => (parse(span.started_at) - t0) / 1000;
  const end = (span: Span) =>
    span.ended_at
      ? (parse(span.ended_at) - t0) / 1000
      : at(span) + (span.duration_ms || 0) / 1000;
  const lastEnd = Math.max(0, ...drawn.map(end));
  const nowS = liveNow ? Math.max(lastEnd, (liveNow - t0) / 1000) : lastEnd;
  // Warped time, measured upward from the start: anchors at each distinct
  // start, silences fold into a fixed-height ring.
  const starts = [...new Set(drawn.map(at))].sort((a, b) => a - b);
  const anchors: [number, number][] = [[0, 0]];
  const gaps: { a: number; b: number; u0: number; u1: number }[] = [];
  let prev = 0;
  let u = 0;
  let reach = 0;
  const ends = drawn.map((span) => [at(span), end(span)] as const);
  for (const s of starts) {
    if (s === 0) continue;
    for (const [a, e] of ends) if (a <= prev && e > reach) reach = e;
    if (s - prev >= FOLD_SECONDS && s - reach >= FOLD_SECONDS) {
      const fold = 64 * clamp(ky, 0.5, 1);
      const u0 = u + clamp((reach - prev) * ky, 8 * ky, 24 * ky);
      anchors.push([reach, u0]);
      gaps.push({ a: reach, b: s, u0, u1: u0 + fold });
      u = u0 + fold;
    } else u += clamp((s - prev) * ky, 5 * ky, 32 * ky);
    anchors.push([s, u]);
    prev = s;
  }
  anchors.push([Math.max(nowS, prev + 1), u + 30]);
  const U = (s: number) => {
    for (let i = 1; i < anchors.length; i++)
      if (s <= anchors[i][0]) {
        const [a0, u0] = anchors[i - 1];
        const [a1, u1] = anchors[i];
        return u0 + ((s - a0) / (a1 - a0 || 1)) * (u1 - u0);
      }
    return anchors[anchors.length - 1][1];
  };
  const uNow = U(nowS);
  const height = Math.ceil(uNow + CROWN + ROOTS);
  const base = height - ROOTS;
  const Y = (s: number) => base - U(s);
  const T = (py: number) => {
    const target = base - py;
    for (let i = 1; i < anchors.length; i++)
      if (target <= anchors[i][1]) {
        const [a0, u0] = anchors[i - 1];
        const [a1, u1] = anchors[i];
        return a0 + ((target - u0) / (u1 - u0 || 1)) * (a1 - a0);
      }
    return anchors[anchors.length - 1][0];
  };
  // Lanes: a branch takes the first free column on its side; a column frees
  // when its branch has finished growing. Two or more actors split the sides.
  const cx = Math.round(width / 2) + (width < 520 ? 14 : 0);
  const lane = LANE * k;
  const gapX = TRUNK_GAP * k;
  const maxCols = clamp(Math.floor((width / 2 - gapX - 120) / lane) + 1, 1, 6);
  const busy: Record<number, number[]> = { [-1]: [], [1]: [] };
  const sorted = [...routes].sort((a, b) => a.start - b.start);
  let lastSide = 1;
  for (const route of sorted) {
    const birth = Y(at(route.steps[0]));
    const tip = Y(Math.max(...route.steps.map(end)));
    const activeLeft = busy[-1].filter((top) => top < birth).length;
    const activeRight = busy[1].filter((top) => top < birth).length;
    const first =
      activeLeft === activeRight
        ? -lastSide
        : activeLeft < activeRight
          ? -1
          : 1;
    const sides =
      actors.length > 1
        ? [actors.indexOf(route.actor) % 2 === 0 ? -1 : 1]
        : [first, -first];
    let placed = false;
    for (const side of sides) {
      const cols = busy[side];
      // A column is free when its branch tip sits above (earlier than) this birth.
      let col = cols.findIndex((top) => top - 34 > birth);
      if (col < 0 && cols.length < maxCols) col = cols.length;
      if (col < 0) continue;
      cols[col] = tip;
      route.side = side;
      route.col = col;
      lastSide = side;
      placed = true;
      break;
    }
    if (!placed) {
      const side = sides[0];
      const cols = busy[side];
      const col = cols.indexOf(Math.max(...cols));
      cols[col] = Math.min(cols[col], tip);
      route.side = side;
      route.col = col;
    }
    route.x = cx + route.side * (gapX + route.col * lane);
    route.birth = birth;
    route.tip = Math.min(tip, birth - 10);
    route.rise = clamp(Math.abs(route.x - cx) * 1.25, 56 * k, 170 * k);
  }
  // A branch leaves the trunk at an angle and bends upward into its lane.
  const branchX = (route: Route, y: number) => {
    const p = clamp((route.birth - y) / route.rise, 0, 1);
    const ease = 1 - (1 - p) * (1 - p);
    const x0 = cx + route.side * 5;
    return x0 + (route.x - x0) * ease;
  };
  const routeOf = new Map<number, Route>();
  const byKey = new Map(routes.map((route) => [route.key, route]));
  for (const span of drawn) {
    const key = keyOf.get(span.id);
    if (key && byKey.has(key)) routeOf.set(span.id, byKey.get(key)!);
  }
  return {
    drawn,
    twinOf,
    routes,
    routeOf,
    actors,
    t0,
    at,
    end,
    Y,
    T,
    gaps: gaps.map((gap) => ({ ...gap, y0: base - gap.u1, y1: base - gap.u0 })),
    cx,
    nowS,
    yNow: Y(nowS),
    branchX,
    base,
    height,
  };
}

type Layout = ReturnType<typeof layoutOf>;

const OUTCOME_TEXT: Record<Outcome, string> = {
  finding: "Finding",
  refuted: "Refuted",
  done: "Tested",
  open: "Open",
};

export function WorldTree({
  spans,
  total,
  selectedId,
  onSelect,
  onKey,
  live,
  focus: focusProp,
  onFocus,
  hot = null,
  intro = false,
}: {
  spans: Span[];
  total: number;
  selectedId: number | null;
  onSelect: (span: Span) => void;
  onKey: (event: KeyboardEvent) => void;
  live: boolean;
  /** UX-26: the focused route, controlled by the Timeline page. */
  focus?: string | null;
  onFocus?: (key: string | null) => void;
  /** A route hovered in the routes panel. */
  hot?: string | null;
  /** Grow the tree from its roots when it first appears. */
  intro?: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(820);
  const [now, setNow] = useState(Date.now());
  const [hover, setHover] = useState<{
    span: Span;
    x: number;
    y: number;
  } | null>(null);
  const [localFocus, setLocalFocus] = useState<string | null>(null);
  const focus = focusProp !== undefined ? focusProp : localFocus;
  const setFocus = onFocus || setLocalFocus;
  const [play, setPlay] = useState<{ y: number; on: boolean } | null>(null);
  const [speed, setSpeed] = useState(1);
  // The intro growth runs at its own rate so it lasts about two seconds.
  const [introRate, setIntroRate] = useState<number | null>(null);
  const seen = useRef<number | null>(null);
  const k = 1.4;
  // UX-26: "whole run" fits the run into the visible height; "detail" spreads it.
  const [zoom, setZoom] = useState<"fit" | "detail">("fit");
  const [viewH, setViewH] = useState(640);
  const shown = spans.length > TREE_LIMIT ? spans.slice(-TREE_LIMIT) : spans;
  useEffect(() => {
    const element = wrap.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setWidth(Math.max(320, Math.min(1600, element.clientWidth))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setViewH(Math.max(320, element.clientHeight)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  });
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(timer);
  }, [live]);
  const g: Layout | null = useMemo(() => {
    if (!shown.length) return null;
    const liveAt = live ? now : null;
    if (zoom === "detail") return layoutOf(shown, width, liveAt, k);
    const full = layoutOf(shown, width, liveAt, k, 1);
    const room = Math.max(240, viewH - CROWN - ROOTS - 8);
    let ky = clamp(room / Math.max(1, full.base - full.yNow), 0.08, k);
    // Folds and margins do not scale linearly: correct once.
    const first = layoutOf(shown, width, liveAt, k, ky);
    const over = (first.base - first.yNow) / room;
    if (over <= 1) return first;
    ky = clamp(ky / over - 0.002, 0.04, k);
    return layoutOf(shown, width, liveAt, k, ky);
  }, [shown, width, live, now, zoom, viewH]);
  // The first time the tree appears it grows from its roots; steps that
  // arrive afterwards sprout with an animation.
  useEffect(() => {
    if (!g || seen.current != null) return;
    seen.current = Math.max(...shown.map((span) => span.id));
    if (!intro) return;
    const start = g.base + 20;
    setIntroRate(Math.max(1, (start - g.yNow) / 120 / 2.2));
    setPlay({ y: start, on: true });
  }, [g, intro, shown]);
  // Focusing a route scrolls its branch into the middle of the view.
  useEffect(() => {
    if (!focus || !g || !scroller.current) return;
    const route = g.routes.find((item) => item.key === focus);
    if (!route) return;
    scroller.current.scrollTo({
      top: (route.tip + route.birth) / 2 - scroller.current.clientHeight / 2,
      behavior: "smooth",
    });
  }, [focus, g]);
  // The crown is the newest moment: stay at the top while not replaying.
  useEffect(() => {
    if (!play && scroller.current) scroller.current.scrollTop = 0;
  }, [shown.length, play]);
  // Keep the selected step in view (keyboard selection from the live view).
  const shownId =
    selectedId != null ? (g?.twinOf.get(selectedId) ?? selectedId) : null;
  useEffect(() => {
    if (shownId == null || !scroller.current) return;
    const mark = scroller.current.querySelector<SVGGElement>(
      `[data-span="${shownId}"]`,
    );
    const box = scroller.current.getBoundingClientRect();
    const at = mark?.getBoundingClientRect();
    if (at && (at.top < box.top + 20 || at.bottom > box.bottom - 20))
      scroller.current.scrollTop += at.top - box.top - box.height / 2;
  }, [shownId]);
  // Replay: the tree grows from the roots at a steady pace.
  useEffect(() => {
    if (!play?.on || !g) return;
    let frame = 0;
    let last = performance.now();
    const step = (ts: number) => {
      const dt = Math.min(64, ts - last);
      last = ts;
      setPlay((current) => {
        if (!current?.on) return current;
        const rate = introRate ?? speed;
        const y = Math.max(g.yNow, current.y - (dt / 1000) * 120 * rate);
        if (scroller.current)
          scroller.current.scrollTop = y - scroller.current.clientHeight * 0.4;
        if (y <= g.yNow && introRate != null) {
          setIntroRate(null);
          return null;
        }
        return y <= g.yNow ? { y: g.yNow, on: false } : { y, on: true };
      });
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [play?.on, g, speed, introRate]);

  if (!g)
    return (
      <div className="yg-empty" ref={wrap}>
        <p>
          No steps yet. The tree grows here as agents and operators act: one
          branch for each route they pursue.
        </p>
      </div>
    );
  const W = width;
  const playY = play ? play.y : g.yNow;
  const future = (y: number) => y < playY - 0.5;
  const dim = (route: Route | undefined) =>
    focus != null && route?.key !== focus;
  const ticks: { y: number; t: number }[] = [];
  let lastTick = 1e9;
  for (let s = 0; s <= g.nowS; s += 10) {
    const y = g.Y(s);
    if (
      lastTick - y < 56 ||
      g.gaps.some((gap) => y > gap.y0 - 6 && y < gap.y1 + 6)
    )
      continue;
    const t = g.t0 + s * 1000;
    if (
      ticks.length &&
      clock(ticks[ticks.length - 1].t, false) === clock(t, false)
    )
      continue;
    lastTick = y;
    ticks.push({ y, t });
  }
  // The trunk tapers from the roots to the crown, with a gentle sway.
  const trunkTop = g.yNow - 18;
  const half = (y: number) =>
    (3 + 6 * clamp((y - trunkTop) / Math.max(1, g.base - trunkTop), 0, 1)) * k;
  const sway = (y: number) => Math.sin(y / 140) * 1.6;
  const edge = (side: number) => {
    const points: string[] = [];
    const stepY = 24;
    for (let y = g.base + 6; y >= trunkTop; y -= stepY)
      points.push(
        `${(g.cx + sway(y) + side * half(y)).toFixed(1)} ${y.toFixed(1)}`,
      );
    points.push(
      `${(g.cx + sway(trunkTop) + side * half(trunkTop)).toFixed(1)} ${trunkTop}`,
    );
    return points;
  };
  // Each branch is a tapered outline along its curve, thick where it leaves
  // the trunk and fine at the tip.
  const branchPath = (route: Route) => {
    const span = Math.max(1, route.birth - route.tip);
    const ys: number[] = [];
    for (let y = route.birth + 3; y > route.tip; y -= 5) ys.push(y);
    ys.push(route.tip);
    const sideA: string[] = [];
    const sideB: string[] = [];
    for (const y of ys) {
      const x = g.branchX(route, y);
      const dx = g.branchX(route, y - 2) - x;
      const len = Math.hypot(dx, 2);
      const w =
        (route.outcome === "finding" ? 2.4 : 1.8) *
          k *
          (1 - 0.6 * clamp((route.birth - y) / span, 0, 1)) +
        0.4;
      const nx = (2 / len) * w;
      const ny = (dx / len) * w;
      sideA.push(`${(x - nx).toFixed(1)} ${(y - ny).toFixed(1)}`);
      sideB.push(`${(x + nx).toFixed(1)} ${(y + ny).toFixed(1)}`);
    }
    return `M${sideA.join(" L")} L${sideB.reverse().join(" L")} Z`;
  };
  const left = edge(-1);
  const right = edge(1).reverse();
  const trunkPath = `M${left.join(" L")} L${right.join(" L")} Z`;
  // Branch labels sit just above each tip, pushed apart per side.
  const roomFor = (route: Route) =>
    Math.max(
      10,
      Math.floor(
        (route.side < 0
          ? g.branchX(route, route.tip) - 70
          : W - g.branchX(route, route.tip) - 14) / 6.4,
      ),
    );
  const taken: Record<string, number[]> = {};
  const labels = g.routes
    .map((route) => {
      const tipY = g.Y(Math.max(...route.steps.map(g.end)));
      return { route, tipY };
    })
    .sort((a, b) => b.tipY - a.tipY)
    .map(({ route, tipY }) => {
      const lane = `${route.side}`;
      const used = (taken[lane] ||= []);
      let y = tipY - 16;
      for (
        let i = 0;
        i < 6 && used.some((other) => Math.abs(other - y) < 30);
        i++
      )
        y -= 30;
      const ok = !used.some((other) => Math.abs(other - y) < 30);
      if (ok) used.push(y);
      return { route, tipY, y, ok };
    });
  const replayStart = g.base + 20;
  return (
    <div className="world-tree page" ref={wrap}>
      <div className="yg-bar">
        <button
          type="button"
          className="button button-outline"
          onClick={() =>
            setPlay((current) =>
              current?.on
                ? { ...current, on: false }
                : {
                    y:
                      current && current.y > g.yNow + 1
                        ? current.y
                        : replayStart,
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
          min={0}
          max={Math.ceil(replayStart - g.yNow)}
          value={Math.round(replayStart - playY)}
          onChange={(event) =>
            setPlay({ y: replayStart - Number(event.target.value), on: false })
          }
        />
        <span className="yg-clock">
          {clock(g.t0 + Math.max(0, g.T(playY)) * 1000)}
        </span>
        <div className="seg" role="group" aria-label="Zoom">
          <button
            type="button"
            aria-pressed={zoom === "fit"}
            onClick={() => setZoom("fit")}
          >
            Whole run
          </button>
          <button
            type="button"
            aria-pressed={zoom === "detail"}
            onClick={() => setZoom("detail")}
          >
            Detail
          </button>
        </div>
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
        {spans.length > TREE_LIMIT && (
          <span className="yg-cap">
            Newest {TREE_LIMIT} of {total} steps · the list view holds all
          </span>
        )}
      </div>
      <div
        className="yg-scroll"
        ref={scroller}
        tabIndex={0}
        role="group"
        aria-label={`World tree, ${g.drawn.length} steps on ${g.routes.length} routes. Arrow keys move the selection.`}
        onKeyDown={onKey}
      >
        <svg
          className="yg-svg"
          width={W}
          height={g.height}
          viewBox={`0 0 ${W} ${g.height}`}
        >
          <defs>
            <filter
              id="yg-glow"
              filterUnits="userSpaceOnUse"
              x={-40}
              y={-40}
              width={W + 80}
              height={g.height + 80}
            >
              <feGaussianBlur stdDeviation="3.2" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <linearGradient id="yg-bark" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="var(--yg-bark-edge)" />
              <stop offset=".45" stopColor="var(--yg-bark)" />
              <stop offset="1" stopColor="var(--yg-bark-edge)" />
            </linearGradient>
            <radialGradient id="yg-well" cx=".5" cy=".5" r=".5">
              <stop offset="0" stopColor="var(--yg-well)" stopOpacity=".9" />
              <stop offset="1" stopColor="var(--yg-well)" stopOpacity="0" />
            </radialGradient>
            <clipPath id="yg-grown">
              <rect x={-40} y={playY} width={W + 80} height={g.height} />
            </clipPath>
          </defs>
          {ticks.map((tick) => (
            <g key={tick.y} className="yg-tick">
              <line x1={52} x2={W - 8} y1={tick.y} y2={tick.y} />
              <text x={4} y={tick.y + 4}>
                {clock(tick.t, false)}
              </text>
            </g>
          ))}
          {/* Roots and the well: where the run started. */}
          <ellipse
            cx={g.cx}
            cy={g.base + 52}
            rx={150}
            ry={26}
            fill="url(#yg-well)"
          />
          <g className="yg-roots">
            {[-1, 1].flatMap((side) =>
              [0, 1, 2].map((i) => (
                <path
                  key={`${side}${i}`}
                  d={`M${g.cx + side * 2} ${g.base} C${g.cx + side * (14 + i * 10)} ${g.base + 14 + i * 4},${g.cx + side * (40 + i * 30)} ${g.base + 22 + i * 8},${g.cx + side * (58 + i * 38)} ${g.base + 44 + i * 12}`}
                  strokeWidth={3 - i * 0.8}
                />
              )),
            )}
          </g>
          <text
            className="yg-start"
            x={g.cx}
            y={g.base + 88}
            textAnchor="middle"
          >
            Started {clock(g.t0)}
          </text>
          {g.gaps.map((gap) => (
            <g key={gap.a} className="yg-gap">
              <ellipse cx={g.cx} cy={gap.y1 - 8} rx={14} ry={3.5} />
              <ellipse cx={g.cx} cy={gap.y0 + 8} rx={14} ry={3.5} />
              <text x={g.cx + 22} y={(gap.y0 + gap.y1) / 2 + 4}>
                {Math.round((gap.b - gap.a) / 60)} min quiet
              </text>
            </g>
          ))}
          <g clipPath="url(#yg-grown)">
            <path className="yg-trunk" d={trunkPath} fill="url(#yg-bark)" />
            <path
              className="yg-grain"
              d={`M${g.cx + sway(g.base)} ${g.base} ${Array.from(
                { length: Math.ceil((g.base - trunkTop) / 24) },
                (_, i) => {
                  const y = g.base - (i + 1) * 24;
                  return `L${(g.cx + sway(y) - 1).toFixed(1)} ${Math.max(trunkTop, y).toFixed(1)}`;
                },
              ).join(" ")}`}
            />
            {g.routes.map((route) => (
              <path
                key={route.key}
                className={`yg-branch ${route.outcome} ${dim(route) ? "dim" : ""} ${focus === route.key ? "on" : ""} ${hot === route.key ? "hot" : ""}`}
                d={branchPath(route)}
              />
            ))}
          </g>
          {g.drawn.map((span, index) => {
            const route = g.routeOf.get(span.id);
            const y0 = g.Y(g.at(span));
            const failed = span.status !== "ok";
            const finding = FINDING.has(span.name) && !failed;
            const fam = family(span);
            const colour = failed ? "var(--bad)" : `var(--t-${fam})`;
            const selected = span.id === shownId;
            const fresh = seen.current != null && span.id > seen.current;
            const cls = `yg-ev ${selected ? "sel" : ""} ${future(y0) ? "fut" : ""} ${dim(route) ? "dim" : ""} ${fresh ? "fresh" : ""} ${route && hot === route.key ? "hot" : ""}`;
            const events = {
              onPointerEnter: (event: ReactPointerEvent) =>
                setHover({ span, x: event.clientX, y: event.clientY }),
              onPointerMove: (event: ReactPointerEvent) =>
                setHover({ span, x: event.clientX, y: event.clientY }),
              onPointerLeave: () => setHover(null),
              onClick: () => onSelect(span),
            };
            if (span.name === "register_hypothesis" && route) {
              const x = g.cx + sway(y0) + route.side * (half(y0) + 5);
              return (
                <g
                  key={span.id}
                  data-span={span.id}
                  className={`${cls} yg-sprout`}
                  {...events}
                >
                  <rect
                    x={x - 9}
                    y={y0 - 9}
                    width={18}
                    height={18}
                    fill="transparent"
                  />
                  <path d={`M${x} ${y0 - 4.5}l3 4.5-3 4.5-3-4.5z`} />
                </g>
              );
            }
            if (span.name === "mark_hypothesis_tested" && route) return null;
            if (!route) {
              // Trunk steps: knots in the bark, alternating sides.
              const side = index % 2 === 0 ? -1 : 1;
              const x = g.cx + sway(y0) + side * (half(y0) + 4);
              return (
                <g
                  key={span.id}
                  data-span={span.id}
                  className={`${cls} yg-knot`}
                  {...events}
                >
                  <rect
                    x={x - 8}
                    y={y0 - 8}
                    width={16}
                    height={16}
                    fill="transparent"
                  />
                  {finding ? (
                    <circle
                      cx={x}
                      cy={y0}
                      r={6}
                      className="yg-fruit"
                      filter="url(#yg-glow)"
                    />
                  ) : span.kind === "model" ? (
                    <circle
                      cx={x}
                      cy={y0}
                      r={3.2}
                      className="yg-ring"
                      stroke={colour}
                    />
                  ) : (
                    <circle cx={x} cy={y0} r={2.6} fill={colour} />
                  )}
                  {selected && (
                    <circle cx={x} cy={y0} r={7.5} className="yg-sel" />
                  )}
                </g>
              );
            }
            if (finding) return null; // drawn as the branch's fruit
            // Leaves: alternate sides of the branch, longer for longer steps.
            const order = route.steps.indexOf(span);
            const side = order % 2 === 0 ? -1 : 1;
            const len =
              clamp(
                6 + Math.log2(1 + (span.duration_ms ?? 0) / 400) * 1.8,
                6,
                13,
              ) * k;
            const x = g.branchX(route, y0);
            const lean =
              (Math.atan2(g.branchX(route, y0 - 2) - x, 2) * 180) / Math.PI;
            const angle = (side < 0 ? -38 : 38) - lean;
            return (
              <g key={span.id} data-span={span.id} className={cls} {...events}>
                <rect
                  x={x - 12}
                  y={y0 - 6}
                  width={24}
                  height={12}
                  fill="transparent"
                />
                <ellipse
                  className={`yg-leaf ${failed ? "err" : ""}`}
                  cx={x + side * (len / 2 + 1.5)}
                  cy={y0}
                  rx={len / 2 + 0.5}
                  ry={2.3 * k}
                  fill={colour}
                  transform={`rotate(${angle} ${x} ${y0})`}
                />
                {span.kind === "model" && (
                  <circle
                    cx={x}
                    cy={y0}
                    r={2.6}
                    className="yg-ring"
                    stroke={colour}
                  />
                )}
                {failed && (
                  <rect
                    className="yg-notch"
                    x={-3.2}
                    y={-3.2}
                    width={6.4}
                    height={6.4}
                    transform={`translate(${x} ${y0}) rotate(45)`}
                  />
                )}
                {!span.ended_at && span.duration_ms == null && live && (
                  <circle cx={x} cy={y0} r={4} className="yg-running" />
                )}
                {selected && (
                  <circle cx={x} cy={y0} r={7.5} className="yg-sel" />
                )}
              </g>
            );
          })}
          {/* Tips: fruit for a finding, a withered end for a refuted
              hypothesis, a bud while the route is still open. */}
          {labels.map(({ route, tipY, y, ok }) => {
            const fruit = route.findings[route.findings.length - 1];
            const hidden = future(tipY);
            const fy = route.tip - 8;
            const tx = g.branchX(route, route.tip);
            const text =
              route.outcome === "finding"
                ? stepLabel(fruit)
                : route.claim || route.name;
            const anchorX = tx + route.side * 12;
            return (
              <g
                key={`t${route.key}`}
                className={`yg-tip ${route.outcome} ${hidden ? "fut" : ""} ${dim(route) ? "dim" : ""} ${hot === route.key ? "hot" : ""}`}
              >
                {route.outcome === "finding" ? (
                  <g
                    data-span={fruit.id}
                    className={`yg-ev ${fruit.id === shownId ? "sel" : ""}`}
                    onClick={() => onSelect(fruit)}
                    onPointerEnter={(event) =>
                      setHover({
                        span: fruit,
                        x: event.clientX,
                        y: event.clientY,
                      })
                    }
                    onPointerLeave={() => setHover(null)}
                  >
                    <circle
                      cx={tx}
                      cy={fy}
                      r={9}
                      className="yg-fruit"
                      filter="url(#yg-glow)"
                    />
                    <path
                      d={`M${tx} ${fy - 4.5}l4.5 4.5-4.5 4.5-4.5-4.5z`}
                      className="yg-fruit-core"
                    />
                  </g>
                ) : route.outcome === "refuted" ? (
                  <path
                    className="yg-wither"
                    d={`M${tx - 4} ${fy - 4}l8 8M${tx + 4} ${fy - 4}l-8 8`}
                  />
                ) : (
                  <circle
                    className={`yg-bud ${route.outcome === "open" && live ? "live" : ""}`}
                    cx={tx}
                    cy={fy}
                    r={4}
                  />
                )}
                {ok && (
                  <g
                    className="yg-label"
                    onClick={() =>
                      setFocus(focus === route.key ? null : route.key)
                    }
                  >
                    <title>
                      {route.claim
                        ? `${route.name}: ${route.claim}`
                        : route.name}
                    </title>
                    <text
                      x={anchorX}
                      y={y - 6}
                      textAnchor={route.side < 0 ? "end" : "start"}
                      className="h"
                    >
                      {cut(route.name, roomFor(route))}
                      <tspan className={`o ${route.outcome}`}>
                        {"  "}
                        {OUTCOME_TEXT[route.outcome]}
                      </tspan>
                    </text>
                    <text
                      x={anchorX}
                      y={y + 8}
                      textAnchor={route.side < 0 ? "end" : "start"}
                    >
                      {cut(
                        text === route.name
                          ? `${route.steps.length} steps`
                          : text,
                        roomFor(route),
                      )}
                    </text>
                  </g>
                )}
              </g>
            );
          })}
          <g
            transform={`translate(0 ${Math.min(g.base, playY)})`}
            className="yg-now"
          >
            <line x1={52} x2={W - 8} y1={0} y2={0} />
            {live && !play && <circle className="halo" cx={g.cx} r={8} />}
            <circle cx={g.cx} r={5.5} className="dot" filter="url(#yg-glow)" />
            <text x={W - 10} y={-6} textAnchor="end">
              {(live && !play ? "Now " : "") +
                clock(g.t0 + Math.max(0, g.T(playY)) * 1000)}
            </text>
          </g>
        </svg>
      </div>
      <div className="yg-legend">
        <span>
          <i className="sp trunk" /> Trunk: the agent's own steps
        </span>
        <span>
          <i className="sp branch" /> Branch: a route (hypothesis or path)
        </span>
        <span>
          <i className="sp leaf fam-http" /> HTTP
        </span>
        <span>
          <i className="sp leaf fam-exec" /> Shell
        </span>
        <span>
          <i className="sp leaf fam-model" /> Model
        </span>
        <span>
          <i className="sp leaf fam-other" /> Other
        </span>
        <span>
          <i className="sp leaf fam-bad" /> Failed or refused
        </span>
        <span>
          <i className="sp fruit" /> Finding
        </span>
        <span>
          <i className="sp wither" /> Refuted
        </span>
        <span>
          <i className="sp bud" /> Open
        </span>
        <span className="yg-legend-note">
          Grows upward from the start · quiet time is compressed · calls an
          agent reported itself are folded into the enforced call
        </span>
      </div>
      {hover && (
        <div
          className="yg-tip-pop"
          role="tooltip"
          style={{
            left: Math.min(hover.x + 14, window.innerWidth - 300),
            top: hover.y + 14,
          }}
        >
          <b>{hover.span.name}</b>
          <span>{cut(stepLabel(hover.span), 120)}</span>
          <small>
            {hover.span.actor} · {clock(parse(hover.span.started_at))} ·{" "}
            {hover.span.duration_ms == null
              ? "running"
              : `${hover.span.duration_ms} ms`}
            {hover.span.status !== "ok"
              ? ` · ${hover.span.status.replace("_", " ")}`
              : ""}
            {g.routeOf.get(hover.span.id)
              ? ` · ${g.routeOf.get(hover.span.id)!.name}`
              : ""}
          </small>
        </div>
      )}
    </div>
  );
}
