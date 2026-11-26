// UX-17: the arena overview as a dashboard. It answers "how is it going" (or
// "how did it go" once destroyed) from the spans the platform recorded:
// activity per interval, budget burn, where the actions went, how they ended,
// findings, the stations as built and the newest steps. Nothing is estimated
// except the budget projection, which says so.
import type { ArenaData } from "../types";
import { Empty, Panel, Status, useWorkspaceData, formatObserved } from "../ui";
import { useBoard } from "../shared/board";
import {
  ActivityChart,
  Bars,
  BurnChart,
  Share,
  clockOf,
  n,
  type ActivityBucket,
} from "../design/charts";
import { Icon } from "../shell/icons";
import { Stations } from "./stations";
import "./dashboard.css";

export type ArenaActivity = {
  start: string;
  end: string;
  bucket_seconds: number;
  buckets: ActivityBucket[];
  totals: {
    by_family: Record<"http" | "exec" | "model" | "other", number>;
    failed_by_family: Record<"http" | "exec" | "model" | "other", number>;
    actions: number;
    failed: number;
    refused: number;
  };
  by_actor: {
    actor: string;
    arena_id: string | null;
    actions: number;
    model_calls: number;
    failed: number;
    refused: number;
  }[];
  durations: {
    median_ms: number | null;
    slowest: { name: string; ms: number } | null;
  };
  recent: {
    name: string;
    kind: string;
    actor: string;
    status: string;
    started_at: string;
    duration_ms: number | null;
    preview: string | null;
  }[];
};

const KIND_ICON = {
  http: "swap",
  exec: "term",
  model: "pulse",
  other: "bolt",
} as const;

function familyOf(kind: string, name: string) {
  if (kind === "model") return "model";
  if (name.startsWith("http/")) return "http";
  if (name === "exec" || name.startsWith("exec/")) return "exec";
  return "other";
}

/** A span's input preview as one readable line (values only, in order). */
export function previewLine(preview: string | null) {
  if (!preview) return null;
  try {
    const value: unknown = JSON.parse(preview);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const parts = Object.values(value as Record<string, unknown>)
        .filter((item) => ["string", "number", "boolean"].includes(typeof item))
        .map(String);
      if (parts.length) return parts.join(" ");
    }
  } catch {
    /* not JSON: show it as recorded */
  }
  return preview;
}

export function duration(ms: number | null | undefined) {
  if (ms == null) return "Not recorded";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s % 60)} s`;
}

function span(start: string, end: string) {
  const ms =
    Date.parse(end.replace(" ", "T") + "Z") -
    Date.parse(start.replace(" ", "T") + "Z");
  const minutes = Math.max(0, Math.round(ms / 60000));
  return minutes >= 60
    ? `${Math.floor(minutes / 60)} h ${minutes % 60} min`
    : `${minutes} min`;
}

type Signal = {
  kind: string | null;
  node: string | null;
  severity: string | null;
  summary: string | null;
  ts: string | null;
};

export function ArenaDashboard({ arena }: { arena: ArenaData }) {
  const base = `/console/arena/${encodeURIComponent(arena.id)}`;
  const evidence = useWorkspaceData<{ signals: Signal[] }>(
    `/api/console/arenas/${encodeURIComponent(arena.id)}/evidence`,
  );
  const signals = [...(evidence.value?.signals || [])].sort((a, b) =>
    (b.ts || "").localeCompare(a.ts || ""),
  );
  const activity = useWorkspaceData<ArenaActivity>(
    `/api/console/arenas/${encodeURIComponent(arena.id)}/activity`,
  );
  const { board } = useBoard();
  const live = board?.arenas.find((item) => item.id === arena.id);
  const data = activity.value;
  const cap = arena.budget.cap;
  const used =
    cap != null && arena.budget.remaining != null
      ? cap - arena.budget.remaining
      : null;
  const over = arena.state === "destroyed";
  const stopped = (arena.budget.gate || "").toLowerCase() === "stopped";
  const waiting = arena.findings.filter(
    (finding) => !["confirmed", "refuted"].includes(finding.verdict),
  ).length;
  const head = over ? "How it went" : "How it is going";

  let summary = null;
  if (data && data.totals.actions + data.totals.refused > 0) {
    const t = data.totals;
    const rate = t.actions ? (t.failed / t.actions) * 100 : 0;
    const verdict = over
      ? "Finished."
      : stopped
        ? "Research is stopped."
        : rate > 5
          ? "Running, with a high failure rate."
          : "Running steadily.";
    summary = (
      <p className="dash-say">
        <b>{verdict}</b> {n(t.actions)} actions in {span(data.start, data.end)},{" "}
        {n(t.failed)} failed ({rate.toFixed(1)}%)
        {t.refused ? `, ${n(t.refused)} refused` : ""}.{" "}
        {arena.findings.length
          ? `${arena.findings.length} finding${arena.findings.length > 1 ? "s" : ""}${waiting ? `, ${waiting} waiting for a verdict` : ", all decided"}.`
          : "No findings yet."}
      </p>
    );
  }
  const empty = data && data.totals.actions + data.totals.refused === 0;
  return (
    <div className="dash">
      {summary}
      {activity.error && !data ? (
        <Panel eyebrow={head} title="Activity unavailable">
          <Empty
            title="Activity could not be loaded"
            detail={activity.error}
            action={
              <button
                type="button"
                className="button button-outline"
                onClick={activity.refresh}
              >
                Try again
              </button>
            }
          />
        </Panel>
      ) : !data ? (
        <div className="dash-skeleton" aria-hidden="true" />
      ) : empty ? (
        <Panel eyebrow={head} title="No activity yet">
          <Empty
            title="Charts appear with the first action"
            detail={
              arena.state === "deploying" || arena.state === "pending"
                ? "The arena is still launching. Activity, budget and outcomes are drawn as soon as an agent acts."
                : "No agent or operator has acted in this arena yet."
            }
          />
        </Panel>
      ) : (
        <>
          <div className="dash-row dash-main">
            <Panel
              eyebrow={head}
              title={over ? "Activity during the run" : "Activity since launch"}
              aside={
                <a className="inline-action" href={`${base}?tab=live`}>
                  Timeline
                </a>
              }
            >
              <div className="dash-body">
                <ActivityChart
                  buckets={data.buckets}
                  bucketSeconds={data.bucket_seconds}
                  caption={`Actions per interval in ${arena.name}, by kind`}
                />
              </div>
            </Panel>
            <Panel
              eyebrow="Budget"
              title={
                cap != null && used != null
                  ? `${n(used)} of ${n(cap)} actions`
                  : "Budget not reported"
              }
              aside={
                cap != null && used != null ? (
                  used >= cap ? (
                    <Status value="exhausted" />
                  ) : used / cap >= 0.75 ? (
                    <Status value="running low" />
                  ) : undefined
                ) : undefined
              }
            >
              <div className="dash-body">
                {cap != null && used != null ? (
                  <BurnChart
                    buckets={data.buckets}
                    bucketSeconds={data.bucket_seconds}
                    start={data.start}
                    end={data.end}
                    expires={arena.expires_at}
                    used={used}
                    cap={cap}
                    live={arena.state === "active" && !stopped}
                  />
                ) : (
                  <Empty
                    title="No action budget reported"
                    detail="This arena has no orchestrator-owned budget, so there is nothing to burn down."
                  />
                )}
              </div>
            </Panel>
          </div>
          <div className="dash-row dash-three">
            <Panel eyebrow="By kind" title="Where the actions went">
              <div className="dash-body">
                <Bars
                  rows={(["http", "exec", "model", "other"] as const).map(
                    (key) => ({
                      key,
                      family: key,
                      label: {
                        http: "HTTP",
                        exec: "Shell",
                        model: "Model",
                        other: "Other",
                      }[key],
                      value: data.totals.by_family[key],
                      failed: data.totals.failed_by_family[key],
                    }),
                  )}
                />
              </div>
              <div className="panel-foot">
                <span>Failures are the red end of each bar</span>
              </div>
            </Panel>
            <Panel eyebrow="Outcomes" title="How the actions ended">
              <div className="dash-body">
                <Share
                  parts={[
                    {
                      key: "ok",
                      label: "Succeeded",
                      value: data.totals.actions - data.totals.failed,
                      tone: "ok",
                    },
                    {
                      key: "failed",
                      label: "Failed",
                      value: data.totals.failed,
                      tone: "bad",
                    },
                    {
                      key: "refused",
                      label: "Refused by policy or budget",
                      value: data.totals.refused,
                      tone: "warn",
                    },
                  ]}
                />
                <dl className="dash-kv">
                  <div>
                    <dt>Median tool time</dt>
                    <dd>{duration(data.durations.median_ms)}</dd>
                  </div>
                  <div>
                    <dt>Slowest tool call</dt>
                    <dd>
                      {data.durations.slowest
                        ? `${data.durations.slowest.name} · ${duration(data.durations.slowest.ms)}`
                        : "Not recorded"}
                    </dd>
                  </div>
                </dl>
              </div>
            </Panel>
            <Panel
              eyebrow="Findings"
              title={
                arena.findings.length
                  ? `${arena.findings.length} submitted${waiting ? ` · ${waiting} open` : ""}`
                  : "None submitted"
              }
            >
              {arena.findings.length ? (
                <ul className="dash-findings">
                  {arena.findings.slice(0, 4).map((finding, index) => (
                    <li key={finding.id || index}>
                      <a href={`${base}?tab=findings`}>
                        {finding.title || "Untitled finding"}
                      </a>
                      <Status value={finding.verdict} />
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="dash-body">
                  <Empty
                    title="Nothing found yet"
                    detail="Findings an agent or you submit appear here with their evidence."
                  />
                </div>
              )}
              <div className="panel-foot">
                <span>The validator's verdict and yours are kept apart</span>
                <a className="inline-action" href={`${base}?tab=findings`}>
                  Review
                </a>
              </div>
            </Panel>
          </div>
        </>
      )}
      <div className="dash-row dash-main">
        <Panel
          eyebrow="Environment"
          title={`${arena.nodes.length || "No"} station${arena.nodes.length === 1 ? "" : "s"} built`}
          aside={
            <a className="inline-action" href={`${base}?tab=infrastructure`}>
              Infrastructure
            </a>
          }
        >
          <div className="dash-body">
            <Stations arena={arena} />
          </div>
        </Panel>
        <Panel
          eyebrow="Agents here"
          title={
            live?.agents.length
              ? "Connected to this arena"
              : "No agent connected"
          }
        >
          {live?.agents.length ? (
            <ul className="dash-agents">
              {live.agents.map((agent) => (
                <li key={agent.name}>
                  <span className="dash-agent-head">
                    <Icon name="agent" />
                    <b>{agent.name}</b>
                    <small>{agent.stance || "any stance"}</small>
                    {agent.paused && <Status value="paused" />}
                  </span>
                  <span className="dash-now">
                    {live.last_action && live.last_action.actor === agent.name
                      ? `${live.last_action.name} · ${live.last_action.status}`
                      : "No recent action"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="dash-body">
              <Empty
                title="Bring your own agent"
                detail="Create a key scoped to this arena and one stance."
                action={
                  <a
                    className="button button-outline"
                    href={`${base}?tab=access`}
                  >
                    Agent access
                  </a>
                }
              />
            </div>
          )}
          <div className="panel-foot">
            <span>Bound by scoped keys</span>
            <a className="inline-action" href={`${base}?tab=access`}>
              Manage access
            </a>
          </div>
        </Panel>
      </div>
      <Panel
        eyebrow="Latest"
        title="Recent activity"
        aside={
          <a className="inline-action" href={`${base}?tab=live`}>
            Open timeline
          </a>
        }
      >
        {data?.recent.length ? (
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Step</th>
                  <th>Detail</th>
                  <th>Result</th>
                  <th className="r">Took</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((row, index) => {
                  const fam = familyOf(row.kind, row.name);
                  return (
                    <tr key={`${row.started_at}-${index}`}>
                      <td className="mono">{clockOf(row.started_at, true)}</td>
                      <td>{row.actor}</td>
                      <td>
                        <span className={`dash-step fam-text-${fam}`}>
                          <Icon name={KIND_ICON[fam]} size={14} />
                          <b className="mono">{row.name}</b>
                        </span>
                      </td>
                      <td
                        className="mono dash-detail"
                        title={row.preview || ""}
                      >
                        {previewLine(row.preview) || "—"}
                      </td>
                      <td>
                        <Status
                          value={
                            row.status === "ok"
                              ? "ok"
                              : row.status === "budget_refused"
                                ? "refused"
                                : row.status
                          }
                        />
                      </td>
                      <td className="r mono">{duration(row.duration_ms)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="dash-body">
            <Empty
              title={
                arena.state === "deploying"
                  ? "The arena is still launching"
                  : "No steps recorded yet"
              }
              detail="The newest steps of every agent and operator in this arena are listed here."
            />
          </div>
        )}
        <details className="dash-events" open={signals.length > 0}>
          <summary>
            Monitor signals{" "}
            <small>
              {evidence.error
                ? "unavailable"
                : evidence.loading && !evidence.value
                  ? "loading"
                  : signals.length
                    ? `${signals.length} recorded`
                    : "none recorded"}
            </small>
          </summary>
          {signals.length ? (
            <ul>
              {signals.slice(0, 8).map((signal, index) => (
                <li key={`${signal.ts}-${index}`}>
                  <time>
                    {signal.ts ? formatObserved(signal.ts) : "Unknown time"}
                  </time>
                  <b>
                    <Status value={signal.severity || "unrated"} />{" "}
                    {signal.summary || signal.kind || "Signal"}
                  </b>
                  <span>{signal.node || "arena"}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="dash-events-empty">
              {evidence.error
                ? "Monitor signals could not be loaded."
                : "The service has not recorded monitor signals for this arena."}
            </p>
          )}
        </details>
        {arena.events.length > 0 && (
          <details className="dash-events">
            <summary>
              Lifecycle events <small>{arena.events.length} recent</small>
            </summary>
            <ul>
              {arena.events.slice(0, 8).map((event, index) => (
                <li key={`${event.ts}-${index}`}>
                  <time>
                    {event.ts ? formatObserved(event.ts) : "Unknown time"}
                  </time>
                  <b>{event.type.replaceAll("_", " ")}</b>
                  <span>{event.actor}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </Panel>
    </div>
  );
}
