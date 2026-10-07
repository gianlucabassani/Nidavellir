import type { ResearchData } from "../types";
import {
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

export function TargetsLibrary() {
  const { value, error, loading, refresh } = useWorkspaceData<ResearchData>(
    "/api/console/research",
  );
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  return (
    <>
      <PageHead
        overline="LIBRARY / TARGETS"
        title="Targets"
        subtitle="Start from an immutable Git commit, an OCI digest, or a source bundle. Review the pinned identity before launch."
        observed={value.observed_at}
        action={
          <a className="button button-gold" href="/console/research/new">
            New research ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="target-source-grid">
        <a href="/console/research/new?source=git">
          <span>01 / REPOSITORY</span>
          <strong>Git target</strong>
          <p>
            Resolve a public repository and ref to one commit. Review build
            inputs and topology.
          </p>
          <b>Import Git ↗</b>
        </a>
        <a href="/console/research/new?source=oci">
          <span>02 / IMAGE</span>
          <strong>OCI target</strong>
          <p>
            Pin an image by digest and inspect runtime identity before creating
            a session.
          </p>
          <b>Import image ↗</b>
        </a>
        <a href="/console/research/new?source=bundle">
          <span>03 / ARCHIVE</span>
          <strong>Source bundle</strong>
          <p>
            Upload a bounded source archive, review its digest and setup plan,
            then launch it in isolation.
          </p>
          <b>Open bundle intake ↗</b>
        </a>
      </div>
      <Panel
        eyebrow="04 / RESEARCH RECORDS"
        title="Sessions using targets"
        aside={
          <span className="tiny-tag">{value.sessions.length} RECORDS</span>
        }
      >
        {value.sessions.length ? (
          <div className="shared-record-list">
            {value.sessions.map((item) => (
              <a
                className="shared-session-link"
                href={`/console/arena/${encodeURIComponent(item.id)}`}
                key={item.id}
              >
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {item.scenario} · {item.provider}
                  </small>
                </span>
                <Status value={item.status} />
                <b>↗</b>
              </a>
            ))}
          </div>
        ) : (
          <Empty
            title="No research sessions"
            detail="Create a session from a pinned target to retain its setup and evidence."
          />
        )}
      </Panel>
    </>
  );
}
