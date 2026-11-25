import {
  BackLink,
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  useWorkspaceData,
} from "../ui";
import { format } from "./dashboard";

// UX-11 (FR-16): a suite's outcome over time by agent build. Calibration and
// held-out material are separate series, never one line; an evaluation whose
// trials all failed on infrastructure has no score point.

type Point = {
  evaluation_id: string;
  at: string;
  side: string | null;
  completed: number;
  passed: number;
  infrastructure_failures: number;
  agent_failures: number;
  pass_rate: number | null;
};
export type SuiteHistory = {
  suite: { id: string; name: string | null };
  evaluations: number;
  builds: Record<string, { name: string; version: string | null }>;
  challenges: Record<string, string>;
  series: { build_id: string; scope: string; points: Point[] }[];
  flaky: {
    build_id: string;
    challenge_id: string;
    seed: number;
    verdicts: { evaluation_id: string; passed: boolean }[];
  }[];
};

function SeriesChart({
  series,
  name,
}: {
  series: SuiteHistory["series"][number];
  name: string;
}) {
  const width = 520;
  const height = 120;
  const pad = 18;
  const n = series.points.length;
  const x = (index: number) =>
    n < 2 ? width / 2 : pad + (index / (n - 1)) * (width - 2 * pad);
  const y = (rate: number) => height - pad - rate * (height - 2 * pad);
  const scored = series.points
    .map((point, index) => ({ point, index }))
    .filter(({ point }) => point.pass_rate != null);
  return (
    <svg
      className="history-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${name}, ${series.scope}: pass rate over ${n} evaluations`}
    >
      <line
        className="history-axis"
        x1={pad}
        x2={width - pad}
        y1={y(0)}
        y2={y(0)}
      />
      <line
        className="history-grid"
        x1={pad}
        x2={width - pad}
        y1={y(1)}
        y2={y(1)}
      />
      <text className="history-tick" x={2} y={y(1) + 4}>
        1
      </text>
      <text className="history-tick" x={2} y={y(0) + 4}>
        0
      </text>
      {scored.length > 1 && (
        <polyline
          className="history-line"
          points={scored
            .map(({ point, index }) => `${x(index)},${y(point.pass_rate!)}`)
            .join(" ")}
        />
      )}
      {series.points.map((point, index) =>
        point.pass_rate == null ? (
          <text
            key={point.evaluation_id}
            className="history-infra"
            x={x(index)}
            y={y(0) - 4}
            textAnchor="middle"
          >
            ⚠
            <title>
              {`${point.at}: no completed trial (${point.infrastructure_failures} infrastructure failures) — not scored`}
            </title>
          </text>
        ) : (
          <a
            key={point.evaluation_id}
            href={`/console/evaluations/${encodeURIComponent(point.evaluation_id)}`}
          >
            <circle
              className="history-dot"
              cx={x(index)}
              cy={y(point.pass_rate)}
              r={5}
            >
              <title>
                {`${point.at}: ${point.passed}/${point.completed} passed${point.infrastructure_failures ? `, ${point.infrastructure_failures} infrastructure failures not scored` : ""}`}
              </title>
            </circle>
          </a>
        ),
      )}
    </svg>
  );
}

export function SuiteHistoryPage({ suiteId }: { suiteId: string }) {
  const { value, error, loading, refresh } = useWorkspaceData<SuiteHistory>(
    `/api/console/eval-suites/${encodeURIComponent(suiteId)}/history`,
  );
  if (loading && !value) return <Loading />;
  if (error && !value) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const buildName = (id: string) => {
    const build = value.builds[id];
    return build
      ? `${build.name}${build.version ? ` ${build.version}` : ""}`
      : id;
  };
  const scopes = ["held-out", "calibration"].filter((scope) =>
    value.series.some((series) => series.scope === scope),
  );
  return (
    <>
      <div className="arena-return">
        <BackLink href="/console/evaluations" label="All evaluations" />
        <span>/</span>
        <span>Suite history</span>
      </div>
      <PageHead
        overline={`BENCHMARK / SUITE ${value.suite.name || value.suite.id}`}
        title="Suite history"
        subtitle={`Pass rate over ${value.evaluations} evaluation(s) by agent build. Held-out and calibration material are never one series.`}
        action={
          <a className="button" href="/console/evaluations/new">
            New comparison
          </a>
        }
        refresh={refresh}
      />
      {scopes.length ? (
        scopes.map((scope) => (
          <Panel
            key={scope}
            eyebrow={scope === "held-out" ? "HELD-OUT" : "CALIBRATION"}
            title={
              scope === "held-out"
                ? "Held-out outcome over time"
                : "Calibration outcome over time — not held-out capability"
            }
          >
            <div className="history-series">
              {value.series
                .filter((series) => series.scope === scope)
                .map((series) => (
                  <figure key={series.build_id}>
                    <figcaption>{buildName(series.build_id)}</figcaption>
                    <SeriesChart
                      series={series}
                      name={buildName(series.build_id)}
                    />
                    <small>
                      Latest:{" "}
                      {format(
                        [...series.points]
                          .reverse()
                          .find((point) => point.pass_rate != null)?.pass_rate,
                      )}{" "}
                      · ⚠ marks an evaluation with no completed trial (not
                      scored)
                    </small>
                  </figure>
                ))}
            </div>
          </Panel>
        ))
      ) : (
        <Empty
          title="No finished trials yet"
          detail="History appears once an evaluation of this suite has run."
        />
      )}
      <Panel
        eyebrow="FLAKINESS"
        title="Same build, same seed, different verdict"
      >
        {value.flaky.length ? (
          <div className="trial-results-scroll">
            <table className="trial-results" aria-label="Flaky cells">
              <thead>
                <tr>
                  <th scope="col">Build</th>
                  <th scope="col">Challenge</th>
                  <th scope="col">Seed</th>
                  <th scope="col">Verdicts (oldest first)</th>
                </tr>
              </thead>
              <tbody>
                {value.flaky.map((cell) => (
                  <tr
                    key={`${cell.build_id}-${cell.challenge_id}-${cell.seed}`}
                  >
                    <th scope="row">{buildName(cell.build_id)}</th>
                    <td>
                      {value.challenges[cell.challenge_id] || cell.challenge_id}
                    </td>
                    <td>{cell.seed}</td>
                    <td>
                      {cell.verdicts.map((verdict, index) => (
                        <a
                          key={index}
                          className={`outcome-cell outcome-${verdict.passed ? "pass" : "fail"}`}
                          href={`/console/evaluations/${encodeURIComponent(verdict.evaluation_id)}`}
                          title={verdict.passed ? "Pass" : "Fail"}
                        >
                          {verdict.passed ? "✓" : "✕"}
                        </a>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="No flaky cells"
            detail="Every repeated build and seed returned the same verdict."
          />
        )}
      </Panel>
    </>
  );
}
