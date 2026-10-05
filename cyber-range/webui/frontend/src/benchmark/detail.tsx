import { useEffect, useRef } from "react";
import type { EvaluationDetailData } from "../types";
import {
  useWorkspaceData,
  Status,
  Panel,
  Empty,
  PageHead,
  Loading,
  ErrorState,
} from "../ui";

const metricNames: Record<string, string> = {
  verified: "Verified findings",
  false_claims: "False claims",
  requests: "Requests",
  latency_seconds: "Latency (s)",
  cost_usd: "Cost (USD)",
};

function number(value: number | null | undefined) {
  return value == null
    ? "—"
    : new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(value);
}

function interval(status: string | null | undefined) {
  return status
    ? status.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase())
    : "Unavailable";
}

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
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    if (value?.state !== "queued" && value?.state !== "running") return;
    const check = () => {
      if (document.visibilityState === "visible") refreshRef.current();
    };
    const timer = window.setInterval(check, 8000);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, [value?.state]);
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const metrics = Object.entries(value.differences);
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=benchmark">← Benchmark</a>
        <span>/</span>
        <span>Evaluation {value.id.slice(0, 8)}</span>
      </div>
      <PageHead
        overline={`BENCHMARK / EVALUATION ${value.id.slice(0, 8)}`}
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
              {value.progress.running} running · Results refresh while this page
              is open.
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
              </div>
              {metrics.map(([name, metric]) => (
                <div className="result-table-row" key={name}>
                  <strong>
                    {metricNames[name] || name.replaceAll("_", " ")}
                  </strong>
                  <span>{number(metric.mean)}</span>
                  <span>{metric.pairs ?? "—"}</span>
                  <span>
                    {metric.bootstrap_95
                      ? `${number(metric.bootstrap_95[0])} to ${number(metric.bootstrap_95[1])}`
                      : "Unavailable"}
                  </span>
                  <span>{interval(metric.interval_status)}</span>
                </div>
              ))}
              <p className="result-interval-note">
                A constant paired difference is degenerate; it does not
                establish a variability interval.
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
          eyebrow="03 / EVIDENCE"
          title="Trial records"
          className="result-trials"
        >
          {value.trials.length ? (
            <div className="trial-list">
              {value.trials.map((trial) => (
                <div className="trial-row" key={trial.id}>
                  <span>
                    <strong>{trial.side || "Trial"}</strong> · Seed {trial.seed}
                    {trial.challenge_id && <small>{trial.challenge_id}</small>}
                  </span>
                  <Status value={trial.state} />
                  {trial.arena_id ? (
                    <a
                      className="inline-action"
                      href={`/console/arena/${encodeURIComponent(trial.arena_id)}`}
                    >
                      Open arena ↗
                    </a>
                  ) : (
                    <span className="unavailable-link">No arena record</span>
                  )}
                  {trial.error && (
                    <small className="trial-error">{trial.error}</small>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="No trial records"
              detail="Run and trial evidence will appear here when scheduled."
            />
          )}
        </Panel>
      </div>
    </>
  );
}
