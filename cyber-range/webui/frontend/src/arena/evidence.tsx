import type { ArenaData, EvidenceData } from "../types";
import {
  useWorkspaceData,
  Status,
  formatObserved,
  Panel,
  Empty,
  Loading,
  ErrorState,
} from "../ui";

export function EvidenceWorkbench({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const { value, error, loading, refresh } = useWorkspaceData<EvidenceData>(
    `/api/console/arenas/${id}/evidence`,
  );
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const total =
    value.artifacts.length +
    value.validations.length +
    value.transactions.length +
    value.signals.length;
  return (
    <div className="evidence-work-grid">
      <Panel
        eyebrow="01 / RECORD"
        title="Evidence inventory"
        className="evidence-summary"
        aside={
          <button className="subtle-link" type="button" onClick={refresh}>
            Refresh ↻
          </button>
        }
      >
        <p className="evidence-intro">
          Proof attached to findings and independent checks in this arena.
          Records remain reviewable after teardown.
        </p>
        <div className="evidence-counts">
          <div>
            <strong>{value.artifacts.length}</strong>
            <span>Artifacts</span>
          </div>
          <div>
            <strong>{value.validations.length}</strong>
            <span>Validation traces</span>
          </div>
          <div>
            <strong>{value.transactions.length}</strong>
            <span>HTTP references</span>
          </div>
          <div>
            <strong>{value.signals.length}</strong>
            <span>Monitor signals</span>
          </div>
        </div>
        <div className="panel-foot">
          <span>Observed {formatObserved(value.observed_at)}</span>
          <a
            className="inline-action"
            href={`/console/arena/${id}?tab=findings`}
          >
            Review findings ↗
          </a>
        </div>
      </Panel>
      <Panel
        eyebrow="02 / PROOF"
        title="Attached artifacts"
        className="evidence-artifacts"
      >
        {value.artifacts.length ? (
          <div className="evidence-record-list">
            {value.artifacts.map((item, index) => (
              <a
                className="evidence-record"
                href={`/api/arenas/${id}/evidence-artifacts/${encodeURIComponent(item.digest)}`}
                key={`${item.finding_id}-${item.digest}-${index}`}
              >
                <span className="evidence-record-icon" aria-hidden="true">
                  ▣
                </span>
                <span>
                  <strong>{item.finding_title}</strong>
                  <small>
                    {item.digest} · {item.bytes} bytes
                  </small>
                </span>
                <b aria-hidden="true">↗</b>
              </a>
            ))}
          </div>
        ) : (
          <Empty
            title="No attached artifacts"
            detail={
              total
                ? "Findings have other evidence types."
                : "Evidence appears here after a finding or validation is recorded."
            }
          />
        )}
      </Panel>
      <Panel
        eyebrow="03 / VALIDATION"
        title="Independent checks"
        className="evidence-validations"
      >
        {value.validations.length ? (
          <div className="evidence-record-list">
            {value.validations.map((item, index) => (
              <a
                className="evidence-record"
                href={`/api/arenas/${id}/validation-evidence/${encodeURIComponent(item.digest)}`}
                key={`${item.finding_id}-${item.kind}-${index}`}
              >
                <span className="evidence-record-icon" aria-hidden="true">
                  ◇
                </span>
                <span>
                  <strong>{item.finding_title}</strong>
                  <small>
                    {item.kind === "effect" ? "Observed effect" : "Control run"}{" "}
                    · {item.digest}
                  </small>
                </span>
                <b aria-hidden="true">↗</b>
              </a>
            ))}
          </div>
        ) : (
          <Empty
            title="No validation traces"
            detail="Independent effect and control records will appear when a finding is checked."
          />
        )}
      </Panel>
      <Panel
        eyebrow="04 / TRAFFIC"
        title="Attached HTTP transactions"
        className="evidence-transactions"
      >
        {value.transactions.length ? (
          <div className="evidence-record-list">
            {value.transactions.map((item, index) => (
              <a
                className="evidence-record"
                href={`/console/arena/${id}?tab=http&digest=${encodeURIComponent(item.digest)}`}
                key={`${item.finding_id}-${item.digest}-${index}`}
              >
                <span className="evidence-record-icon" aria-hidden="true">
                  ⇄
                </span>
                <span>
                  <strong>
                    {item.method} {item.path} <em>→ {item.status}</em>
                  </strong>
                  <small>
                    {item.finding_title} · {item.digest}
                  </small>
                </span>
                <b aria-hidden="true">↗</b>
              </a>
            ))}
          </div>
        ) : (
          <Empty
            title="No attached transactions"
            detail="Capture and attach an HTTP transaction from the arena workbench."
          />
        )}
      </Panel>
      <Panel
        eyebrow="05 / TELEMETRY"
        title="Monitor signals"
        className="evidence-signals"
      >
        {value.signals.length ? (
          <div className="evidence-signal-list">
            {value.signals.map((item, index) => (
              <div key={`${item.ts}-${index}`}>
                <span>
                  <Status value={item.severity || "observed"} />{" "}
                  <small>
                    {item.ts ? formatObserved(item.ts) : "Time unknown"}
                  </small>
                </span>
                <strong>{item.summary || item.kind || "Monitor signal"}</strong>
                <small>
                  {item.node || "Arena"}
                  {item.kind ? ` · ${item.kind}` : ""}
                </small>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="No monitor signals"
            detail="Observed telemetry will appear here when the arena reports it."
          />
        )}
      </Panel>
    </div>
  );
}
