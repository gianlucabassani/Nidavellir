import { useEffect, useState } from "react";
import type { FindingReview } from "../types";
import { ErrorState, Loading, Status, useWorkspaceData } from "../ui";

function RecordData({ value }: { value: Record<string, unknown> }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

type ReviewProps = {
  arenaId: string;
  findingId: string;
  onReview: (id: string, review: FindingReview) => void;
};

function ReviewContents({ arenaId, findingId, onReview }: ReviewProps) {
  const arena = encodeURIComponent(arenaId);
  const { value, error, loading, refresh } = useWorkspaceData<FindingReview>(
    `/api/console/arenas/${arena}/findings/${encodeURIComponent(findingId)}/review`,
  );
  useEffect(() => {
    if (value) onReview(findingId, value);
  }, [value, findingId, onReview]);
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (loading || !value) return <Loading />;
  const evidenceLink = (digest: string, type = "validation-evidence") =>
    `/api/arenas/${arena}/${type}/${encodeURIComponent(digest)}`;
  return (
    <div className="control-evidence-review">
      <div className="finding-title">
        <strong>Independent result</strong>
        <Status value={value.verdict} />
      </div>
      <p>{value.reason_code || "No independent conclusion recorded"}</p>
      {value.verdict !== value.recorded_verdict && value.recorded_verdict && (
        <p>
          Historical verdict: {value.recorded_verdict}. The retained evidence
          does not support that conclusion in this review.
        </p>
      )}
      {value.unresolved.length > 0 && (
        <div className="review-unresolved" role="note">
          <strong>Unresolved evidence</strong>
          <ul>
            {value.unresolved.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      <section aria-label="Actor request and response">
        <h4>Actor request and response</h4>
        {value.actor ? (
          <>
            <p>Actor: {value.actor.identity || "Identity not retained"}</p>
            <h5>Request</h5>
            <RecordData value={value.actor.request} />
            <h5>Response</h5>
            <RecordData value={value.actor.response} />
            <p>
              Header values are withheld from this review. Bodies are retained
              target content; capture truncation is shown in the response.
            </p>
            <a href={evidenceLink(value.actor.digest, "http/transactions")}>
              Stored actor transaction · {value.actor.digest}
            </a>
          </>
        ) : (
          <p>Unresolved: no readable linked actor transaction.</p>
        )}
      </section>
      <section aria-label="Prerequisite controls">
        <h4>Prerequisite controls</h4>
        {value.controls.map((control, index) => (
          <div className="review-control" key={`${control.name}-${index}`}>
            <div className="finding-title">
              <strong>{control.name}</strong>
              <Status value={control.state} />
            </div>
            {control.request && (
              <>
                <h5>Control request</h5>
                <RecordData value={control.request} />
              </>
            )}
            <h5>Expected</h5>
            <RecordData value={control.expected} />
            <h5>Observed</h5>
            {control.observed ? (
              <RecordData value={control.observed} />
            ) : (
              <p>Unresolved: observation unavailable.</p>
            )}
          </div>
        ))}
        {value.control_digest && (
          <a href={evidenceLink(value.control_digest)}>
            Stored control evidence · {value.control_digest}
          </a>
        )}
        {!value.can_refute && (
          <p>
            A refutation requires passed prerequisites and resolved actor/effect
            evidence.
          </p>
        )}
      </section>
      <section aria-label="Observed effects">
        <h4>Observed effects</h4>
        {value.effect ? (
          <>
            <RecordData value={value.effect.data} />
            <a href={evidenceLink(value.effect.digest)}>
              Stored effect evidence · {value.effect.digest}
            </a>
          </>
        ) : (
          <p>Unresolved: no readable supported effect observation.</p>
        )}
      </section>
      <details>
        <summary>Validation identity</summary>
        <RecordData
          value={{
            validator: value.validator_id,
            version: value.validator_version,
            recipe: value.recipe_digest,
            target: value.target_identity_digest,
          }}
        />
      </details>
      <p>
        Operator judgments are recorded separately. Review reads retained
        evidence and does not execute probes.
      </p>
    </div>
  );
}

export function ControlEvidenceReview(props: ReviewProps) {
  const [opened, setOpened] = useState(false);
  return (
    <details
      className="finding-review"
      onToggle={(event) => setOpened(event.currentTarget.open)}
    >
      <summary>Review controls and evidence</summary>
      {opened && <ReviewContents {...props} />}
    </details>
  );
}
