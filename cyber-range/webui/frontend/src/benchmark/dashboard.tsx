import "./dashboard.css";
import { useEffect, useRef } from "react";
import type { EvaluationDetailData } from "../types";

// UX-11 (FR-16): evaluation dashboard pieces. Everything here renders from the
// evaluation projection; a value that was not measured is shown as such and
// never drawn as zero.

type Trial = EvaluationDetailData["trials"][number];
type Difference = EvaluationDetailData["differences"][string];

export const ACTIVE = new Set(["queued", "running"]);

export function format(value: number | null | undefined, digits = 2) {
  return value == null
    ? "—"
    : new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(
        value,
      );
}

export function intervalLabel(status: string | null | undefined) {
  return status
    ? status.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase())
    : "Unavailable";
}

/** Push-driven refresh: one refetch per `evaluation` frame that changes state
 * or progress. The stream closes itself once the evaluation is finished. */
export function useEvaluationStream(
  id: string,
  active: boolean,
  refresh: () => void,
) {
  const ref = useRef(refresh);
  ref.current = refresh;
  useEffect(() => {
    if (!active) return;
    const stream = new EventSource(
      `/api/console/evaluations/${encodeURIComponent(id)}/stream`,
    );
    let last = "";
    stream.addEventListener("evaluation", (event) => {
      const frame = JSON.parse((event as MessageEvent).data) as {
        state: string;
        progress: unknown;
      };
      const signature = JSON.stringify([frame.state, frame.progress]);
      if (last && signature !== last) ref.current();
      last = signature;
      if (!ACTIVE.has(frame.state)) {
        stream.close();
        ref.current();
      }
    });
    return () => stream.close();
  }, [id, active]);
}

const metricNames: Record<string, string> = {
  verified: "Verified findings",
  false_claims: "False claims",
  requests: "Requests",
  latency_seconds: "Latency (s)",
  cost_usd: "Cost (USD)",
};

export function metricName(name: string) {
  return metricNames[name] || name.replaceAll("_", " ");
}

/** One paired difference on its own symmetric scale around zero. A degenerate
 * interval is labelled and has no bar: zero width is not certainty. */
export function DifferencePlot({
  name,
  metric,
}: {
  name: string;
  metric: Difference;
}) {
  const width = 220;
  const height = 30;
  const mid = width / 2;
  if (metric.mean == null)
    return (
      <span className="diff-plot-empty">
        {intervalLabel(metric.interval_status)}
      </span>
    );
  const drawInterval =
    metric.bootstrap_95 != null &&
    (metric.interval_status === "supported" ||
      metric.interval_status === "insufficient_pairs");
  const extent = Math.max(
    Math.abs(metric.mean),
    ...(drawInterval && metric.bootstrap_95
      ? metric.bootstrap_95.map(Math.abs)
      : []),
    1e-9,
  );
  const x = (value: number) => mid + (value / extent) * (mid - 12);
  const label = `${metricName(name)}: mean ${format(metric.mean)}${
    drawInterval && metric.bootstrap_95
      ? `, interval ${format(metric.bootstrap_95[0])} to ${format(metric.bootstrap_95[1])}`
      : ""
  }, ${intervalLabel(metric.interval_status)}`;
  return (
    <svg
      className="diff-plot"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
    >
      <line className="diff-zero" x1={mid} x2={mid} y1={2} y2={height - 2} />
      {drawInterval && metric.bootstrap_95 && (
        <line
          className={
            metric.interval_status === "supported"
              ? "diff-interval"
              : "diff-interval diff-interval-weak"
          }
          x1={x(metric.bootstrap_95[0])}
          x2={x(metric.bootstrap_95[1])}
          y1={height / 2}
          y2={height / 2}
        />
      )}
      <circle
        className={
          metric.interval_status === "degenerate"
            ? "diff-mean diff-mean-degenerate"
            : "diff-mean"
        }
        cx={x(metric.mean)}
        cy={height / 2}
        r={5}
      />
    </svg>
  );
}

function outcome(trial: Trial | undefined) {
  if (!trial) return { key: "missing", text: "No trial" };
  if (trial.state === "infrastructure_failure")
    return { key: "infra", text: "Infrastructure failure — not scored" };
  if (trial.state === "agent_failure")
    return { key: "agent", text: "Agent failure" };
  if (trial.state !== "completed")
    return { key: "pending", text: trial.state.replaceAll("_", " ") };
  if (trial.passed == null) return { key: "unknown", text: "No verdict" };
  return trial.passed
    ? { key: "pass", text: "Pass" }
    : { key: "fail", text: "Fail" };
}

const MARKS: Record<string, string> = {
  pass: "✓",
  fail: "✕",
  infra: "⚠",
  agent: "!",
  pending: "…",
  unknown: "?",
  missing: "",
};

/** Challenge × seed × side. Each cell opens that trial's timeline; each row
 * compares the pair. An infrastructure-failed trial has no score mark. */
export function OutcomeGrid({
  evaluation,
  challengeNames,
}: {
  evaluation: EvaluationDetailData;
  challengeNames: Record<string, string>;
}) {
  const sides = ["baseline", "candidate"];
  const rows = new Map<string, Map<string, Trial>>();
  for (const trial of evaluation.trials) {
    const key = `${trial.challenge_id || ""}\u0000${trial.seed}`;
    if (!rows.has(key)) rows.set(key, new Map());
    rows.get(key)!.set(trial.side || "trial", trial);
  }
  const ordered = [...rows.entries()].sort(([a], [b]) => {
    const [ca, sa] = a.split("\u0000");
    const [cb, sb] = b.split("\u0000");
    return ca.localeCompare(cb, "en") || Number(sa) - Number(sb);
  });
  return (
    <div className="trial-results-scroll">
      <table
        className="outcome-grid"
        aria-label="Outcome by challenge, seed and side"
      >
        <thead>
          <tr>
            <th scope="col">Challenge</th>
            <th scope="col">Seed</th>
            {sides.map((side) => (
              <th scope="col" key={side}>
                {side}
              </th>
            ))}
            <th scope="col">Compare</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map(([key, cells]) => {
            const [challenge, seed] = key.split("\u0000");
            const baseline = cells.get("baseline");
            const candidate = cells.get("candidate");
            return (
              <tr key={key}>
                <th scope="row">{challengeNames[challenge] || challenge}</th>
                <td>{seed}</td>
                {sides.map((side) => {
                  const trial = cells.get(side);
                  const result = outcome(trial);
                  const mark = (
                    <>
                      <span aria-hidden="true">{MARKS[result.key]}</span>
                      <span className="visually-hidden">{result.text}</span>
                    </>
                  );
                  return (
                    <td key={side}>
                      {trial?.arena_id ? (
                        <a
                          className={`outcome-cell outcome-${result.key}`}
                          href={`/console/arena/${encodeURIComponent(trial.arena_id)}`}
                          title={`${side} seed ${seed}: ${result.text} — open timeline`}
                        >
                          {mark}
                        </a>
                      ) : (
                        <span
                          className={`outcome-cell outcome-${result.key}`}
                          title={`${side} seed ${seed}: ${result.text}`}
                        >
                          {mark}
                        </span>
                      )}
                    </td>
                  );
                })}
                <td>
                  {baseline?.arena_id && candidate?.arena_id ? (
                    <a
                      className="inline-action"
                      href={`/console/evaluations/${encodeURIComponent(evaluation.id)}/compare?a=${encodeURIComponent(baseline.id)}&b=${encodeURIComponent(candidate.id)}`}
                    >
                      Compare
                    </a>
                  ) : (
                    <small>Needs two runs</small>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="outcome-legend">
        ✓ pass · ✕ fail · ⚠ infrastructure failure (not scored) · ! agent
        failure · … in progress
      </p>
    </div>
  );
}

function quantile(sorted: number[], q: number) {
  const at = (sorted.length - 1) * q;
  const low = Math.floor(at);
  return sorted[low] + (sorted[Math.ceil(at)] - sorted[low]) * (at - low);
}

/** Strip plots per side for one per-trial measure, over trials that ran (an
 * infrastructure failure measured nothing). Unreported values are counted. */
export function Distribution({
  title,
  trials,
  pick,
  unit,
}: {
  title: string;
  trials: Trial[];
  pick: (trial: Trial) => number | null;
  unit: string;
}) {
  const ran = trials.filter(
    (trial) => trial.state === "completed" || trial.state === "agent_failure",
  );
  const bySide = ["baseline", "candidate"].map((side) => {
    const own = ran.filter((trial) => trial.side === side);
    const values = own
      .map(pick)
      .filter((value): value is number => value != null)
      .sort((a, b) => a - b);
    return { side, values, missing: own.length - values.length };
  });
  const all = bySide.flatMap((row) => row.values);
  const max = Math.max(...all, 0);
  const width = 240;
  const x = (value: number) => 8 + (max ? value / max : 0) * (width - 16);
  return (
    <div className="distribution">
      <strong>{title}</strong>
      {bySide.map(({ side, values, missing }) => (
        <div className="distribution-row" key={side}>
          <span>{side}</span>
          {values.length ? (
            <svg
              viewBox={`0 0 ${width} 22`}
              role="img"
              aria-label={`${title}, ${side}: ${values.length} trials, median ${format(quantile(values, 0.5))} ${unit}, range ${format(values[0])} to ${format(values[values.length - 1])}`}
            >
              <line
                className="distribution-axis"
                x1={8}
                x2={width - 8}
                y1={11}
                y2={11}
              />
              {values.map((value, index) => (
                <circle
                  key={index}
                  className={`distribution-dot distribution-${side}`}
                  cx={x(value)}
                  cy={11}
                  r={4}
                />
              ))}
              <line
                className="distribution-median"
                x1={x(quantile(values, 0.5))}
                x2={x(quantile(values, 0.5))}
                y1={3}
                y2={19}
              />
            </svg>
          ) : (
            <em>Not reported</em>
          )}
          <small>
            {values.length
              ? `median ${format(quantile(values, 0.5))} ${unit}`
              : ""}
            {missing ? ` · ${missing} not reported` : ""}
          </small>
        </div>
      ))}
      <small className="distribution-scale">
        Scale 0 – {format(max)} {unit}
      </small>
    </div>
  );
}
