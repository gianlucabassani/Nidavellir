import { useState } from "react";
import type { EvaluationDetailData } from "../types";
import { navigate } from "../router";
import {
  BackLink,
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

// UX-12 (FR-17): two trials side by side, aligned by step (the agent's n-th
// action), with the first divergence highlighted and findings below.

type Step = {
  index: number;
  span_id: string | null;
  name: string;
  status: string;
  input_digest: string | null;
  input_preview: string | null;
  method: string | null;
  status_code: number | null;
  transaction_digest: string | null;
  finding_id: string | null;
  duration_ms: number | null;
};
type Side = {
  id: string;
  seed: number;
  state: string;
  side: string | null;
  build_id: string | null;
  challenge_id: string | null;
  arena_id: string | null;
  passed: boolean | null;
  findings: { id: string; title: string; verdict: string }[];
};
export type TrialComparison = {
  evaluation_id: string;
  a: Side;
  b: Side;
  same_start: boolean;
  steps: {
    index: number;
    relation:
      "same" | "different_input" | "different_tool" | "only_a" | "only_b";
    a: Step | null;
    b: Step | null;
  }[];
  first_divergence: number | null;
  only_in_a: number[];
  only_in_b: number[];
  tools_only_in_a: string[];
  tools_only_in_b: string[];
};

const RELATION: Record<string, string> = {
  same: "Same call",
  different_input: "Same tool, different input",
  different_tool: "Different tool",
  only_a: "Only in A",
  only_b: "Only in B",
};
const PAGE = 400;

function sideName(side: Side) {
  return `${side.side || "trial"} · seed ${side.seed}`;
}

function verdict(side: Side) {
  if (side.state === "infrastructure_failure")
    return "Infrastructure failure — not scored";
  if (side.passed == null) return "No verdict";
  return side.passed ? "Pass" : "Fail";
}

function StepCell({ step, absent }: { step: Step | null; absent: boolean }) {
  if (!step) return <td className="compare-step compare-none">—</td>;
  return (
    <td className={`compare-step compare-status-${step.status}`}>
      <strong>{step.name}</strong>
      {step.status_code != null && <small> {step.status_code}</small>}
      {absent && (
        <span className="compare-absent">never issued by the other run</span>
      )}
      {step.input_preview && <code>{step.input_preview.slice(0, 160)}</code>}
      {step.transaction_digest && (
        <small className="compare-digest">
          tx {step.transaction_digest.slice(0, 19)}
        </small>
      )}
    </td>
  );
}

function SelectTrials({
  evaluationId,
  a,
  b,
}: {
  evaluationId: string;
  a: string;
  b: string;
}) {
  const { value } = useWorkspaceData<EvaluationDetailData>(
    `/api/console/evaluations/${encodeURIComponent(evaluationId)}`,
  );
  const [left, setLeft] = useState(a);
  const [right, setRight] = useState(b);
  const options = (value?.trials || []).filter((trial) => trial.arena_id);
  const label = (trial: EvaluationDetailData["trials"][number]) =>
    `${trial.side || "trial"} · ${value?.challenges.find((c) => c.id === trial.challenge_id)?.name || trial.challenge_id || ""} · seed ${trial.seed}`;
  return (
    <form
      className="compare-select"
      onSubmit={(event) => {
        event.preventDefault();
        navigate(
          `/console/evaluations/${encodeURIComponent(evaluationId)}/compare?a=${encodeURIComponent(left)}&b=${encodeURIComponent(right)}`,
        );
      }}
    >
      <label>
        Trial A
        <select value={left} onChange={(event) => setLeft(event.target.value)}>
          <option value="">Choose a trial</option>
          {options.map((trial) => (
            <option key={trial.id} value={trial.id}>
              {label(trial)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Trial B
        <select
          value={right}
          onChange={(event) => setRight(event.target.value)}
        >
          <option value="">Choose a trial</option>
          {options.map((trial) => (
            <option key={trial.id} value={trial.id}>
              {label(trial)}
            </option>
          ))}
        </select>
      </label>
      <button
        className="button"
        type="submit"
        disabled={!left || !right || left === right}
        aria-describedby="compare-select-reason"
      >
        Compare
      </button>
      {(!left || !right || left === right) && (
        <small id="compare-select-reason">
          {left && left === right
            ? "Choose two different trials."
            : "Choose two trials that ran in an arena."}
        </small>
      )}
    </form>
  );
}

export function TrialCompare({ evaluationId }: { evaluationId: string }) {
  const params = new URLSearchParams(window.location.search);
  const a = params.get("a") || "";
  const b = params.get("b") || "";
  const [limit, setLimit] = useState(PAGE);
  const ready = Boolean(a && b);
  const { value, error, loading, refresh } = useWorkspaceData<TrialComparison>(
    ready
      ? `/api/console/evaluations/${encodeURIComponent(evaluationId)}/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`
      : `/api/console/evaluations/${encodeURIComponent(evaluationId)}`,
  );
  const comparison = ready && value && "steps" in value ? value : null;
  const back = `/console/evaluations/${encodeURIComponent(evaluationId)}`;
  const head = (
    <>
      <div className="arena-return">
        <BackLink href={back} label="Evaluation" />
        <span>/</span>
        <span>Trial comparison</span>
      </div>
      <PageHead
        overline={`BENCHMARK / EVALUATION ${evaluationId} / COMPARE`}
        title="Trial comparison"
        subtitle="Two trials aligned by the agent's n-th action. The first step where they differ is highlighted."
        action={null}
        refresh={refresh}
      />
      <SelectTrials key={`${a}|${b}`} evaluationId={evaluationId} a={a} b={b} />
    </>
  );
  if (!ready)
    return (
      <>
        {head}
        <Empty
          title="Choose two trials"
          detail="Typically the baseline and the candidate on the same seed."
        />
      </>
    );
  if (loading && !comparison)
    return (
      <>
        {head}
        <Loading />
      </>
    );
  if (error && !comparison)
    return (
      <>
        {head}
        <ErrorState message={error} refresh={refresh} />
      </>
    );
  if (!comparison) return head;
  const absentA = new Set(comparison.only_in_a);
  const absentB = new Set(comparison.only_in_b);
  const divergence = comparison.first_divergence;
  const shown = comparison.steps.slice(
    0,
    Math.max(limit, divergence == null ? 0 : divergence + 20),
  );
  return (
    <>
      {head}
      <div className="compare-summary" role="status">
        <div>
          <small>A</small>
          <strong>{sideName(comparison.a)}</strong>
          <span>{verdict(comparison.a)}</span>
        </div>
        <div>
          <small>B</small>
          <strong>{sideName(comparison.b)}</strong>
          <span>{verdict(comparison.b)}</span>
        </div>
        <div>
          <small>FIRST DIVERGENCE</small>
          <strong>
            {divergence == null ? "None — identical" : `Step ${divergence + 1}`}
          </strong>
          {divergence != null && (
            <a className="inline-action" href={`#step-${divergence}`}>
              Jump to step
            </a>
          )}
        </div>
        <div>
          <small>STARTING STATE</small>
          <strong>
            {comparison.same_start ? "Same" : "Different or unknown"}
          </strong>
          <span>
            {comparison.same_start
              ? "Both runs began from the same observed state."
              : "Differences may come from the start, not the agent."}
          </span>
        </div>
      </div>
      {(comparison.tools_only_in_a.length > 0 ||
        comparison.tools_only_in_b.length > 0) && (
        <div className="scope-note compare-tools">
          {comparison.tools_only_in_a.length > 0 && (
            <span>
              <strong>B never called:</strong>{" "}
              {comparison.tools_only_in_a.join(", ")}
            </span>
          )}
          {comparison.tools_only_in_b.length > 0 && (
            <span>
              <strong>A never called:</strong>{" "}
              {comparison.tools_only_in_b.join(", ")}
            </span>
          )}
        </div>
      )}
      <Panel eyebrow="01 / TIMELINES" title="Aligned by step">
        {comparison.steps.length ? (
          <div className="trial-results-scroll">
            <table
              className="compare-table"
              aria-label="Trial steps side by side"
            >
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col">A — {sideName(comparison.a)}</th>
                  <th scope="col">Relation</th>
                  <th scope="col">B — {sideName(comparison.b)}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr
                    key={row.index}
                    id={`step-${row.index}`}
                    className={`compare-${row.relation}${row.index === divergence ? " compare-divergence" : ""}`}
                    aria-current={row.index === divergence ? "step" : undefined}
                  >
                    <th scope="row">
                      {row.index + 1}
                      {row.index === divergence && (
                        <span className="compare-flag">first divergence</span>
                      )}
                    </th>
                    <StepCell
                      step={row.a}
                      absent={absentA.has(row.a?.index ?? -1)}
                    />
                    <td className="compare-relation">
                      {RELATION[row.relation]}
                    </td>
                    <StepCell
                      step={row.b}
                      absent={absentB.has(row.b?.index ?? -1)}
                    />
                  </tr>
                ))}
              </tbody>
            </table>
            {shown.length < comparison.steps.length && (
              <button
                className="button button-outline"
                onClick={() => setLimit(comparison.steps.length)}
              >
                Show all {comparison.steps.length} steps
              </button>
            )}
          </div>
        ) : (
          <Empty
            title="No agent actions"
            detail="Neither trial recorded an agent tool call."
          />
        )}
      </Panel>
      <div className="compare-findings">
        {[comparison.a, comparison.b].map((side, index) => (
          <Panel
            key={side.id}
            eyebrow={`0${index + 2} / ${index ? "B" : "A"}`}
            title={`Findings — ${sideName(side)}`}
            aside={<Status value={side.state} />}
          >
            <div className="compact-list">
              <p>
                Verdict: <strong>{verdict(side)}</strong>
                {side.arena_id && (
                  <>
                    {" · "}
                    <a
                      className="inline-action"
                      href={`/console/arena/${encodeURIComponent(side.arena_id)}`}
                    >
                      Open timeline
                    </a>
                  </>
                )}
              </p>
              {side.findings.length ? (
                side.findings.map((finding) => (
                  <div className="challenge-row" key={finding.id}>
                    <strong>{finding.title || finding.id}</strong>
                    <Status value={finding.verdict} />
                  </div>
                ))
              ) : (
                <small>No findings submitted.</small>
              )}
            </div>
          </Panel>
        ))}
      </div>
    </>
  );
}
