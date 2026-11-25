import type { EvaluationDetailData } from "../types";
import { navigate } from "../router";
import { usePaletteActions } from "../shared/palette";
import {
  ACTIVE,
  DifferencePlot,
  Distribution,
  OutcomeGrid,
  format as number,
  intervalLabel as interval,
  metricName,
  useEvaluationStream,
} from "./dashboard";
import {
  useWorkspaceData,
  Status,
  Panel,
  Empty,
  PageHead,
  Loading,
  ErrorState,
  BackLink,
} from "../ui";

function evidenceScope(scope: string) {
  return scope === "calibration_or_unknown"
    ? "Calibration or unclassified"
    : scope.replaceAll("_", " ");
}

export function EvaluationDetail({ id }: { id: string }) {
  const { value, error, loading, refresh } =
    useWorkspaceData<EvaluationDetailData>(
      `/api/console/evaluations/${encodeURIComponent(id)}`,
    );
  useEvaluationStream(id, ACTIVE.has(value?.state || ""), refresh);
  const firstPair = (() => {
    const trials = value?.trials || [];
    for (const baseline of trials) {
      if (baseline.side !== "baseline" || !baseline.arena_id) continue;
      const candidate = trials.find(
        (trial) =>
          trial.side === "candidate" &&
          trial.arena_id &&
          trial.seed === baseline.seed &&
          trial.challenge_id === baseline.challenge_id,
      );
      if (candidate) return { baseline, candidate };
    }
    return null;
  })();
  usePaletteActions(`evaluation:${id}`, [
    ...(firstPair
      ? [
          {
            id: "compare",
            label: `Compare baseline and candidate, seed ${firstPair.baseline.seed}`,
            run: () =>
              navigate(
                `/console/evaluations/${encodeURIComponent(id)}/compare?a=${encodeURIComponent(firstPair.baseline.id)}&b=${encodeURIComponent(firstPair.candidate.id)}`,
              ),
          },
        ]
      : []),
    ...(value?.suite_id
      ? [
          {
            id: "history",
            label: "Open suite history",
            run: () =>
              navigate(
                `/console/suites/${encodeURIComponent(value.suite_id!)}/history`,
              ),
          },
        ]
      : []),
  ]);
  if (loading && !value) return <Loading />;
  if (error && !value) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const metrics = Object.entries(value.differences);
  return (
    <>
      <div className="arena-return">
        <BackLink href="/console?workspace=benchmark" label="Benchmark" />
        <span>/</span>
        <span className="evaluation-crumb" title={value.id}>
          Evaluation {value.id}
        </span>
        {value.suite_id && (
          <a
            className="inline-action crumb-aside"
            href={`/console/suites/${encodeURIComponent(value.suite_id)}/history`}
          >
            Suite history
          </a>
        )}
      </div>
      <PageHead
        overline={`BENCHMARK / EVALUATION ${value.id}`}
        title={
          value.state === "queued" || value.state === "running"
            ? "Evaluation progress"
            : "Evaluation result"
        }
        subtitle={
          value.state === "queued" || value.state === "running"
            ? "Track each trial as the service executes the comparison."
            : "Candidate minus baseline on observed-state-matched trials."
        }
        observed={value.observed_at}
        action={<Status value={value.state} />}
        refresh={refresh}
      />
      <div className="scope-note">
        <strong>Evidence scope: {evidenceScope(value.evidence_scope)}</strong>
        <span>
          {value.leakage_labels.length
            ? `Labels: ${value.leakage_labels.join(", ")}.`
            : "Leakage label unavailable."}{" "}
          Calibration evidence does not establish held-out capability.
        </span>
      </div>
      {(value.state === "queued" || value.state === "running") && (
        <div className="result-progress" role="status" aria-live="polite">
          <div>
            <strong>
              {value.progress.finished} of {value.progress.total} trials
              finished
            </strong>
            <span>
              {value.progress.running} running · Results update live while this
              page is open.
            </span>
          </div>
          <progress
            value={value.progress.finished}
            max={Math.max(value.progress.total, 1)}
            aria-label="Evaluation trial progress"
          />
        </div>
      )}
      <div className="result-facts">
        <div>
          <small>MATCHED PAIRS</small>
          <strong>{value.matched_pairs ?? "—"}</strong>
        </div>
        <div>
          <small>INFRASTRUCTURE FAILURES</small>
          <strong>{value.infrastructure_failed_pairs ?? "—"}</strong>
        </div>
        <div>
          <small>VERIFIED DIFFERENCE</small>
          <strong>{number(value.differences.verified?.mean)}</strong>
        </div>
        <div>
          <small>INTERVAL</small>
          <strong>
            {interval(value.differences.verified?.interval_status)}
          </strong>
        </div>
      </div>
      <div className="result-grid">
        <Panel
          eyebrow="01 / COMPARISON"
          title="Paired differences"
          className="result-metrics"
        >
          {metrics.length ? (
            <div className="result-table">
              <div className="result-table-head">
                <span>METRIC</span>
                <span>MEAN</span>
                <span>PAIRS</span>
                <span>BOOTSTRAP 95%</span>
                <span>INTERVAL</span>
                <span>DIFFERENCE (CANDIDATE − BASELINE)</span>
              </div>
              {metrics.map(([name, metric]) => (
                <div className="result-table-row" key={name}>
                  <strong>{metricName(name)}</strong>
                  <span>{number(metric.mean)}</span>
                  <span>{metric.pairs ?? "—"}</span>
                  <span>
                    {metric.bootstrap_95
                      ? `${number(metric.bootstrap_95[0])} to ${number(metric.bootstrap_95[1])}`
                      : "Unavailable"}
                  </span>
                  <span>{interval(metric.interval_status)}</span>
                  <span>
                    <DifferencePlot name={name} metric={metric} />
                  </span>
                </div>
              ))}
              <p className="result-interval-note">
                Dot: mean paired difference; bar: bootstrap 95% interval (dashed
                when there are too few pairs). A constant paired difference is
                degenerate: it is drawn as a hollow dot with no interval,
                because zero width does not establish certainty.
              </p>
            </div>
          ) : (
            <Empty
              title={
                value.state === "complete"
                  ? "No matched comparison"
                  : "Comparison pending"
              }
              detail={
                value.state === "complete"
                  ? "Inspect trial states and infrastructure failures below. No paired difference can be reported for this run."
                  : "Paired trial differences are not available yet."
              }
            />
          )}
        </Panel>
        <Panel
          eyebrow="02 / ATTRIBUTION"
          title="By challenge"
          className="result-challenges"
        >
          {value.challenges.length ? (
            <div className="compact-list">
              {value.challenges.map((challenge) => (
                <div className="challenge-row" key={challenge.id}>
                  <strong>{challenge.name}</strong>
                  <small>
                    {challenge.leakage_label || "unlabelled"} ·{" "}
                    {challenge.matched_pairs ?? 0} matched pairs
                  </small>
                  <span>
                    Verified difference <b>{number(challenge.verified_mean)}</b>
                  </span>
                  <span>
                    Infrastructure failures{" "}
                    <b>{challenge.infrastructure_failed_pairs ?? 0}</b>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="No challenge breakdown"
              detail="Challenge-level attribution will appear when trials are compared."
            />
          )}
        </Panel>
        <Panel
          eyebrow="03 / OUTCOMES"
          title="Outcome by seed"
          className="result-trials"
        >
          {value.trials.length ? (
            <OutcomeGrid
              evaluation={value}
              challengeNames={Object.fromEntries(
                value.challenges.map((challenge) => [
                  challenge.id,
                  challenge.name,
                ]),
              )}
            />
          ) : (
            <Empty
              title="No trials scheduled"
              detail="The outcome grid fills in as trials are scheduled."
            />
          )}
        </Panel>
        <Panel
          eyebrow="04 / DISTRIBUTIONS"
          title="Duration, actions and tokens"
          className="result-trials"
        >
          <div className="distributions">
            <Distribution
              title="Duration"
              unit="s"
              trials={value.trials}
              pick={(trial) => trial.duration_seconds}
            />
            <Distribution
              title="Agent actions"
              unit="actions"
              trials={value.trials}
              pick={(trial) => trial.actions}
            />
            <Distribution
              title="Model tokens"
              unit="tokens"
              trials={value.trials}
              pick={(trial) => trial.tokens}
            />
          </div>
          <p className="result-interval-note">
            Over trials that ran. {value.infrastructure_failed_pairs ?? 0}{" "}
            pair(s) with an infrastructure failure are excluded and counted
            separately, never as zero.
          </p>
        </Panel>
        <Panel
          eyebrow="05 / EVIDENCE"
          title="Trial records"
          className="result-trials"
        >
          {value.trials.length ? (
            <>
              <div className="trial-export">
                <a
                  className="button button-outline"
                  download={`evaluation-${value.id}-trials.jsonl`}
                  href={`data:application/x-ndjson;charset=utf-8,${encodeURIComponent(
                    [...value.trials]
                      .sort(
                        (a, b) =>
                          (a.challenge_id || "").localeCompare(
                            b.challenge_id || "",
                            "en",
                          ) ||
                          a.seed - b.seed ||
                          (a.side || "").localeCompare(b.side || "", "en") ||
                          a.id.localeCompare(b.id, "en"),
                      )
                      .map((trial) =>
                        JSON.stringify({ evaluation_id: value.id, ...trial }),
                      )
                      .join("\n") + "\n",
                  )}`}
                >
                  Download trial JSONL
                </a>
              </div>
              <div className="trial-results-scroll">
                <table className="trial-results" aria-label="Trial results">
                  <thead>
                    <tr>
                      {[
                        "Build / challenge",
                        "Seed",
                        "State",
                        "Outcome",
                        "Score",
                        "Cost (USD)",
                        "Duration (s)",
                        "Evidence",
                      ].map((name) => (
                        <th key={name} scope="col">
                          {name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {value.trials.map((trial) => (
                      <tr key={trial.id}>
                        <th scope="row">
                          {trial.side || "Trial"}
                          <small>{trial.challenge_id}</small>
                        </th>
                        <td>{trial.seed}</td>
                        <td>
                          <Status value={trial.state} />
                          {trial.error && (
                            <small className="trial-error">{trial.error}</small>
                          )}
                        </td>
                        <td>
                          {trial.state === "completed" && trial.passed != null
                            ? trial.passed
                              ? "Pass"
                              : "Fail"
                            : "Unavailable"}
                        </td>
                        <td>{number(trial.score)}</td>
                        <td>
                          {trial.cost_usd == null
                            ? "Not reported"
                            : number(trial.cost_usd)}
                        </td>
                        <td>{number(trial.duration_seconds)}</td>
                        <td>
                          {trial.arena_id ? (
                            <a
                              className="inline-action"
                              href={`/console/arena/${encodeURIComponent(trial.arena_id)}`}
                            >
                              Open arena ↗
                            </a>
                          ) : (
                            "No arena record"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <Empty
              title="No trial records"
              detail="Refresh to check for scheduled trials."
              action={
                <button className="button button-outline" onClick={refresh}>
                  Refresh trials
                </button>
              }
            />
          )}
        </Panel>
      </div>
    </>
  );
}
