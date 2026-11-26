// UX-26: the run's world tree on its own page. The tree fills the page and
// grows from its roots when it opens; the routes the agent pursued are a
// panel beside it: filter them, hover one to light its branch, click one to
// focus it. The selected step opens in the inspector under the routes.
import { useMemo, useState, type KeyboardEvent } from "react";
import type { ArenaData, Span } from "../types";
import { Inspector, type SpanFeed } from "./live-view";
import { useArenaSpans } from "./use-spans";
import { WorldTree, routesOf, stepLabel } from "./world-tree";
import "./timeline-page.css";

type Filter = "all" | "open" | "finding" | "refuted";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "finding", label: "Findings" },
  { key: "refuted", label: "Refuted" },
];
const OUTCOME: Record<string, string> = {
  finding: "Finding",
  refuted: "Refuted",
  done: "Tested",
  open: "Open",
};

function clock(ms: number) {
  return new Date(ms).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
function span(ms: number) {
  const minutes = Math.round(ms / 60000);
  return minutes < 1
    ? "under a minute"
    : minutes < 90
      ? `${minutes} min`
      : `${(minutes / 60).toFixed(1)} h`;
}

export function TimelinePage({
  arena,
  feed,
}: {
  arena: ArenaData;
  feed: SpanFeed;
}) {
  const { spans, loadError, loaded } = useArenaSpans(arena.id, feed);
  const [selected, setSelected] = useState<number | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [hot, setHot] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const { routes, drawn } = useMemo(() => routesOf(spans), [spans]);
  const live = arena.state === "active";
  const counts = {
    all: routes.length,
    open: routes.filter((route) => route.outcome === "open").length,
    finding: routes.filter((route) => route.outcome === "finding").length,
    refuted: routes.filter((route) => route.outcome === "refuted").length,
  };
  const shown = [...routes]
    .filter((route) => filter === "all" || route.outcome === filter)
    .sort((a, b) => b.end - a.end);
  const current = spans.find((item) => item.id === selected) || null;
  const onKey = (event: KeyboardEvent) => {
    if (!["ArrowUp", "ArrowDown"].includes(event.key) || !drawn.length) return;
    event.preventDefault();
    const index = drawn.findIndex((item) => item.id === selected);
    // Up is later in time (the crown), down is earlier (the roots).
    const next =
      index < 0
        ? drawn.length - 1
        : Math.max(
            0,
            Math.min(
              drawn.length - 1,
              index + (event.key === "ArrowUp" ? 1 : -1),
            ),
          );
    setSelected(drawn[next].id);
  };
  const first = drawn.length
    ? Date.parse(drawn[0].started_at.replace(" ", "T") + "Z")
    : 0;
  const findings = routes.reduce((n, route) => n + route.findings.length, 0);
  return (
    <div className="tl">
      <header className="tl-head">
        <div>
          <span className="eyebrow">Timeline</span>
          <h2>How the run grew</h2>
          <p className="muted">
            The trunk is the agent itself; each branch is a route it pursued.
            Fruit is a finding, a withered tip a refuted hypothesis, a bud a
            route still open.
          </p>
        </div>
        <dl className="tl-stats">
          <div>
            <dt>Steps</dt>
            <dd>{drawn.length}</dd>
          </div>
          <div>
            <dt>Routes</dt>
            <dd>{routes.length}</dd>
          </div>
          <div>
            <dt>Findings</dt>
            <dd>{findings}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{first ? clock(first) : "·"}</dd>
          </div>
        </dl>
      </header>
      <div className="tl-body">
        <div className="tl-canvas">
          {spans.length || loaded ? (
            <WorldTree
              spans={spans}
              total={spans.length}
              selectedId={selected}
              onSelect={(item: Span) => setSelected(item.id)}
              onKey={onKey}
              live={live}
              focus={focus}
              onFocus={setFocus}
              hot={hot}
              intro
            />
          ) : (
            <p className="muted tl-wait">{loadError || "Loading the run…"}</p>
          )}
        </div>
        <aside className="tl-side" aria-label="Routes">
          <div className="tl-side-head">
            <h3 className="label">Routes</h3>
            <div className="seg" role="group" aria-label="Route filter">
              {FILTERS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={filter === item.key}
                  onClick={() => setFilter(item.key)}
                >
                  {item.label} {counts[item.key]}
                </button>
              ))}
            </div>
          </div>
          {focus && (
            <button
              type="button"
              className="inline-action tl-all"
              onClick={() => setFocus(null)}
            >
              Show every route
            </button>
          )}
          <ul className="tl-routes">
            {shown.map((route) => {
              const fruit = route.findings[route.findings.length - 1];
              return (
                <li key={route.key}>
                  <button
                    type="button"
                    className={`tl-route ${route.outcome}`}
                    aria-pressed={focus === route.key}
                    onClick={() =>
                      setFocus(focus === route.key ? null : route.key)
                    }
                    onPointerEnter={() => setHot(route.key)}
                    onPointerLeave={() => setHot(null)}
                    onFocus={() => setHot(route.key)}
                    onBlur={() => setHot(null)}
                  >
                    <span className="tl-route-top">
                      <i aria-hidden="true" />
                      <b>{route.name}</b>
                      <span className={`tl-outcome ${route.outcome}`}>
                        {OUTCOME[route.outcome]}
                      </span>
                    </span>
                    {fruit ? (
                      <span className="tl-claim find">{stepLabel(fruit)}</span>
                    ) : route.claim ? (
                      <span className="tl-claim">{route.claim}</span>
                    ) : null}
                    <span className="tl-meta">
                      {route.steps.length} steps ·{" "}
                      {span(route.end - route.start)} · last {clock(route.end)}
                    </span>
                  </button>
                </li>
              );
            })}
            {!shown.length && (
              <li className="muted tl-none">
                {routes.length
                  ? "No route matches this filter."
                  : "No routes yet: steps that belong to no hypothesis or path stay on the trunk."}
              </li>
            )}
          </ul>
          <div className="tl-inspect">
            <Inspector arena={arena} span={current} signals={[]} />
          </div>
        </aside>
      </div>
    </div>
  );
}
