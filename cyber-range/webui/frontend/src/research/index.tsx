import { useState } from "react";
import type { ActivityData, ArenaData, ResearchData } from "../types";
import { SegmentMap } from "../topology/SegmentMap";
import { stationDetail } from "../arena/forge";
import { paths } from "../types";
import {
  formatObserved,
  useWorkspaceData,
  Status,
  Panel,
  Empty,
  PageHead,
  Loading,
  ErrorState,
} from "../ui";

export function Research() {
  const { value, error, loading, refresh } = useWorkspaceData<ResearchData>(
    paths.research,
  );
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const live = value.sessions.filter(
    (item) =>
      !["destroyed", "failed", "error_destroying"].includes(item.status),
  );
  const featured = live.find((item) => item.status === "active") || live[0];
  return (
    <>
      <PageHead
        overline="WORKSPACE / RESEARCH"
        title="Research"
        subtitle="Sessions, proof and decisions in one operating view."
        observed={value.observed_at}
        action={
          <a className="button button-gold" href="/console/research/new">
            New research <span aria-hidden="true">↗</span>
          </a>
        }
        refresh={refresh}
      />
      <div className="research-grid">
          <Panel
            eyebrow="01 / CURRENT WORK"
            title="Active session"
            className="featured"
            aside={featured && <Status value={featured.status} />}
          >
            {featured ? (
              <>
                <div className="featured-main featured-main-map">
                  <div>
                    <span className="micro-label">PINNED WORKSPACE</span>
                    <h3>{featured.name}</h3>
                    <p>{featured.scenario}</p>
                    <div className="meta-pills">
                      <span>{featured.provider}</span>
                      <span>Session {featured.id.slice(0, 8)}</span>
                    </div>
                  </div>
                </div>
                <FeaturedTopology id={featured.id} />
                <div className="panel-foot">
                  <span>
                    Open the arena for tools, evidence and lifecycle state.
                  </span>
                  <a
                    className="inline-action"
                    href={`/console/arena/${encodeURIComponent(featured.id)}`}
                  >
                    Open workspace ↗
                  </a>
                </div>
              </>
            ) : (
              <Empty
                title="No live sessions"
                detail="Start research from a pinned target or challenge."
                action={
                  <a className="inline-action" href="/console/research/new">
                    Create research ↗
                  </a>
                }
              />
            )}
          </Panel>
          <Panel
            eyebrow="02 / DECISIONS"
            title="Needs review"
            className="review-panel"
            aside={<span className="count">{value.review.length}</span>}
          >
            {value.review.length ? (
              <div className="compact-list">
                {value.review.slice(0, 3).map((finding, index) => (
                  <a
                    key={finding.id || index}
                    href={
                      finding.arena_known && finding.arena_id
                        ? `/console/arena/${encodeURIComponent(finding.arena_id)}?tab=findings`
                        : "/console/activity?section=findings"
                    }
                    className="compact-row"
                  >
                    <span>
                      <strong>{finding.title}</strong>
                      <small>
                        {finding.arena_name} ·{" "}
                        {finding.verdict.replaceAll("_", " ")}
                      </small>
                    </span>
                    <b aria-hidden="true">↗</b>
                  </a>
                ))}
              </div>
            ) : (
              <Empty
                title="Review queue clear"
                detail="Findings that need an operator verdict will appear here."
              />
            )}
            <div className="panel-foot">
              <a
                className="inline-action"
                href="/console/activity?section=findings"
              >
                View all findings ↗
              </a>
            </div>
          </Panel>
          <Panel
            eyebrow="03 / RECORDS"
            title="Recent sessions"
            className="sessions-panel"
            aside={
              <a className="subtle-link" href="/engagements">
                View all
              </a>
            }
          >
            {value.sessions.length ? (
              <div className="session-table">
                <div className="table-labels">
                  <span>SESSION</span>
                  <span>STATUS</span>
                  <span>SCENARIO</span>
                  <span />
                </div>
                {value.sessions.slice(0, 6).map((item) => (
                  <a
                    key={item.id}
                    className="session-row"
                    href={`/console/arena/${encodeURIComponent(item.id)}`}
                  >
                    <span className="session-name">
                      <strong>{item.name}</strong>
                      <small>{item.id.slice(0, 8)}</small>
                    </span>
                    <Status value={item.status} />
                    <span className="row-scenario">{item.scenario}</span>
                    <span aria-hidden="true">↗</span>
                  </a>
                ))}
              </div>
            ) : (
              <Empty
                title="No session records"
                detail="Created and archived research will be listed here."
              />
            )}
          </Panel>
          <Panel
            eyebrow="04 / EVIDENCE"
            title="Proof desk"
            className="evidence-panel"
          >
            <div className="resource-links">
              <a href="/console/activity?section=evidence">
                <strong>Evidence library</strong>
                <small>Artifacts and provenance</small>
                <span>↗</span>
              </a>
              <a href="/console/activity?section=audit">
                <strong>Audit trace</strong>
                <small>Attributed events</small>
                <span>↗</span>
              </a>
              <a href="/console/library/targets">
                <strong>Target library</strong>
                <small>Source and pinned identities</small>
                <span>↗</span>
              </a>
            </div>
          </Panel>
        <LiveActivity />
      </div>
    </>
  );
}

type Source = "all" | "agent" | "human" | "system";
const SOURCES: Source[] = ["all", "agent", "human", "system"];

// Latest attributed events across arenas, filterable by who acted.
function LiveActivity() {
  const [source, setSource] = useState<Source>("all");
  const { value, error } = useWorkspaceData<ActivityData>(
    "/api/console/activity",
  );
  const events = [...(value?.audit || [])]
    .filter((item) => source === "all" || item.source === source)
    .sort((first, second) => (second.ts || "").localeCompare(first.ts || ""))
    .slice(0, 6);
  return (
    <Panel
      eyebrow="05 / ACTIVITY"
      title="Live activity"
      className="research-activity"
      aside={
        <nav className="registry-tabs" aria-label="Filter activity by source">
          {SOURCES.map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={source === item}
              onClick={() => setSource(item)}
            >
              {item === "all"
                ? "All"
                : item === "agent"
                  ? "Agents"
                  : item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </nav>
      }
    >
      {error ? (
        <Empty title="Activity unavailable" detail={error} />
      ) : !value ? (
        <Empty title="Loading activity" detail="Fetching recent events." />
      ) : events.length ? (
        <div className="activity-list">
          {events.map((item, index) => (
            <article
              className="activity-row activity-audit-row"
              key={`${item.ts}-${index}`}
            >
              <span className="activity-source">{item.source}</span>
              <strong>{item.type.replaceAll("_", " ")}</strong>
              <small>
                {item.actor} · {item.arena_name || "platform"} ·{" "}
                {item.ts ? formatObserved(item.ts) : "Time unknown"}
              </small>
              {item.arena_known && item.arena_id && (
                <a
                  className="inline-action"
                  href={`/console/arena/${encodeURIComponent(item.arena_id)}`}
                >
                  Arena ↗
                </a>
              )}
            </article>
          ))}
        </div>
      ) : (
        <Empty
          title={
            source === "all" ? "No recorded activity" : `No ${source} events`
          }
          detail="Attributed events from arenas and the platform appear here."
        />
      )}
      <div className="panel-foot">
        <span>Events come from the append-only audit trail.</span>
        <a className="inline-action" href="/console/activity?section=audit">
          Full audit trail ↗
        </a>
      </div>
    </Panel>
  );
}

// The same declared-topology map the Arena page draws, from the arena
// projection, so the overview and the workspace never disagree.
function FeaturedTopology({ id }: { id: string }) {
  const { value, error } = useWorkspaceData<ArenaData>(
    `/api/console/arenas/${encodeURIComponent(id)}`,
  );
  const [selected, setSelected] = useState<string | undefined>();
  if (error)
    return (
      <p className="featured-topology-note">
        Topology unavailable here; open the workspace to inspect it.
      </p>
    );
  if (!value)
    return <p className="featured-topology-note">Loading topology…</p>;
  const current =
    selected ||
    value.nodes.find((node) => !node.foothold)?.name ||
    value.nodes[0]?.name;
  return (
    <div className="featured-topology forge-workbench">
      <div className="forge-canvas">
        <SegmentMap
          compact
          nodes={value.nodes.map((item) => ({
            name: item.name,
            kind: item.foothold ? "foothold" : "target",
            detail: stationDetail(item),
            state: item.state,
          }))}
          segments={value.topology?.segments || []}
          unsegmented={value.topology?.unsegmented || []}
          unavailable={!value.topology}
          selected={current}
          onSelect={setSelected}
        />
      </div>
    </div>
  );
}
