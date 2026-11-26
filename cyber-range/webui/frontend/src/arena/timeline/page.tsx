// UX-28: the Timeline page. The run against its time budget: the serpent on
// the left, the run in numbers on the right. The orchestrator folds the run;
// the page polls it every 10 seconds while the arena is live.
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { getJson } from "../../api";
import type { ArenaData } from "../../types";
import {
  C,
  clustersOf,
  duration,
  frameOf,
  verdictClass,
  type Cluster,
  type Timeline,
} from "./model";
import { Serpent } from "./serpent";
import { SidePanel } from "./side";
import "./timeline.css";

function parseStart(value: string | null) {
  if (!value) return Date.now();
  const at = Date.parse(
    /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`,
  );
  return Number.isNaN(at) ? Date.now() : at;
}

function HoverCard({
  cluster,
  x,
  y,
  clock,
}: {
  cluster: Cluster;
  x: number;
  y: number;
  clock: (t: number) => string;
}) {
  const findings = cluster.list.flatMap((e) =>
    e.kind === "finding" ? [e] : [],
  );
  const fails = cluster.list.filter((e) => e.kind === "fail").length;
  const verdicts = cluster.list.flatMap((e) =>
    e.kind === "verdict" ? [e] : [],
  );
  const kinds = (k: string) =>
    verdicts.filter((e) => verdictClass(e.item.outcome) === k).length;
  return (
    <div
      className="tl-card"
      role="tooltip"
      style={{
        left: Math.min(x + 14, window.innerWidth - 340),
        top: Math.min(y + 14, window.innerHeight - 140),
      }}
    >
      {findings.length === 1 && <b>◆ {findings[0].item.title}</b>}
      {findings.length > 1 && <b>◆ {findings.length} findings</b>}
      {fails > 0 && (
        <b className="bad">
          × {fails} failed {fails === 1 ? "call" : "calls"}
        </b>
      )}
      {verdicts.length === 1 && (
        <>
          <b>
            {verdicts[0].item.id} · {verdicts[0].item.outcome || "tested"}
          </b>
          {verdicts[0].item.claim && <span>{verdicts[0].item.claim}</span>}
        </>
      )}
      {verdicts.length > 1 && (
        <b>
          {verdicts.length} verdicts: {kinds("supported")} supported,{" "}
          {kinds("refuted")} refuted
          {kinds("other") ? `, ${kinds("other")} other` : ""}
        </b>
      )}
      <small>
        {clock(cluster.list[0].t)} · {(cluster.f0 * 100).toFixed(1)}% of the
        budget · click to open
      </small>
    </div>
  );
}

export function TimelinePage({ arena }: { arena: ArenaData }) {
  const [tree, setTree] = useState<Timeline | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [finding, setFinding] = useState<string | null>(null);
  const [hover, setHover] = useState<{
    key: string;
    x: number;
    y: number;
  } | null>(null);
  const [replay, setReplay] = useState<number | null>(null);
  const raf = useRef(0);
  const base = `/api/console/arenas/${encodeURIComponent(arena.id)}/run-tree`;

  const load = useCallback(
    (signal?: AbortSignal) =>
      getJson<Timeline>(base, signal)
        .then((data) => {
          setTree(data);
          setError("");
        })
        .catch((reason: unknown) => {
          if (!signal?.aborted)
            setError(
              reason instanceof Error ? reason.message : "Timeline unavailable",
            );
        }),
    [base],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  // Poll while live, and keep trying until the first read succeeds.
  const polling = tree ? tree.live : true;
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [polling, load]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (finding) setFinding(null);
      else setPicked(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [finding]);
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  const frame = useMemo(
    () => (tree ? frameOf(tree, preview) : null),
    [tree, preview],
  );
  const clusters = useMemo(
    () => (tree && frame ? clustersOf(tree, frame) : []),
    [tree, frame],
  );
  // Replay: the serpent grows again from its tail; marks sprout as the head
  // passes them.
  const grow = useCallback((target: number) => {
    cancelAnimationFrame(raf.current);
    const t0 = performance.now();
    const ms = 1200 + 2600 * Math.min(1, target);
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      setReplay(target * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf.current = requestAnimationFrame(tick);
      else setReplay(null);
    };
    raf.current = requestAnimationFrame(tick);
  }, []);
  const grown = useRef(false);
  useEffect(() => {
    if (!frame || grown.current) return;
    grown.current = true;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches)
      grow(frame.head);
  }, [frame, grow]);
  const onHover = useCallback((key: string | null, event?: MouseEvent) => {
    setHover(key && event ? { key, x: event.clientX, y: event.clientY } : null);
  }, []);
  const onPick = useCallback((cluster: Cluster) => {
    setHover(null);
    const only = cluster.list.length === 1 ? cluster.list[0] : null;
    if (only?.kind === "finding" && only.item.id) {
      setPicked(null);
      setFinding(only.item.id);
      return;
    }
    setFinding(null);
    setPicked((current) => (current === cluster.key ? null : cluster.key));
  }, []);

  if (!tree || !frame)
    return (
      <div className="tl-page">
        <p className="muted tl-wait">{error || "Reading the run…"}</p>
      </div>
    );
  const t0 = parseStart(tree.started_at);
  const clock = (t: number) =>
    new Date(t0 + t * 1000).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
    });
  const p = replay ?? frame.head;
  const bitten = p >= 0.999;
  const cluster = clusters.find((c) => c.key === picked) || null;
  const hovered = hover ? clusters.find((c) => c.key === hover.key) : null;
  const seen = (f: number) => f <= p + 1e-6;
  const nF = tree.findings.filter((f) => seen(frame.frac(f.t))).length;
  const nE = tree.failures.filter((f) => seen(frame.frac(f.t))).length;
  const nV = tree.verdicts.filter((v) => seen(frame.frac(v.t))).length;
  const used = p * frame.total;
  const ended = !tree.live && !bitten && replay == null;
  return (
    <div className="tl-page">
      <header className="tl-top">
        <div>
          <span className="eyebrow">Timeline</span>
          <h2>The run against its time budget</h2>
        </div>
        <div className="tl-ctl">
          <button
            type="button"
            className="tl-btn"
            onClick={() => grow(frame.head)}
          >
            Replay
          </button>
          <button
            type="button"
            className="tl-btn"
            aria-pressed={preview}
            disabled={frame.open}
            title="Draw the serpent as if the budget ended now"
            onClick={() => {
              setPreview(!preview);
              setPicked(null);
            }}
          >
            Preview the end
          </button>
        </div>
      </header>
      <div className={`tl-main${finding ? " reading" : ""}`}>
        <section className="tl-stage">
          {tree.totals.steps === 0 && !tree.findings.length ? (
            <p className="muted tl-wait">
              No steps yet. The serpent is born here when the agent starts.
            </p>
          ) : (
            <svg
              className="tl-svg"
              viewBox="0 0 760 760"
              role="img"
              aria-label={`The run's time budget as a serpent: ${(frame.head * 100).toFixed(0)}% spent, ${tree.findings.length} findings, ${tree.totals.errors} failed calls`}
            >
              <Serpent
                tree={tree}
                frame={frame}
                p={p}
                clusters={clusters}
                selected={picked}
                hovered={hover?.key ?? null}
                onHover={onHover}
                onPick={onPick}
              />
              <g className="tl-centre">
                <text className="tag" x={C} y={C - 74} textAnchor="middle">
                  {preview
                    ? "IF THE BUDGET ENDED NOW"
                    : frame.open
                      ? "NO DEADLINE · THE RUN SO FAR"
                      : "TIME BUDGET"}
                </text>
                <text className="big" x={C} y={C - 20} textAnchor="middle">
                  {duration(used)}
                </text>
                <text className="of" x={C} y={C + 6} textAnchor="middle">
                  {frame.open
                    ? "since the arena started"
                    : `of ${duration(frame.total)}`}
                </text>
                <text className="pct" x={C} y={C + 34} textAnchor="middle">
                  {bitten && !frame.open
                    ? "spent · the serpent bites its tail"
                    : ended
                      ? `ended at ${(p * 100).toFixed(1)}%`
                      : frame.open
                        ? tree.live
                          ? "live"
                          : "ended"
                        : `${(p * 100).toFixed(1)}% · ${duration(frame.total - used)} left`}
                </text>
                <text className="line" x={C} y={C + 68} textAnchor="middle">
                  <tspan className="g">◆</tspan> {nF}{" "}
                  {nF === 1 ? "finding" : "findings"} ·{" "}
                  <tspan className="e">×</tspan> {nE} failed ·{" "}
                  <tspan className="v">●</tspan> {nV}{" "}
                  {nV === 1 ? "verdict" : "verdicts"}
                </text>
              </g>
            </svg>
          )}
          <ul className="tl-legend" aria-label="Legend">
            <li>
              <i className="lg-gem" /> Finding, coloured by severity
            </li>
            <li>
              <i className="lg-fail" /> Failed calls
            </li>
            <li>
              <i className="lg-sup" /> Supported
            </li>
            <li>
              <i className="lg-ref" /> Refuted
            </li>
            <li>
              <i className="lg-donut" /> Several verdicts
            </li>
            <li>
              <i className="lg-cycle" /> Agent cycle
            </li>
            <li>A number counts what sits close together</li>
          </ul>
        </section>
        <SidePanel
          arenaId={arena.id}
          tree={tree}
          frame={frame}
          clock={clock}
          cluster={cluster}
          finding={finding}
          onFinding={setFinding}
          onBack={() => (finding ? setFinding(null) : setPicked(null))}
        />
      </div>
      {hovered && hover && (
        <HoverCard cluster={hovered} x={hover.x} y={hover.y} clock={clock} />
      )}
    </div>
  );
}
