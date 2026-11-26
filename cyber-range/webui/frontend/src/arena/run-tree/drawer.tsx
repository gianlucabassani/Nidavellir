// UX-27: the inspection drawer. It slides over the page from the right when
// you open a branch, a cycle or the trunk: Summary, Steps (loaded on open,
// every step with its input and output) and Errors.
import { useEffect, useMemo, useRef, useState } from "react";
import { getJson } from "../../api";
import { Icon } from "../../shell/icons";
import {
  STATE_TEXT,
  duration,
  type RunTree,
  type TreeError,
  type TreeRoute,
} from "./model";
import type { Pick } from "./canvas";

type Step = {
  id: number;
  t: number;
  name: string;
  kind: string;
  family: string;
  status: string;
  duration_ms: number | null;
  target: string;
  error: string | null;
  input: string;
  output: string;
};
type Tab = "summary" | "steps" | "errors";
const FAMILY: Record<string, string> = {
  http: "HTTP requests",
  exec: "Shell commands",
  model: "Model calls",
  other: "Other tools",
};

function pretty(text: string) {
  if (!text) return "";
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function Marked({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>;
  const lower = text.toLowerCase();
  const parts: React.ReactNode[] = [];
  let from = 0;
  let at = lower.indexOf(q);
  while (at >= 0 && parts.length < 400) {
    parts.push(
      text.slice(from, at),
      <mark key={at}>{text.slice(at, at + q.length)}</mark>,
    );
    from = at + q.length;
    at = lower.indexOf(q, from);
  }
  parts.push(text.slice(from));
  return <>{parts}</>;
}

export function RunDrawer({
  arenaId,
  tree,
  pick,
  query,
  clock,
  onPick,
  onClose,
}: {
  arenaId: string;
  tree: RunTree;
  pick: Pick;
  query: string;
  clock: (t: number) => string;
  onPick: (pick: Pick) => void;
  onClose: () => void;
}) {
  const route: TreeRoute | null =
    pick.kind === "route"
      ? tree.routes.find((r) => r.key === pick.key) || null
      : null;
  const cycle = pick.kind === "cycle" ? tree.cycles[pick.i] : null;
  const focus = pick.kind !== "cycle" ? pick.focus : undefined;
  const [tab, setTab] = useState<Tab>(focus != null ? "steps" : "summary");
  const [wide, setWide] = useState(false);
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Set<number>>(
    new Set(focus != null ? [focus] : []),
  );
  const body = useRef<HTMLDivElement>(null);
  const q = query.trim().toLowerCase();
  const routeParam = route ? route.key : "trunk";
  useEffect(() => {
    if (tab === "summary" && !route) return;
    if (steps) return;
    const controller = new AbortController();
    getJson<{ steps: Step[] }>(
      `/api/console/arenas/${encodeURIComponent(arenaId)}/run-tree/steps?route=${encodeURIComponent(routeParam)}`,
      controller.signal,
    )
      .then((data) => setSteps(data.steps))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "Steps unavailable",
          );
      });
    return () => controller.abort();
  }, [arenaId, routeParam, tab, steps, route]);
  useEffect(() => {
    if (tab !== "steps" || focus == null || !steps) return;
    const id = requestAnimationFrame(() =>
      body.current
        ?.querySelector(`[data-step="${focus}"]`)
        ?.scrollIntoView({ block: "center" }),
    );
    return () => cancelAnimationFrame(id);
  }, [tab, focus, steps]);
  const shown = useMemo(() => {
    if (!steps) return [];
    if (!cycle) return steps;
    return steps.filter((s) => s.t >= cycle.a - 1 && s.t <= cycle.b + 1);
  }, [steps, cycle]);
  const errors: TreeError[] = route
    ? route.episodes.flatMap((ep) => ep.errors)
    : tree.trunk.errors.filter(
        (e) => !cycle || (e.t >= cycle.a && e.t <= cycle.b),
      );
  const title = route
    ? route.name
    : cycle
      ? `Cycle ${cycle.i + 1}`
      : "The agent (trunk)";
  const span = route
    ? `${clock(route.a)} to ${route.state === "open" && tree.live ? "now" : clock(route.b)}, ${duration(route.b - route.a)}`
    : cycle
      ? `${clock(cycle.a)} to ${clock(cycle.b)}, ${duration(cycle.b - cycle.a)}`
      : `${tree.trunk.steps} steps on no route`;
  const findings = route
    ? tree.findings.filter((f) => f.route === route.key)
    : [];
  const active = cycle
    ? tree.routes.filter((r) => r.a <= cycle.b && r.b >= cycle.a)
    : [];
  const tools = route
    ? Object.entries(route.tools).sort((a, b) => b[1] - a[1])
    : [];
  const toolMax = Math.max(1, ...tools.map(([, n]) => n));
  const toggle = (id: number) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <aside
      className={`rt-drawer ${wide ? "wide" : ""}`}
      role="dialog"
      aria-label={`${title} details`}
    >
      <header className="rt-drawer-head">
        <div className="rt-drawer-actions">
          <button
            type="button"
            className="button button-outline"
            onClick={() => setWide(!wide)}
          >
            {wide ? "Narrower" : "Wider"}
          </button>
          <button
            type="button"
            className="button button-outline"
            aria-label="Close details"
            onClick={onClose}
          >
            <Icon name="x" size={14} />
          </button>
        </div>
        <h2>
          <i
            className={`rt-dot ${route ? route.state : "trunk"}`}
            aria-hidden="true"
          />
          {title}
        </h2>
        <p className="muted">
          {span}
          {route && route.actor ? ` · ${route.actor}` : ""}
        </p>
        {route && (
          <p className={`rt-pill ${route.state}`}>
            {STATE_TEXT[route.state]}
            {route.outcome ? ` (${route.outcome})` : ""}
          </p>
        )}
        <div className="rt-tabs" role="tablist">
          {(
            [
              ["summary", "Summary"],
              [
                "steps",
                `Steps${route ? ` (${route.steps})` : cycle ? ` (${cycle.steps})` : ""}`,
              ],
              ...(errors.length
                ? [["errors", `Errors (${errors.length})`]]
                : []),
            ] as [Tab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
          <span className="fl-sp" />
          {tab === "steps" && shown.length > 0 && (
            <>
              <button
                type="button"
                className="inline-action"
                onClick={() => setOpen(new Set(shown.map((s) => s.id)))}
              >
                Expand all
              </button>
              <button
                type="button"
                className="inline-action"
                onClick={() => setOpen(new Set())}
              >
                Collapse all
              </button>
            </>
          )}
        </div>
      </header>
      <div className="rt-drawer-body" ref={body}>
        {tab === "summary" && (
          <>
            <dl className="rt-numbers">
              {(route
                ? [
                    [route.steps, "steps"],
                    [
                      route.episodes.length || 1,
                      route.episodes.length === 1 ? "episode" : "episodes",
                    ],
                    [route.errors, "failed calls"],
                    [
                      findings.length,
                      findings.length === 1 ? "finding" : "findings",
                    ],
                  ]
                : cycle
                  ? [
                      [cycle.steps, "steps"],
                      [active.length, "routes worked"],
                      [cycle.errors, "failed calls"],
                      [duration(cycle.b - cycle.a), "long"],
                    ]
                  : [
                      [tree.trunk.steps, "steps on no route"],
                      [tree.trunk.errors.length, "failed calls"],
                      [tree.cycles.length, "cycles"],
                      [tree.totals.steps, "steps in the run"],
                    ]
              ).map(([value, label]) => (
                <div key={label as string}>
                  <dd>{value}</dd>
                  <dt>{label}</dt>
                </div>
              ))}
            </dl>
            {route?.claim && (
              <>
                <h3 className="label">
                  {route.kind === "hypothesis" ? "Hypothesis" : "Route"}
                </h3>
                <blockquote className={`rt-claim ${route.state}`}>
                  {route.claim}
                </blockquote>
              </>
            )}
            {findings.length > 0 && (
              <>
                <h3 className="label">Findings</h3>
                <ul className="rt-links">
                  {findings.map((f) => (
                    <li key={f.id}>
                      <a
                        href={`/console/arena/${encodeURIComponent(arenaId)}?tab=findings&finding=${encodeURIComponent(f.id)}`}
                      >
                        {f.title}
                      </a>
                      <small>
                        {f.severity ? `${f.severity} · ` : ""}
                        {clock(f.t)}
                      </small>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {tools.length > 0 && (
              <>
                <h3 className="label">What it used</h3>
                {tools.map(([family, count]) => (
                  <div key={family} className="rt-mix">
                    <span>{FAMILY[family] || family}</span>
                    <i
                      className={`fam-${family}`}
                      style={{ width: `${(count / toolMax) * 100}%` }}
                    />
                    <b>{count}</b>
                  </div>
                ))}
              </>
            )}
            {route && route.episodes.length > 1 && (
              <>
                <h3 className="label">Episodes</h3>
                <ul className="rt-links">
                  {route.episodes.map((ep, i) => (
                    <li key={i}>
                      {clock(ep.a)} to {clock(ep.b)}{" "}
                      <small>{ep.steps} steps</small>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {!route &&
              !cycle &&
              tree.routes.some((r) => !r.episodes.length) && (
                <>
                  <h3 className="label">Background routes on the trunk</h3>
                  <ul className="rt-links">
                    {tree.routes
                      .filter((r) => !r.episodes.length)
                      .map((r) => (
                        <li key={r.key}>
                          <button
                            type="button"
                            className="inline-action"
                            onClick={() =>
                              onPick({ kind: "route", key: r.key })
                            }
                          >
                            {r.name}
                          </button>
                          <small>
                            {r.steps} steps ·{" "}
                            {r.background
                              ? "interleaved with other routes"
                              : "too few steps for a branch"}
                          </small>
                        </li>
                      ))}
                  </ul>
                </>
              )}
            {active.length > 0 && (
              <>
                <h3 className="label">Routes worked in this cycle</h3>
                <ul className="rt-links">
                  {active.map((r) => (
                    <li key={r.key}>
                      <button
                        type="button"
                        className="inline-action"
                        onClick={() => onPick({ kind: "route", key: r.key })}
                      >
                        {r.name}
                      </button>
                      <small>
                        {STATE_TEXT[r.state]} · {r.steps} steps
                      </small>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {errors.length > 0 && (
              <>
                <h3 className="label">Failed calls</h3>
                <ErrorList
                  errors={errors.slice(0, 8)}
                  clock={clock}
                  onPick={(id) =>
                    onPick(
                      route
                        ? { kind: "route", key: route.key, focus: id }
                        : { kind: "trunk", focus: id },
                    )
                  }
                />
              </>
            )}
          </>
        )}
        {tab === "errors" && (
          <ErrorList
            errors={errors}
            clock={clock}
            onPick={(id) =>
              onPick(
                route
                  ? { kind: "route", key: route.key, focus: id }
                  : { kind: "trunk", focus: id },
              )
            }
          />
        )}
        {tab === "steps" &&
          (error ? (
            <p className="fr-error">{error}</p>
          ) : !steps ? (
            <p className="muted" role="status">
              Loading the steps…
            </p>
          ) : !shown.length ? (
            <p className="muted">No steps recorded here.</p>
          ) : (
            <ol className="rt-steps">
              {shown.map((step) => {
                const expanded = open.has(step.id);
                const failed = step.status !== "ok";
                const match =
                  q && `${step.target} ${step.input}`.toLowerCase().includes(q);
                return (
                  <li
                    key={step.id}
                    data-step={step.id}
                    className={`${failed ? "err" : ""} ${match ? "match" : ""} ${focus === step.id ? "focus" : ""}`}
                  >
                    <button
                      type="button"
                      aria-expanded={expanded}
                      onClick={() => toggle(step.id)}
                    >
                      <span className="t">{clock(step.t)}</span>
                      <i
                        className={`fam fam-${failed ? "bad" : step.family}`}
                        aria-hidden="true"
                      />
                      <b>{step.name}</b>
                      <span className="target">
                        <Marked text={step.target} q={q} />
                      </span>
                      <span className="st">
                        {failed
                          ? step.status.replace("_", " ")
                          : step.duration_ms != null
                            ? `${step.duration_ms} ms`
                            : ""}
                      </span>
                    </button>
                    {expanded && (
                      <div className="rt-step-body">
                        {step.error && (
                          <p className="err">Error: {step.error}</p>
                        )}
                        {step.input && (
                          <section>
                            <h4>Input</h4>
                            <pre>
                              <Marked text={pretty(step.input)} q={q} />
                            </pre>
                          </section>
                        )}
                        {step.output && (
                          <section>
                            <h4>Output</h4>
                            <pre>
                              <Marked text={pretty(step.output)} q={q} />
                            </pre>
                          </section>
                        )}
                        {!step.input && !step.output && (
                          <p className="muted">
                            No input or output was recorded.
                          </p>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
          ))}
      </div>
    </aside>
  );
}

function ErrorList({
  errors,
  clock,
  onPick,
}: {
  errors: TreeError[];
  clock: (t: number) => string;
  onPick: (id: number) => void;
}) {
  return (
    <ul className="rt-errors">
      {errors.map((e) => (
        <li key={e.id}>
          <button type="button" onClick={() => onPick(e.id)}>
            <b>{e.tool}</b>
            <small>
              {clock(e.t)} · {e.status.replace("_", " ")}
            </small>
            <span>{e.target}</span>
            {e.error && <code>{e.error}</code>}
          </button>
        </li>
      ))}
    </ul>
  );
}
