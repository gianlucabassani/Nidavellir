import { useCallback, useEffect, useRef, useState } from "react";
import type React from "react";
import { ControlEvidenceReview } from "./finding-review";
import { EvidencePicker, useEvidenceCandidates } from "./evidence-picker";
import type { ArenaData, FindingRecord, FindingReview } from "../types";
import {
  useWorkspaceData,
  Panel,
  Empty,
  Loading,
  ErrorState,
  DisabledReason,
} from "../ui";
import { FindingList, SEVERITIES } from "../shared/finding-list";

export function FindingsWorkbench({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const { value, error, loading, refresh } = useWorkspaceData<{
    findings: FindingRecord[];
  }>(`/api/console/arenas/${id}/findings`);
  const [reviews, setReviews] = useState<Record<string, FindingReview>>({});
  const onReview = useCallback((findingId: string, review: FindingReview) => {
    setReviews((previous) => ({ ...previous, [findingId]: review }));
  }, []);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<{
    finding: FindingRecord;
    verdict: "confirmed" | "refuted";
  } | null>(null);
  const [note, setNote] = useState("");
  const [digest, setDigest] = useState("");
  const prefill = (key: string) =>
    (new URLSearchParams(window.location.search).get(key) || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  const [artifacts, setArtifacts] = useState<string[]>(() =>
    prefill("artifact"),
  );
  const [transactions, setTransactions] = useState<string[]>(() =>
    prefill("transaction"),
  );
  // UX-06: findings and evidence candidates follow the live arena stream.
  const liveKey = `${arena.events[0]?.ts || ""}:${arena.events.length}:${arena.findings.length}`;
  const candidates = useEvidenceCandidates(arena.id, liveKey);
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveKey]);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (selected && dialog.current && !dialog.current.open)
      dialog.current.showModal();
    if (!selected && dialog.current?.open) dialog.current.close();
  }, [selected]);
  async function post(path: string, body: Record<string, unknown>) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken":
          document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
            ?.content || "",
      },
      body: JSON.stringify(body),
    });
    if (response.redirected && new URL(response.url).pathname === "/login") {
      window.location.assign(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
      );
      throw new Error("Session expired");
    }
    const payload = await response.json();
    if (!response.ok)
      throw new Error(payload.error || `Action rejected (${response.status})`);
    return payload;
  }
  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setPending(true);
    setMessage("");
    try {
      await post(`/api/arenas/${id}/findings/manual`, {
        title: String(fields.get("title") || "").trim(),
        cwe: String(fields.get("cwe") || "").trim(),
        severity: String(fields.get("severity") || "") || null,
        node: String(fields.get("node") || "").trim(),
        evidence: String(fields.get("evidence") || "").trim(),
        poc: String(fields.get("poc") || "").trim(),
        evidence_artifact_digests: artifacts,
        transaction_digests: transactions,
      });
      form.reset();
      setArtifacts([]);
      setTransactions([]);
      setMessage(
        "Finding recorded. Review its evidence and verification state below.",
      );
      refresh();
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "Finding could not be recorded",
      );
    } finally {
      setPending(false);
    }
  }
  async function verify(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || pending) return;
    setPending(true);
    setMessage("");
    try {
      await post(
        `/api/arenas/${id}/findings/${encodeURIComponent(selected.finding.id)}/verify`,
        {
          verdict: selected.verdict,
          note: note.trim(),
          evidence_digest: digest.trim() || null,
        },
      );
      setMessage(
        `${selected.verdict === "confirmed" ? "Confirmation" : "Refutation"} recorded separately from independent validation.`,
      );
      setSelected(null);
      setDigest("");
      setNote("");
      refresh();
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Verification failed",
      );
    } finally {
      setPending(false);
    }
  }
  const editable = arena.state === "active";
  const findings = value?.findings || [];
  return (
    <>
      {message && (
        <p className="poc-message" role="status">
          {message}
        </p>
      )}
      <Panel
        eyebrow="Record"
        title={
          findings.length
            ? `${findings.length} finding${findings.length === 1 ? "" : "s"} in this arena`
            : "Findings in this arena"
        }
        aside={
          <button className="inline-action" type="button" onClick={refresh}>
            Refresh
          </button>
        }
      >
        <div className="findings-body">
          {loading && !value ? (
            <Loading />
          ) : error && !value ? (
            <ErrorState message={error} refresh={refresh} />
          ) : (
            <FindingList
              findings={findings}
              arenaId={arena.id}
              body={(finding) => (
                <ControlEvidenceReview
                  arenaId={arena.id}
                  findingId={finding.id}
                  onReview={onReview}
                />
              )}
              actions={(finding) =>
                editable ? (
                  <>
                    <button
                      className="button button-gold"
                      type="button"
                      onClick={() => {
                        setSelected({ finding, verdict: "confirmed" });
                        setDigest(
                          finding.artifacts[0]?.digest ||
                            finding.transactions[0]?.digest ||
                            "",
                        );
                      }}
                    >
                      Confirm with evidence
                    </button>
                    <button
                      className="button button-outline"
                      type="button"
                      onClick={() => {
                        setSelected({ finding, verdict: "refuted" });
                        setDigest("");
                      }}
                      disabled={!reviews[finding.id]?.refutation_allowed}
                      aria-describedby={
                        reviews[finding.id]?.refutation_allowed
                          ? undefined
                          : `refute-why-${finding.id}`
                      }
                    >
                      Refute
                    </button>
                    {!reviews[finding.id]?.refutation_allowed && (
                      <DisabledReason id={`refute-why-${finding.id}`}>
                        Refuting needs the control and evidence review above to
                        allow it: open the review and run its control first.
                      </DisabledReason>
                    )}
                  </>
                ) : (
                  <span className="muted">
                    Archived arena: decisions are read-only.
                  </span>
                )
              }
              empty={
                <Empty
                  title="No findings recorded"
                  detail="Agent and operator reports appear here with their proof and review state."
                />
              }
            />
          )}
        </div>
      </Panel>
      {editable ? (
        <details className="panel finding-record" open={!findings.length}>
          <summary>
            <span className="eyebrow">Report</span>
            <b>Record a finding yourself</b>
            <small>
              A report alone does not establish a confirmed vulnerability.
            </small>
          </summary>
          <form className="finding-form" onSubmit={create}>
            <p>
              Record the observed effect and a reproducible proof. A report
              alone does not establish a confirmed vulnerability.
            </p>
            <label>
              Finding title
              <input
                name="title"
                required
                maxLength={256}
                placeholder="Cross-account record access"
              />
            </label>
            <div className="finding-pair">
              <label>
                Severity
                <select name="severity" defaultValue="">
                  <option value="">Not rated</option>
                  {SEVERITIES.filter((item) => item.key !== "none").map(
                    (item) => (
                      <option key={item.key} value={item.key}>
                        {item.label}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label>
                CWE
                <input name="cwe" maxLength={32} placeholder="CWE-639" />
              </label>
              <label>
                Node
                <input name="node" maxLength={64} placeholder="grant-service" />
              </label>
            </div>
            <label>
              Observed evidence
              <textarea
                name="evidence"
                maxLength={4096}
                rows={4}
                placeholder="What changed, which identity was used, and what was returned"
              />
            </label>
            <label>
              Reproduction steps
              <textarea
                name="poc"
                maxLength={8192}
                rows={5}
                spellCheck={false}
                placeholder="Request, command or numbered steps"
              />
            </label>
            <EvidencePicker
              label="Evidence artifacts"
              candidates={candidates.value}
              kinds={["artifact"]}
              multiple
              value={artifacts}
              onChange={setArtifacts}
            />
            <EvidencePicker
              label="HTTP transactions"
              candidates={candidates.value}
              kinds={["transaction"]}
              multiple
              value={transactions}
              onChange={setTransactions}
            />
            <div className="poc-submit">
              <span>
                Attached digests must exist in this arena. The service validates
                them before recording.
              </span>
              <button className="button button-gold" disabled={pending}>
                {pending ? "Recording…" : "Record finding ↗"}
              </button>
            </div>
          </form>
        </details>
      ) : (
        <Empty
          title="Retained finding record"
          detail="This arena is archived and its findings remain readable."
        />
      )}
      <dialog
        ref={dialog}
        className="gate-dialog"
        onClose={() => setSelected(null)}
        onCancel={(event) => {
          if (pending) event.preventDefault();
        }}
      >
        <form onSubmit={verify} className="verify-form">
          <span className="eyebrow">OPERATOR VERDICT</span>
          <h2>
            {selected?.verdict === "confirmed" ? "Confirm" : "Refute"}{" "}
            {selected?.finding.title}?
          </h2>
          <p>
            {selected?.verdict === "confirmed"
              ? "Pick the immutable record from this arena that proves it. Manual confirmation stays separate from independent validation."
              : "Record why this finding is refuted. The service keeps the decision in the audit trail."}
          </p>
          {selected?.verdict === "confirmed" && (
            <EvidencePicker
              label="Evidence"
              candidates={candidates.value}
              kinds={["transaction", "artifact"]}
              multiple={false}
              value={digest ? [digest] : []}
              onChange={(next) => setDigest(next[0] || "")}
            />
          )}
          <label>
            Decision note
            <textarea
              maxLength={1024}
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          <div>
            <button
              type="button"
              className="button button-outline"
              disabled={pending}
              onClick={() => setSelected(null)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button-gold"
              disabled={
                pending || (selected?.verdict === "confirmed" && !digest)
              }
              aria-describedby={
                selected?.verdict === "confirmed" && !digest
                  ? "confirm-evidence-why"
                  : undefined
              }
            >
              {pending ? "Saving…" : `Record ${selected?.verdict}`}
            </button>
          </div>
          {selected?.verdict === "confirmed" && !digest && (
            <DisabledReason id="confirm-evidence-why">
              Pick the evidence above (or paste its digest) to record a
              confirmation.
            </DisabledReason>
          )}
        </form>
      </dialog>
    </>
  );
}
