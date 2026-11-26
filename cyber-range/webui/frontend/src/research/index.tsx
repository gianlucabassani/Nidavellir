import {
  useBoard,
  isIdle,
  ago,
  readDismissed,
  onDismissedChange,
} from "../shared/board";
import { useEffect, useState } from "react";
import type { ResearchData } from "../types";
import { paths } from "../types";
import {
  useWorkspaceData,
  Status,
  Panel,
  Empty,
  PageHead,
  Loading,
  ErrorState,
} from "../ui";
import { ActivityChart, Bars, n, type ActivityBucket } from "../design/charts";
import { Icon } from "../shell/icons";
import "./overview.css";

type RecentActivity = {
  bucket_seconds: number;
  buckets: ActivityBucket[];
  totals: {
    actions: number;
    failed: number;
    refused: number;
    by_family: Record<"http" | "exec" | "model" | "other", number>;
  };
  by_actor: {
    actor: string;
    arena_id: string | null;
    actions: number;
    model_calls: number;
    failed: number;
    refused: number;
  }[];
};

const DECIDED = ["confirmed", "refuted"];

// UX-17: the Research overview answers three questions in order: which agents
// are connected and what they are doing, what is waiting for me, and how the
// last hour went. Arenas and host capacity follow.
export function Research() {
  const { value, error, loading, refresh } = useWorkspaceData<ResearchData>(
    paths.research,
  );
  const recent = useWorkspaceData<RecentActivity>(
    "/api/console/activity/recent",
  );
  const { board, live, now } = useBoard();
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  useEffect(() => onDismissedChange(setDismissed), []);
  if (loading && !value) return <Loading />;
  if (error && !value) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const liveArenas = value.sessions.filter(
    (item) =>
      !["destroyed", "failed", "error_destroying"].includes(item.status),
  );
  const deploying = liveArenas.filter(
    (item) => item.status !== "active",
  ).length;
  const stopped = board
    ? board.arenas.filter((arena) => arena.budget.stopped).length
    : 0;
  const waiting = value.review.filter(
    (finding) => !DECIDED.includes(finding.verdict),
  );
  const agentTiles = board
    ? board.arenas.flatMap((arena) =>
        arena.agents.map((agent) => ({ agent, arena })),
      )
    : [];
  const idleCount = board
    ? agentTiles.filter(({ arena }) => isIdle(arena, board, now)).length
    : 0;
  const needYou = agentTiles.filter(({ arena }) => arena.budget.stopped).length;
  const inbox = board
    ? board.inbox.filter((item) => !dismissed.includes(item.key))
    : [];
  const names = new Map(value.sessions.map((item) => [item.id, item.name]));
  const hour = recent.value;
  const actors = hour
    ? hour.by_actor.filter((row) => row.actions + row.model_calls + row.refused)
    : [];
  return (
    <>
      <PageHead
        overline="Research"
        title="Research"
        subtitle="What is running, what each agent is doing right now, and what is waiting for you."
        observed={value.observed_at}
        action={
          <a className="button button-gold" href="/console/research/new">
            <Icon name="plus" /> New research
          </a>
        }
        refresh={refresh}
      />
      <div className="ov-row ov-main">
        <section className="panel ov-agents" aria-labelledby="ov-agents-title">
          <div className="panel-head">
            <div>
              <span className="eyebrow">Agents now</span>
              <h2 id="ov-agents-title">
                {board
                  ? `${agentTiles.length} connected · ${idleCount} idle · ${needYou} need${needYou === 1 ? "s" : ""} you`
                  : "Loading the live board"}
              </h2>
            </div>
            <span className={`ov-live ${live ? "on" : ""}`}>
              <span className="dot" /> {live ? "Live" : "Reconnecting"}
            </span>
          </div>
          {board && agentTiles.length ? (
            <ul className="ov-agent-grid">
              {agentTiles.slice(0, 6).map(({ agent, arena }) => {
                const quiet = isIdle(arena, board, now);
                const state = arena.budget.stopped
                  ? "wait"
                  : agent.paused
                    ? "idle"
                    : quiet
                      ? "idle"
                      : "run";
                const ratio =
                  arena.budget.remaining != null && arena.budget.cap
                    ? 1 - arena.budget.remaining / arena.budget.cap
                    : null;
                return (
                  <li
                    key={`${arena.id}:${agent.name}`}
                    className={`ov-agent ${state}`}
                  >
                    <a
                      href={`/console/arena/${encodeURIComponent(arena.id)}?tab=live`}
                    >
                      <span className="ov-agent-head">
                        <Icon name="agent" />
                        <b>{agent.name}</b>
                        <small>{agent.stance || "any stance"}</small>
                        <span className="ov-agent-state">
                          {arena.budget.stopped
                            ? "Needs you"
                            : agent.paused
                              ? "Paused"
                              : quiet
                                ? "Idle"
                                : "Working"}
                        </span>
                      </span>
                      <span className="ov-now">
                        {arena.last_action
                          ? `${arena.last_action.name} · ${arena.last_action.status}`
                          : "No action yet"}
                      </span>
                      <span className="ov-agent-foot">
                        <span>{arena.name}</span>
                        <span>
                          {arena.last_action
                            ? ago(arena.last_action.at, now)
                            : "—"}
                        </span>
                        {ratio != null && (
                          <span
                            className={`meter ${ratio >= 0.9 ? "bad" : ratio >= 0.75 ? "warn" : ""}`}
                            role="img"
                            aria-label={`${Math.round(ratio * 100)}% of the budget used`}
                          >
                            <i style={{ width: `${ratio * 100}%` }} />
                          </span>
                        )}
                      </span>
                    </a>
                  </li>
                );
              })}
              {Math.min(agentTiles.length, 6) % 2 === 1 && (
                <li className="ov-agent ov-connect">
                  <a href="/console/arenas">
                    <span className="ov-agent-head">
                      <Icon name="plus" />
                      <b>Connect another agent</b>
                    </span>
                    <span className="ov-connect-text">
                      Create a key scoped to one arena and one stance on its
                      Agent access page.
                    </span>
                  </a>
                </li>
              )}
            </ul>
          ) : (
            <div className="ov-body">
              <Empty
                title={board ? "No agent is connected" : "Loading"}
                detail="Create a key scoped to an arena and one stance on the arena's Agent access page; the agent appears here as soon as it acts."
                action={
                  <a className="button button-outline" href="/console/arenas">
                    Choose an arena
                  </a>
                }
              />
            </div>
          )}
          <div className="panel-foot">
            <span>
              Pushed live · idle after {board?.idle_minutes ?? 5} min without an
              action
            </span>
            <a className="inline-action" href="/console/board">
              Agents board
            </a>
          </div>
        </section>
        <Panel
          eyebrow="Needs attention"
          title={
            inbox.length ? `${inbox.length} waiting for you` : "Nothing waiting"
          }
          className="ov-attention"
        >
          {inbox.length ? (
            <ul className="ov-list">
              {inbox.slice(0, 4).map((item) => (
                <li key={item.key} className={`kind-${item.kind}`}>
                  <a
                    href={
                      item.arena_id
                        ? `/console/arena/${encodeURIComponent(item.arena_id)}?tab=live`
                        : item.evaluation_id
                          ? `/console/evaluations/${encodeURIComponent(item.evaluation_id)}`
                          : "/console/board"
                    }
                  >
                    <b>{item.text}</b>
                    <small>
                      {item.arena_name || item.arena_id || "Platform"} ·{" "}
                      {ago(item.at, now)}
                    </small>
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <div className="ov-body">
              <Empty
                title="Queue clear"
                detail="Failed arenas, verdicts, budget exhaustion, stops and finished trials appear here."
              />
            </div>
          )}
          <div className="panel-foot">
            <span>Newest first</span>
            <a className="inline-action" href="/console/board">
              {inbox.length > 4 ? `Show all ${inbox.length}` : "Agents board"}
            </a>
          </div>
        </Panel>
      </div>
      <div className="ov-row ov-kpis">
        <Kpi
          label="Live arenas"
          value={n(liveArenas.length)}
          hint={`${deploying} launching · ${stopped} stopped`}
        />
        <Kpi
          label="Actions, last hour"
          value={hour ? n(hour.totals.actions) : "—"}
          hint={
            hour
              ? `${n(hour.totals.failed)} failed · ${n(hour.totals.refused)} refused`
              : recent.error || "Loading"
          }
        />
        <Kpi
          label="Findings awaiting a verdict"
          value={n(waiting.length)}
          hint={`${value.review.length} recent findings`}
        />
        <Kpi
          label="Model calls, last hour"
          value={hour ? n(hour.totals.by_family.model) : "—"}
          hint="Counted from recorded model spans"
        />
      </div>
      <div className="ov-row ov-main">
        <Panel
          eyebrow="Activity, last hour"
          title={
            hour && hour.totals.actions
              ? `${n(hour.totals.actions)} actions across ${new Set(actors.map((row) => row.arena_id)).size} arena${new Set(actors.map((row) => row.arena_id)).size === 1 ? "" : "s"}`
              : "No actions in the last hour"
          }
        >
          <div className="ov-body">
            {hour ? (
              <ActivityChart
                buckets={hour.buckets}
                bucketSeconds={hour.bucket_seconds}
                caption="Actions per interval in the last hour, by kind"
              />
            ) : (
              <Empty
                title={recent.error ? "Activity unavailable" : "Loading"}
                detail={recent.error || "Reading the last hour of spans."}
              />
            )}
          </div>
        </Panel>
        <Panel eyebrow="By agent, last hour" title="Who did the work">
          <div className="ov-body">
            {actors.length ? (
              <Bars
                rows={actors.slice(0, 6).map((row) => ({
                  key: `${row.actor}:${row.arena_id}`,
                  label: row.actor,
                  sub: row.arena_id
                    ? names.get(row.arena_id) || row.arena_id
                    : "platform",
                  value: row.actions + row.model_calls,
                  failed: row.failed,
                  note: row.refused ? `${row.refused} refused` : undefined,
                }))}
              />
            ) : (
              <Empty
                title="No one acted in the last hour"
                detail="Tool calls and model calls by every agent and operator are counted here."
              />
            )}
          </div>
          <div className="panel-foot">
            <span>Tool and model calls; failures are the red end</span>
          </div>
        </Panel>
      </div>
      <div className="ov-row ov-main">
        <Panel
          eyebrow="Arenas"
          title="Running and recent"
          aside={
            <a className="inline-action" href="/console/arenas">
              All arenas
            </a>
          }
        >
          {value.sessions.length ? (
            <div className="ov-table-wrap">
              <table className="ov-table">
                <thead>
                  <tr>
                    <th>Arena</th>
                    <th>State</th>
                    <th>Scenario</th>
                    <th>Provider</th>
                    <th className="r">Stations</th>
                  </tr>
                </thead>
                <tbody>
                  {value.sessions.slice(0, 6).map((item) => (
                    <tr key={item.id}>
                      <td>
                        <a
                          href={`/console/arena/${encodeURIComponent(item.id)}`}
                        >
                          <b>{item.name}</b>
                          <small className="mono">{item.id.slice(0, 12)}</small>
                        </a>
                      </td>
                      <td>
                        <Status value={item.status} />
                      </td>
                      <td>{item.scenario}</td>
                      <td className="mono">{item.provider}</td>
                      <td className="r mono">{item.nodes.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="ov-body">
              <Empty
                title="No arenas yet"
                detail="Launch one in Cyber Range or start research from a pinned target."
                action={
                  <a
                    className="button button-outline"
                    href="/console/arenas/new"
                  >
                    New arena
                  </a>
                }
              />
            </div>
          )}
        </Panel>
        <Capacity />
      </div>
    </>
  );
}

function Kpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="panel ov-kpi">
      <span className="eyebrow">{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  );
}

type Usage = {
  ok: boolean;
  cpu: number | null;
  mem: number | null;
  disk: number | null;
  uptime: string | null;
  mem_used_gb: number | null;
  mem_total_gb: number | null;
  containers: number;
  networks: number;
  active_arenas: number;
};

function Gauge({
  label,
  value,
  detail,
}: {
  label: string;
  value: number | null;
  detail?: string;
}) {
  const level =
    value == null ? "" : value >= 85 ? "high" : value >= 65 ? "warm" : "";
  return (
    <div className={`capacity-gauge ${level}`}>
      <div>
        <span>{label}</span>
        <strong>{value == null ? "—" : `${value}%`}</strong>
      </div>
      <svg viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">
        <rect className="capacity-track" width="100" height="4" />
        <rect className="capacity-fill" width={value ?? 0} height="4" />
      </svg>
      {detail && <small>{detail}</small>}
    </div>
  );
}

// Host load as the console process sees it, plus the live arena footprint.
function Capacity() {
  const { value, error } = useWorkspaceData<Usage>("/api/system-usage");
  return (
    <Panel
      eyebrow="Capacity"
      title="Host & arenas"
      className="research-capacity"
    >
      {error ? (
        <Empty title="Capacity unavailable" detail={error} />
      ) : !value ? (
        <Empty title="Reading capacity" detail="Sampling host load." />
      ) : (
        <>
          <div className="capacity-gauges">
            <Gauge label="CPU load" value={value.cpu} />
            <Gauge
              label="Memory"
              value={value.mem}
              detail={
                value.mem_used_gb != null && value.mem_total_gb != null
                  ? `${value.mem_used_gb} of ${value.mem_total_gb} GB`
                  : undefined
              }
            />
            <Gauge label="Disk" value={value.disk} />
          </div>
          <div className="capacity-counts">
            <div>
              <strong>{value.active_arenas}</strong>
              <span>live arenas</span>
            </div>
            <div>
              <strong>{value.containers}</strong>
              <span>stations</span>
            </div>
            <div>
              <strong>{value.networks}</strong>
              <span>arena networks</span>
            </div>
            <div>
              <strong>{value.uptime || "—"}</strong>
              <span>uptime</span>
            </div>
          </div>
          <div className="panel-foot">
            <span>
              Sampled from the console host. Station counts come from live arena
              outputs.
            </span>
          </div>
        </>
      )}
    </Panel>
  );
}
