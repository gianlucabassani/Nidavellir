// UX-27: the run tree page. The tree has the whole page; what you open on it
// slides in from the right. The orchestrator folds the run (cycles, routes,
// episodes, failed calls, findings); the page polls it every 10 seconds while
// the arena is live, and loads a route's steps only when its drawer opens.
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { getJson } from "../../api";
import type { ArenaData } from "../../types";
import { TreeCanvas, type Hover, type Pick } from "./canvas";
import { RunDrawer } from "./drawer";
import {
  STATE_TEXT,
  branchesOf,
  duration,
  fitDensity,
  layout,
  type Branch,
  type RunTree,
} from "./model";
import "./run-tree.css";

function parseStart(value: string | null) {
  if (!value) return Date.now();
  const at = Date.parse(
    /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`,
  );
  return Number.isNaN(at) ? Date.now() : at;
}

export function RunTreePage({ arena }: { arena: ArenaData }) {
  const [tree, setTree] = useState<RunTree | null>(null);
  const [error, setError] = useState("");
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<Set<string>>(new Set());
  const [errOnly, setErrOnly] = useState(false);
  const [roomy, setRoomy] = useState(false);
  const [pick, setPick] = useState<Pick | null>(null);
  const [hover, setHover] = useState<{ h: Hover; x: number; y: number } | null>(
    null,
  );
  const [cursor, setCursor] = useState(-1);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1100);
  const [viewH, setViewH] = useState(800);
  const base = `/api/console/arenas/${encodeURIComponent(arena.id)}/run-tree`;

  useEffect(() => {
    const t = window.setTimeout(() => {
      setQuery(input.trim());
      setCursor(-1);
    }, 300);
    return () => window.clearTimeout(t);
  }, [input]);
  const load = useCallback(
    (signal?: AbortSignal) =>
      getJson<RunTree>(
        query.length >= 2 ? `${base}?q=${encodeURIComponent(query)}` : base,
        signal,
      )
        .then((data) => {
          setTree(data);
          setError("");
        })
        .catch((reason: unknown) => {
          if (!signal?.aborted)
            setError(
              reason instanceof Error ? reason.message : "Run tree unavailable",
            );
        }),
    [base, query],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    if (!tree?.live) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [tree?.live, load]);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      setWidth((old) => (Math.abs(old - w) > 24 ? w : old));
    });
    observer.observe(element);
    const onResize = () => setViewH(window.innerHeight);
    onResize();
    window.addEventListener("resize", onResize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", onResize);
    };
  }, [tree == null]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPick(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const { branches, lanes } = useMemo(
    () =>
      tree
        ? branchesOf(tree)
        : { branches: [] as Branch[], lanes: { left: 1, right: 1 } },
    [tree],
  );
  const g = useMemo(() => {
    if (!tree) return null;
    const fit = fitDensity(
      tree,
      branches,
      lanes,
      width,
      Math.max(560, viewH - 230),
    );
    return layout(
      tree,
      branches,
      lanes,
      width,
      roomy ? Math.max(0.6, fit * 2.2) : fit,
    );
  }, [tree, branches, lanes, width, viewH, roomy]);

  // Replay: the tree regrows; slow where things start, quick through solo work.
  const [replay, setReplay] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const [speed, setSpeed] = useState(1);
  const rp = useRef({ paused: false, speed: 1, raf: 0, last: 0, t: 0 });
  useEffect(() => {
    rp.current.paused = paused;
    rp.current.speed = speed;
  }, [paused, speed]);
  useEffect(() => () => cancelAnimationFrame(rp.current.raf), []);
  const stopReplay = () => {
    cancelAnimationFrame(rp.current.raf);
    setReplay(null);
    setPaused(false);
  };
  const startReplay = () => {
    if (!tree) return;
    const s = rp.current;
    cancelAnimationFrame(s.raf);
    Object.assign(s, { t: 0, last: 0 });
    setPaused(false);
    const dur = Math.max(1, tree.duration);
    const tick = (now: number) => {
      const dt = s.last ? Math.min(0.1, (now - s.last) / 1000) : 0;
      s.last = now;
      if (!s.paused && s.t < dur) {
        const soon =
          branches.some((b) => b.ep.a >= s.t && b.ep.a - s.t < 40) ||
          tree.cycles.some((c) => c.a >= s.t && c.a - s.t < 40);
        const busy = branches.some((b) => b.ep.a <= s.t && b.ep.b >= s.t);
        s.t = Math.min(
          dur,
          s.t + dt * (soon ? 40 : busy ? 140 : 900) * s.speed,
        );
      }
      setReplay(s.t);
      if (s.t >= dur) {
        window.setTimeout(() => setReplay(null), 900);
        return;
      }
      s.raf = requestAnimationFrame(tick);
    };
    s.raf = requestAnimationFrame(tick);
  };

  const onHover = useCallback(
    (h: Hover, event: MouseEvent) =>
      setHover({ h, x: event.clientX, y: event.clientY }),
    [],
  );
  const onLeave = useCallback(() => setHover(null), []);
  if (!tree || !g)
    return (
      <div className="rt-page" ref={box}>
        <p className="muted rt-wait">{error || "Folding the run…"}</p>
      </div>
    );
  const t0 = parseStart(tree.started_at);
  const clock = (t: number) =>
    new Date(t0 + t * 1000).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
    });
  const clockS = (t: number) =>
    new Date(t0 + t * 1000).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  const hits = tree.search?.hits || {};
  const searching = query.length >= 2;
  const dimmed = (branch: Branch) =>
    (pick?.kind === "route" && pick.key !== branch.route.key) ||
    (errOnly && !branch.route.errors) ||
    (kinds.size > 0 && !kinds.has(branch.route.kind)) ||
    (searching && !hits[branch.route.key]);
  const hitRoutes = tree.routes.filter((r) => hits[r.key]);
  const stepHit = (dir: 1 | -1) => {
    if (!hitRoutes.length) return;
    const next =
      cursor < 0
        ? dir > 0
          ? 0
          : hitRoutes.length - 1
        : (cursor + dir + hitRoutes.length) % hitRoutes.length;
    setCursor(next);
    setPick({ kind: "route", key: hitRoutes[next].key });
  };
  const findings = tree.findings.length;
  const T = replay ?? g.dur;
  const day = new Date(t0).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
  });
  const selected =
    pick?.kind === "route"
      ? pick.key
      : pick?.kind === "cycle"
        ? `cycle:${pick.i}`
        : null;

  return (
    <div className="rt-page">
      <header className="rt-head">
        <div>
          <span className="eyebrow">Timeline</span>
          <h2>
            Run of {day}, {clock(0)} to{" "}
            {tree.live ? "now" : clock(tree.duration)}
          </h2>
          <p>
            <b>
              {tree.cycles.length}{" "}
              {tree.cycles.length === 1 ? "cycle" : "cycles"}
            </b>{" "}
            and <b>{tree.routes.length} routes</b> over{" "}
            {duration(tree.duration)}, {tree.totals.steps} steps.{" "}
            {tree.totals.errors > 0 && (
              <span className="err">{tree.totals.errors} calls failed. </span>
            )}
            {findings > 0 &&
              `${findings} ${findings === 1 ? "finding was" : "findings were"} reported.`}
          </p>
          {tree.truncated && (
            <p className="muted">
              This run has more steps than the tree reads at once; the newest
              are shown.
            </p>
          )}
        </div>
      </header>

      <div className="rt-bar">
        <div className="rt-row">
          <label className="rt-search">
            <input
              type="search"
              value={input}
              aria-label="Search the run"
              placeholder="Search requests, commands and inputs"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                if (input.trim() !== query) setQuery(input.trim());
                else stepHit(event.shiftKey ? -1 : 1);
              }}
            />
            <span className="muted" aria-live="polite">
              {searching
                ? tree.search?.total
                  ? `${tree.search.total} steps in ${hitRoutes.length} routes`
                  : "No mentions"
                : ""}
            </span>
            <button
              type="button"
              className="inline-action"
              disabled={!hitRoutes.length}
              onClick={() => stepHit(-1)}
            >
              Previous
            </button>
            <button
              type="button"
              className="inline-action"
              disabled={!hitRoutes.length}
              onClick={() => stepHit(1)}
            >
              Next
            </button>
          </label>
          <div className="rt-chips" role="group" aria-label="Filter routes">
            {(["hypothesis", "path"] as const).map((kind) => (
              <button
                key={kind}
                type="button"
                aria-pressed={kinds.has(kind)}
                onClick={() =>
                  setKinds((current) => {
                    const next = new Set(current);
                    if (next.has(kind)) next.delete(kind);
                    else next.add(kind);
                    return next;
                  })
                }
              >
                {kind === "hypothesis" ? "Hypotheses" : "Target paths"}
              </button>
            ))}
            <button
              type="button"
              aria-pressed={errOnly}
              onClick={() => setErrOnly(!errOnly)}
            >
              Only branches with errors
            </button>
          </div>
        </div>
        <div className="rt-row">
          <button
            type="button"
            className="rt-btn"
            aria-pressed={replay != null && !paused}
            onClick={() =>
              replay != null ? setPaused(!paused) : startReplay()
            }
          >
            {replay != null ? (paused ? "Resume" : "Pause") : "Replay the run"}
          </button>
          {replay != null && (
            <>
              <button type="button" className="rt-btn" onClick={stopReplay}>
                Stop replay
              </button>
              <button
                type="button"
                className="rt-btn"
                onClick={() => setSpeed(speed === 1 ? 3 : speed === 3 ? 8 : 1)}
              >
                Speed {speed}×
              </button>
              <span className="rt-clock">{clockS(replay)}</span>
            </>
          )}
          <button
            type="button"
            className="rt-btn"
            aria-pressed={roomy}
            onClick={() => setRoomy(!roomy)}
          >
            {roomy ? "Fit to page" : "Roomier"}
          </button>
          <div className="rt-legend">
            <span>
              <i className="lg-err" /> Failed call
            </span>
            <span>
              <i className="lg-fruit" /> Finding
            </span>
            <span>
              <i className="lg-open" /> Open
            </span>
            <span>
              <i className="lg-wither" /> Refuted
            </span>
            <span>
              <i className="lg-ring" /> Agent cycle
            </span>
          </div>
        </div>
      </div>

      <div className="rt-canvas" ref={box}>
        {tree.totals.steps === 0 ? (
          <p className="muted rt-wait">
            No steps yet. The tree grows here as the agent works.
          </p>
        ) : (
          <TreeCanvas
            tree={tree}
            branches={branches}
            g={g}
            T={T}
            selected={selected}
            dimmed={dimmed}
            hits={hits}
            onHover={onHover}
            onLeave={onLeave}
            onPick={(next) => {
              setHover(null);
              setPick(next);
            }}
            clock={clock}
          />
        )}
      </div>
      {hover && (
        <HoverCard
          tree={tree}
          branches={branches}
          hover={hover}
          clock={clock}
          clockS={clockS}
          hits={hits}
        />
      )}
      {pick && (
        <>
          <div
            className="rt-backdrop"
            aria-hidden="true"
            onClick={() => setPick(null)}
          />
          <RunDrawer
            key={JSON.stringify(pick)}
            arenaId={arena.id}
            tree={tree}
            pick={pick}
            query={searching ? query : ""}
            clock={clockS}
            onPick={setPick}
            onClose={() => setPick(null)}
          />
        </>
      )}
    </div>
  );
}

function HoverCard({
  tree,
  branches,
  hover,
  clock,
  clockS,
  hits,
}: {
  tree: RunTree;
  branches: Branch[];
  hover: { h: Hover; x: number; y: number };
  clock: (t: number) => string;
  clockS: (t: number) => string;
  hits: Record<string, number>;
}) {
  const { h } = hover;
  let body: ReactNode = null;
  if (h.kind === "branch") {
    const branch = branches.find((b) => b.id === h.id);
    if (branch) {
      const { route, ep } = branch;
      body = (
        <>
          <h4>
            <i className={`rt-dot ${route.state}`} />
            {route.name} <small>{STATE_TEXT[route.state]}</small>
          </h4>
          <p className="muted">
            {clock(ep.a)} to {clock(ep.b)}
            {route.episodes.length > 1
              ? `, episode ${branch.index + 1} of ${route.episodes.length}`
              : ""}
          </p>
          {route.claim && <p>{route.claim}</p>}
          <p className="muted">
            <b>{ep.steps}</b> steps here, <b>{route.steps}</b> in all
            {route.errors ? (
              <>
                , <b className="err">{route.errors}</b> failed
              </>
            ) : null}
            {hits[route.key] ? (
              <>
                , <b className="hits">{hits[route.key]}</b> matches
              </>
            ) : null}
          </p>
          <p className="rt-hint">Click to open its steps</p>
        </>
      );
    }
  } else if (h.kind === "ring") {
    const c = tree.cycles[h.i];
    body = (
      <>
        <h4>
          <i className="rt-dot trunk" />
          Cycle {c.i + 1}
        </h4>
        <p className="muted">
          {clock(c.a)} to {clock(c.b)}, {duration(c.b - c.a)}
        </p>
        <p>
          {c.steps} steps{c.errors ? `, ${c.errors} failed` : ""};{" "}
          {tree.routes.filter((r) => r.a <= c.b && r.b >= c.a).length} routes
          worked.
        </p>
      </>
    );
  } else if (h.kind === "trunk") {
    const running = tree.routes.filter((r) =>
      r.episodes.some((ep) => ep.a <= h.t && ep.b >= h.t),
    );
    body = (
      <>
        <h4>
          <i className="rt-dot trunk" />
          The agent at {clockS(h.t)}
        </h4>
        <p>
          {running.length
            ? `Working on ${running.map((r) => r.name).join(", ")}`
            : "Between routes"}
        </p>
        <p className="rt-hint">Click for the agent's own steps</p>
      </>
    );
  } else if (h.kind === "knot") {
    body = (
      <>
        <h4>
          <i className="rt-dot err" />
          {h.list.length} failed call{h.list.length > 1 ? "s" : ""}
        </h4>
        {h.list.slice(0, 4).map((e) => (
          <p key={e.id} className="muted">
            <b>{e.tool}</b> {clockS(e.t)} · {e.status.replace("_", " ")}
            <br />
            {e.target}
          </p>
        ))}
      </>
    );
  } else if (h.kind === "fruit") {
    const f = tree.findings.find((item) => item.id === h.id);
    if (f)
      body = (
        <>
          <h4>
            <i className="rt-dot finding" />
            Finding{f.severity ? `, ${f.severity}` : ""}
          </h4>
          <p className="muted">{clockS(f.t)}</p>
          <p>{f.title}</p>
        </>
      );
  }
  if (!body) return null;
  const x = Math.min(hover.x + 18, window.innerWidth - 340);
  const y = Math.min(hover.y + 18, window.innerHeight - 230);
  return (
    <div className="rt-card" role="tooltip" style={{ left: x, top: y }}>
      {body}
    </div>
  );
}
