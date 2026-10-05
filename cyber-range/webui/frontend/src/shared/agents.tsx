import type { AgentsData } from "../types";
import {
  Empty,
  ErrorState,
  formatObserved,
  Loading,
  PageHead,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

export function AgentsLibrary() {
  const { value, error, loading, refresh } = useWorkspaceData<AgentsData>(
    "/api/console/agents",
  );
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  return (
    <>
      <PageHead
        overline="LIBRARY / AGENTS"
        title="Agents"
        subtitle="Pinned builds for comparisons and observed gateway connections across arenas."
        observed={value.observed_at}
        action={
          <a
            className="button button-gold"
            href="/console/benchmark/registry?kind=builds"
          >
            Register build ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="shared-grid">
        <Panel
          eyebrow="01 / BUILD REGISTRY"
          title="Pinned agent builds"
          className="shared-primary"
          aside={<span className="tiny-tag">{value.builds.length} BUILDS</span>}
        >
          {value.builds.length ? (
            <div className="shared-record-list">
              {value.builds.map((item) => (
                <article key={item.id} className="shared-record">
                  <div>
                    <strong>{item.name}</strong>
                    <span>{item.version}</span>
                  </div>
                  <small>{item.driver}</small>
                  <code>{item.digest || item.id}</code>
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="No registered builds"
              detail="Register a scripted or model-driven configuration before a paired comparison."
              action={
                <a
                  className="inline-action"
                  href="/console/benchmark/registry?kind=builds"
                >
                  Open build registry ↗
                </a>
              }
            />
          )}
        </Panel>
        <Panel
          eyebrow="02 / RUNTIME"
          title="Recent connections"
          aside={
            <span className="tiny-tag">{value.connections.length} SEEN</span>
          }
        >
          {value.connections.length ? (
            <div className="shared-record-list">
              {value.connections.map((item, index) => (
                <article
                  key={`${item.arena_id}-${item.stance}-${index}`}
                  className="shared-record"
                >
                  <div>
                    <strong>
                      {item.model || item.actor || "Agent connection"}
                    </strong>
                    <Status value={item.active ? "active" : "inactive"} />
                  </div>
                  <small>
                    {item.arena_name} · {item.stance} ·{" "}
                    {item.provider || "provider unknown"}
                  </small>
                  <small>
                    {item.commands} commands · {item.findings} findings ·{" "}
                    {item.last_seen
                      ? formatObserved(item.last_seen)
                      : "No recent action"}
                  </small>
                  {item.arena_id && (
                    <a
                      className="inline-action"
                      href={`/console/arena/${encodeURIComponent(item.arena_id)}`}
                    >
                      Open arena ↗
                    </a>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="No agent connections"
              detail="Gateway sessions will appear when an agent connects to an arena."
            />
          )}
        </Panel>
        <Panel
          eyebrow="03 / TRACE"
          title="Agent activity"
          className="shared-wide"
        >
          {value.timeline.length ? (
            <div className="shared-timeline">
              {value.timeline.slice(0, 30).map((item, index) => (
                <div key={`${item.ts}-${index}`}>
                  <time>
                    {item.ts ? formatObserved(item.ts) : "Time unknown"}
                  </time>
                  <strong>
                    {item.summary || item.type.replaceAll("_", " ")}
                  </strong>
                  <small>
                    {item.arena_name} · {item.actor || item.stance || "agent"}
                  </small>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="No agent activity"
              detail="Agent actions will appear here after a gateway session starts."
            />
          )}
        </Panel>
      </div>
    </>
  );
}
