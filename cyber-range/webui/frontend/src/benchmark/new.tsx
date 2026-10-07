import { useState } from "react";
import type React from "react";
import type { BenchmarkData } from "../types";
import { paths } from "../types";
import { useWorkspaceData, Panel, PageHead, Loading, ErrorState } from "../ui";

export function NewComparison() {
  const { value, error, loading, refresh } = useWorkspaceData<BenchmarkData>(
    paths.benchmark,
  );
  const [suiteId, setSuiteId] = useState("");
  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [pending, setPending] = useState(false);
  const [submitError, setSubmitError] = useState("");
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const ready = value.suites.length > 0 && value.builds.length > 1;
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || !suiteId || !baselineId || !candidateId) return;
    if (baselineId === candidateId) {
      setSubmitError("Choose two different pinned builds.");
      return;
    }
    setSubmitError("");
    setPending(true);
    try {
      const response = await fetch("/api/console/evaluations", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-CSRFToken":
            document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
              ?.content || "",
        },
        body: JSON.stringify({
          suite_id: suiteId,
          baseline_id: baselineId,
          candidate_id: candidateId,
        }),
      });
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname)}`,
        );
        return;
      }
      const payload: { id?: string; error?: string } = await response.json();
      if (!response.ok || !payload.id)
        throw new Error(
          payload.error || `Evaluation could not start (${response.status})`,
        );
      window.location.assign(
        `/console/evaluations/${encodeURIComponent(payload.id)}`,
      );
    } catch (reason) {
      setSubmitError(
        reason instanceof Error ? reason.message : "Evaluation could not start",
      );
      setPending(false);
    }
  }
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=benchmark">← Benchmark</a>
        <span>/</span>
        <span>New comparison</span>
      </div>
      <PageHead
        overline="BENCHMARK / NEW COMPARISON"
        title="Configure matched trials"
        subtitle="Choose two pinned builds and one versioned suite."
        observed={value.observed_at}
        action={
          <a
            className="button button-outline"
            href="/console/benchmark/registry"
          >
            Manage registry ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="scope-note">
        <strong>Calibration scope</strong>
        <span>
          The current durable driver executes scripted MCP plans. The suite
          fixes challenges, seeds and trial limits.
        </span>
      </div>
      <div className="comparison-form-grid">
        <form className="panel comparison-form" onSubmit={submit}>
          <div className="panel-head">
            <div>
              <span className="eyebrow">01 / SELECT</span>
              <h2>Comparison setup</h2>
            </div>
          </div>
          <div className="comparison-fields">
            <label>
              Versioned suite
              <select
                required
                value={suiteId}
                onChange={(event) => setSuiteId(event.target.value)}
              >
                <option value="">Choose a suite</option>
                {value.suites.map((suite) => (
                  <option value={suite.id} key={suite.id}>
                    {suite.name} · {suite.version} · {suite.challenge_count}{" "}
                    challenges · {suite.seed_count} seeds
                  </option>
                ))}
              </select>
            </label>
            <label>
              Baseline build
              <select
                required
                value={baselineId}
                onChange={(event) => setBaselineId(event.target.value)}
              >
                <option value="">Choose a build</option>
                {value.builds.map((build) => (
                  <option value={build.id} key={build.id}>
                    {build.name} · {build.version} · {build.driver}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Candidate build
              <select
                required
                value={candidateId}
                onChange={(event) => setCandidateId(event.target.value)}
              >
                <option value="">Choose a build</option>
                {value.builds.map((build) => (
                  <option value={build.id} key={build.id}>
                    {build.name} · {build.version} · {build.driver}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {submitError && (
            <div className="form-error" role="alert">
              {submitError}
            </div>
          )}
          <div className="comparison-form-foot">
            <span>
              {ready
                ? "The orchestrator validates identities, reset eligibility and limits before scheduling."
                : "Register at least two builds and one suite first."}
            </span>
            <button
              className="button button-gold"
              type="submit"
              disabled={!ready || pending}
            >
              {pending ? "Starting…" : "Launch evaluation ↗"}
            </button>
          </div>
        </form>
        <Panel
          eyebrow="02 / CONDITIONS"
          title="Pinned material"
          className="comparison-help"
        >
          <div className="material-count">
            <strong>{value.builds.length}</strong>
            <span>registered builds</span>
          </div>
          <div className="material-count">
            <strong>{value.suites.length}</strong>
            <span>versioned suites</span>
          </div>
          <p>
            Trials are paired on equivalent starting states. Infrastructure
            failures remain separate from agent outcomes.
          </p>
          <div className="panel-foot">
            <a
              className="inline-action"
              href="/console/benchmark/registry?kind=builds"
            >
              Register material ↗
            </a>
          </div>
        </Panel>
      </div>
    </>
  );
}
