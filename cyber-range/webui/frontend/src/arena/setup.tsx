import { useState } from "react";
import { postJson } from "../api";
import type { ArenaData } from "../types";
import {
  ConfirmDialog,
  Empty,
  ErrorState,
  Loading,
  Panel,
  Status,
  useWorkspaceData,
  formatObserved,
} from "../ui";

type SetupProposal = {
  step_id: string;
  node: string;
  command: string;
  rationale?: string;
};
type SetupState = {
  steps?: {
    node: string;
    command: string;
    stdout: string;
    stderr: string;
    exit_code: number | null;
    ok: boolean;
    via: string;
    ts: string;
  }[];
  open: boolean;
  finished?: boolean;
  planned?: {
    mode?: string;
    time_box_seconds?: number;
    command_budget?: number;
    setup_egress?: boolean;
  } | null;
  expired?: boolean;
  mode?: string;
  nodes?: string[];
  connect?: Record<string, string>;
  steps_run?: number;
  command_budget?: number;
  egress_enforced?: boolean;
  pending_proposals?: SetupProposal[];
};

export function SetupWorkbench({
  arena,
  compactFlow = false,
}: {
  arena: ArenaData;
  compactFlow?: boolean;
}) {
  const id = encodeURIComponent(arena.id);
  const { value, error, loading, refresh } = useWorkspaceData<SetupState>(
    `/api/console/arenas/${id}/setup`,
  );
  const [mode, setMode] = useState<string | null>(null);
  const [confirmFinish, setConfirmFinish] = useState(false);
  const [seconds, setSeconds] = useState<number | null>(null);
  const [budget, setBudget] = useState<number | null>(null);
  const [egress, setEgress] = useState<boolean | null>(null);
  const [node, setNode] = useState("");
  const [command, setCommand] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [result, setResult] = useState("");
  const active = arena.state === "active";
  async function run(path: string, body?: unknown) {
    if (pending) return;
    setPending(true);
    setFailure("");
    setMessage("");
    try {
      const data = await postJson<Record<string, unknown>>(path, body);
      setResult(JSON.stringify(data, null, 2));
      setMessage("The service accepted the setup action. State refreshed.");
      refresh();
    } catch (reason) {
      setFailure(
        reason instanceof Error ? reason.message : "Setup action failed",
      );
    } finally {
      setPending(false);
    }
  }
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const canEdit = active && value.open && !value.expired;
  const showSteps = !compactFlow || (active && value.open && !value.finished);
  const planned = value.planned;
  const nodes = value.nodes || [];
  const endpoint = `/api/setup/${id}`;
  return (
    <div
      className={`setup-grid${compactFlow && !showSteps ? " setup-single" : ""}`}
    >
      <Panel
        eyebrow="01 / CONFIGURATION"
        title="Target setup"
        aside={
          <Status
            value={value.open ? (value.expired ? "expired" : "open") : "closed"}
          />
        }
      >
        <p className="scenario-description">
          Bring the software under test up in its disposable setup phase.
          Commands and proposals remain bounded by the service.
        </p>
        <div className="arena-detail-list">
          <div>
            <span>Driver</span>
            <strong>{value.mode || "Not started"}</strong>
          </div>
          <div>
            <span>Steps used</span>
            <strong>
              {value.steps_run ?? 0} / {value.command_budget ?? "—"}
            </strong>
          </div>
          <div>
            <span>Setup egress</span>
            <strong>{value.egress_enforced ? "Open" : "Closed"}</strong>
          </div>
        </div>
        {Object.keys(value.connect || {}).length > 0 && (
          <div className="setup-connect">
            <strong>Connection details</strong>
            {Object.entries(value.connect || {}).map(([name, detail]) => (
              <div key={name}>
                <span>{name}</span>
                <code>{detail}</code>
              </div>
            ))}
          </div>
        )}
        {!value.open && active && !value.finished && (
          <form
            className="setup-form"
            onSubmit={(event) => {
              event.preventDefault();
              void run(`${endpoint}/start`, {
                mode: mode ?? planned?.mode ?? "operator",
                time_box_seconds: seconds ?? planned?.time_box_seconds ?? 1800,
                command_budget: budget ?? planned?.command_budget ?? 50,
                setup_egress: egress ?? planned?.setup_egress ?? false,
              });
            }}
          >
            <label>
              Driver
              <select
                value={mode ?? planned?.mode ?? "operator"}
                onChange={(event) => setMode(event.target.value)}
              >
                <option value="operator">Operator commands</option>
                <option value="hitl">Agent proposals with approval</option>
              </select>
            </label>
            <label>
              Time box (seconds)
              <input
                type="number"
                min={60}
                max={21600}
                required
                value={seconds ?? planned?.time_box_seconds ?? 1800}
                onChange={(event) => setSeconds(Number(event.target.value))}
              />
            </label>
            <label>
              Command budget
              <input
                type="number"
                min={1}
                max={500}
                required
                value={budget ?? planned?.command_budget ?? 50}
                onChange={(event) => setBudget(Number(event.target.value))}
              />
            </label>
            <label className="form-check">
              <input
                type="checkbox"
                checked={egress ?? planned?.setup_egress ?? false}
                onChange={(event) => setEgress(event.target.checked)}
              />{" "}
              Allow dependency downloads during setup
            </label>
            <button className="button button-gold" disabled={pending}>
              Start setup ↗
            </button>
          </form>
        )}
        {value.finished && (
          <Empty
            title="Setup complete"
            detail="The configuration phase is closed. Review its recorded steps in the audit trail."
          />
        )}
        {!active && !value.finished && (
          <Empty
            title="Read-only setup record"
            detail="Configuration actions are available only while this arena is active."
          />
        )}
        {compactFlow && value.finished && (
          <div className="panel-foot">
            <span>Setup history is retained in the event trace.</span>
            <a
              className="inline-action"
              href={`/console/arena/${encodeURIComponent(id)}`}
            >
              {active ? "Continue research" : "View arena record"} ↗
            </a>
          </div>
        )}
        {canEdit && (
          <button
            className="button button-danger setup-finish"
            disabled={pending}
            onClick={() => setConfirmFinish(true)}
          >
            Finish setup
          </button>
        )}
        {confirmFinish && (
          <ConfirmDialog
            title={`Finish setup for ${arena.name}?`}
            body="This closes the configuration phase. Setup history stays in the event trace."
            confirmLabel="Finish setup"
            danger
            onCancel={() => setConfirmFinish(false)}
            onConfirm={() => {
              setConfirmFinish(false);
              void run(`${endpoint}/finish`, {});
            }}
          />
        )}
        {message && (
          <p className="gate-message" role="status">
            {message}
          </p>
        )}
        {failure && (
          <p className="form-error" role="alert">
            {failure}
          </p>
        )}
      </Panel>
      {showSteps && (
        <Panel
          eyebrow="02 / STEPS"
          title={
            value.mode === "hitl" ? "Review proposals" : "Run a setup step"
          }
        >
          {value.finished ? (
            <Empty
              title="Setup steps retained"
              detail="The configuration phase is complete. Its recorded steps remain in the audit trail."
            />
          ) : !value.open ? (
            <Empty
              title="Setup has not started"
              detail="Start a bounded setup session to configure the target."
            />
          ) : value.expired ? (
            <Empty
              title="Setup expired"
              detail="The setup time box has ended. Refresh to inspect the recorded state."
            />
          ) : value.mode === "operator" ? (
            <form
              className="setup-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (!command.trim()) return;
                void run(`${endpoint}/step`, {
                  node: node || nodes[0],
                  command: command.trim(),
                });
              }}
            >
              <label>
                Target node
                <select
                  value={node || nodes[0] || ""}
                  onChange={(event) => setNode(event.target.value)}
                >
                  {nodes.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Command
                <input
                  value={command}
                  required
                  maxLength={8192}
                  onChange={(event) => setCommand(event.target.value)}
                  placeholder="Command inside the setup node"
                />
              </label>
              <button
                className="button button-gold"
                disabled={!canEdit || pending || nodes.length === 0}
              >
                Run step ↗
              </button>
            </form>
          ) : value.mode === "hitl" ? (
            <>
              <button
                className="button button-outline"
                disabled={!canEdit || pending}
                onClick={() => void run(`${endpoint}/generate-proposals`, {})}
              >
                Generate proposals ↗
              </button>
              <div className="setup-proposals">
                {(value.pending_proposals || []).length ? (
                  value.pending_proposals!.map((proposal) => (
                    <div key={proposal.step_id}>
                      <small>{proposal.node}</small>
                      <code>{proposal.command}</code>
                      {proposal.rationale && <p>{proposal.rationale}</p>}
                      <div className="settings-model-actions">
                        <button
                          className="button button-gold"
                          disabled={!canEdit || pending}
                          onClick={() =>
                            void run(
                              `${endpoint}/proposals/${encodeURIComponent(proposal.step_id)}/approve`,
                              {},
                            )
                          }
                        >
                          Approve
                        </button>
                        <button
                          className="button button-outline"
                          disabled={!canEdit || pending}
                          onClick={() =>
                            void run(
                              `${endpoint}/proposals/${encodeURIComponent(proposal.step_id)}/reject`,
                              {},
                            )
                          }
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ))
                ) : (
                  <Empty
                    title="No pending proposals"
                    detail="Generate steps with the connected model or wait for a configurator agent."
                  />
                )}
              </div>
            </>
          ) : (
            <Empty
              title="Agent-controlled setup"
              detail="An authorized configurator agent can run its steps through the scoped gateway. Review the audit trail for each action."
            />
          )}
          {result && (
            <div className="setup-result">
              <small>LAST SERVICE RESPONSE</small>
              <pre>{result}</pre>
            </div>
          )}
        </Panel>
      )}
      <Panel
        eyebrow="03 / RECORD"
        title="Setup command history"
        className="setup-history"
      >
        {(value.steps || []).length ? (
          value.steps!.map((step, index) => (
            <article className="setup-history-step" key={`${step.ts}-${index}`}>
              <div>
                <Status value={step.ok ? "succeeded" : "failed"} />{" "}
                <strong>{step.node}</strong> · exit{" "}
                {step.exit_code ?? "unknown"} · {formatObserved(step.ts)}
              </div>
              <pre aria-label="Setup command">{step.command}</pre>
              {step.stdout && (
                <pre aria-label="Standard output">{step.stdout}</pre>
              )}
              {step.stderr && (
                <pre className="form-error" aria-label="Standard error">
                  {step.stderr}
                </pre>
              )}
            </article>
          ))
        ) : (
          <Empty
            title="No recorded setup commands"
            detail="Executed commands and their bounded output remain here after setup and arena teardown."
          />
        )}
      </Panel>
    </div>
  );
}
