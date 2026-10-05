import type { BenchmarkData } from "../types";
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

export function Benchmark() {
  const { value, error, loading, refresh } = useWorkspaceData<BenchmarkData>(
    paths.benchmark,
  );
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const latest = value.evaluations[0];
  const lookup = (id: string) => value.builds.find((build) => build.id === id);
  return (
    <>
      <PageHead
        overline="WORKSPACE / BENCHMARK"
        title="Benchmark"
        subtitle="Compare pinned builds on matched calibration trials."
        observed={value.observed_at}
        action={
          <a className="button button-gold" href="/console/evaluations/new">
            New comparison ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="scope-note">
        <strong>Calibration scope</strong>
        <span>
          Public synthetic challenges check the workbench. Scripted results do
          not establish held-out model capability.
        </span>
        <b>SCRIPTED DRIVER</b>
      </div>
      <div className="benchmark-grid">
        <Panel
          eyebrow="01 / LATEST EVALUATION"
          title="Latest comparison"
          className="latest-panel"
          aside={latest && <Status value={latest.state} />}
        >
          {latest ? (
            <>
              <div className="pair">
                <div>
                  <span>BASELINE</span>
                  <strong>
                    {lookup(latest.baseline_id)?.name ||
                      latest.baseline_id.slice(0, 8)}
                  </strong>
                  <small>
                    {lookup(latest.baseline_id)?.version || "Pinned build"}
                  </small>
                </div>
                <span className="pair-arrow" aria-hidden="true">
                  ⇄
                </span>
                <div>
                  <span>CANDIDATE</span>
                  <strong>
                    {lookup(latest.candidate_id)?.name ||
                      latest.candidate_id.slice(0, 8)}
                  </strong>
                  <small>
                    {lookup(latest.candidate_id)?.version || "Pinned build"}
                  </small>
                </div>
              </div>
              <div className="panel-foot">
                <span>Evaluation {latest.id.slice(0, 8)}</span>
                <a
                  className="inline-action"
                  href={`/console/evaluations/${encodeURIComponent(latest.id)}`}
                >
                  Inspect results ↗
                </a>
              </div>
            </>
          ) : (
            <Empty
              title="No comparisons yet"
              detail="Register two builds and a suite to run matched trials."
              action={
                <a className="inline-action" href="/console/evaluations/new">
                  Configure comparison ↗
                </a>
              }
            />
          )}
        </Panel>
        <Panel
          eyebrow="02 / REGISTRY"
          title="Ready to use"
          className="registry-panel"
        >
          <div className="registry-list">
            <a href="/console/benchmark/registry?kind=builds">
              <strong>Agent builds</strong>
              <span>{value.builds.length}</span>
            </a>
            <a href="/console/benchmark/registry?kind=challenges">
              <strong>Challenges</strong>
              <span>{value.challenges.length}</span>
            </a>
            <a href="/console/benchmark/registry?kind=suites">
              <strong>Suites</strong>
              <span>{value.suites.length}</span>
            </a>
          </div>
        </Panel>
        <Panel
          eyebrow="03 / EVALUATIONS"
          title="Recent comparisons"
          className="comparisons-panel"
          aside={
            <a className="subtle-link" href="/evaluations#recent">
              View all
            </a>
          }
        >
          {value.evaluations.length ? (
            <div className="compact-list">
              {value.evaluations.slice(0, 5).map((item) => (
                <a
                  className="compact-row"
                  href={`/console/evaluations/${encodeURIComponent(item.id)}`}
                  key={item.id}
                >
                  <span>
                    <strong>Evaluation {item.id.slice(0, 8)}</strong>
                    <small>
                      Suite {item.suite_id?.slice(0, 8) || "unknown"} ·{" "}
                      {item.state}
                    </small>
                  </span>
                  <b>↗</b>
                </a>
              ))}
            </div>
          ) : (
            <Empty
              title="No evaluation records"
              detail="Completed and interrupted comparisons will be retained here."
            />
          )}
        </Panel>
        <Panel
          eyebrow="04 / CONDITIONS"
          title="Pinned material"
          className="material-panel"
        >
          <div className="material-count">
            <strong>{value.challenges.length}</strong>
            <span>versioned challenges</span>
          </div>
          <div className="material-count">
            <strong>{value.suites.length}</strong>
            <span>matched suites</span>
          </div>
          <div className="panel-foot">
            <a className="inline-action" href="/console/benchmark/registry">
              Manage evaluation registry ↗
            </a>
          </div>
        </Panel>
      </div>
    </>
  );
}
