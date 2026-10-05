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
              <div className="featured-main">
                <div>
                  <span className="micro-label">PINNED WORKSPACE</span>
                  <h3>{featured.name}</h3>
                  <p>{featured.scenario}</p>
                  <div className="meta-pills">
                    <span>{featured.provider}</span>
                    <span>Session {featured.id.slice(0, 8)}</span>
                  </div>
                </div>
                <div className="topology-art">
                  {featured.nodes.length ? (
                    <div className="topology-mini-nodes">
                      {featured.nodes.slice(0, 4).map((node) => (
                        <span key={node.name} title={node.name}>
                          {node.foothold ? "◈" : "⬡"}
                          <small>{node.name}</small>
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="topology-unavailable">
                      Topology available inside the workspace
                    </span>
                  )}
                </div>
              </div>
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
                      ? `/arena/${encodeURIComponent(finding.arena_id)}#findings`
                      : "/activity/findings"
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
            <a className="inline-action" href="/activity/findings">
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
            <a href="/activity/evidence">
              <strong>Evidence library</strong>
              <small>Artifacts and provenance</small>
              <span>↗</span>
            </a>
            <a href="/activity/audit">
              <strong>Audit trace</strong>
              <small>Attributed events</small>
              <span>↗</span>
            </a>
            <a href="/library/targets">
              <strong>Target library</strong>
              <small>Source and pinned identities</small>
              <span>↗</span>
            </a>
          </div>
        </Panel>
      </div>
    </>
  );
}
