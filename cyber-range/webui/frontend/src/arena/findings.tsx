import { useEffect, useRef, useState } from "react";
import type React from "react";
import type { ArenaData, FindingRecord } from "../types";
import {
  useWorkspaceData,
  Status,
  Panel,
  Empty,
  Loading,
  ErrorState,
} from "../ui";

export function FindingsWorkbench({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const { value, error, loading, refresh } = useWorkspaceData<{
    findings: FindingRecord[];
  }>(`/api/console/arenas/${id}/findings`);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<{
    finding: FindingRecord;
    verdict: "confirmed" | "refuted";
  } | null>(null);
  const [note, setNote] = useState("");
  const [digest, setDigest] = useState("");
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
        node: String(fields.get("node") || "").trim(),
        evidence: String(fields.get("evidence") || "").trim(),
        poc: String(fields.get("poc") || "").trim(),
        evidence_artifact_digests: String(fields.get("artifacts") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        transaction_digests: String(fields.get("transactions") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      form.reset();
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
  return (
    <>
      <div className="findings-grid">
        <Panel eyebrow="01 / REPORT" title="Record an observation">
          {editable ? (
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
                  CWE
                  <input name="cwe" maxLength={32} placeholder="CWE-639" />
                </label>
                <label>
                  Node
                  <input
                    name="node"
                    maxLength={64}
                    placeholder="grant-service"
                  />
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
              <label>
                Evidence artifact digests
                <input
                  name="artifacts"
                  defaultValue={
                    new URLSearchParams(window.location.search).get(
                      "artifact",
                    ) || ""
                  }
                  placeholder="sha256:… (comma-separated)"
                />
              </label>
              <label>
                HTTP transaction digests
                <input
                  name="transactions"
                  defaultValue={
                    new URLSearchParams(window.location.search).get(
                      "transaction",
                    ) || ""
                  }
                  placeholder="sha256:… (comma-separated)"
                />
              </label>
              <div className="poc-submit">
                <span>
                  Attached digests must exist in this arena. The service
                  validates them before recording.
                </span>
                <button className="button button-gold" disabled={pending}>
                  {pending ? "Recording…" : "Record finding ↗"}
                </button>
              </div>
            </form>
          ) : (
            <Empty
              title="Retained finding record"
              detail="This arena is archived and its findings remain readable."
            />
          )}
        </Panel>
        <Panel
          eyebrow="02 / REVIEW"
          title="Findings"
          aside={
            <button className="subtle-link" type="button" onClick={refresh}>
              Refresh ↻
            </button>
          }
        >
          {message && (
            <p className="poc-message" role="status">
              {message}
            </p>
          )}
          {loading && !value ? (
            <Loading />
          ) : error ? (
            <ErrorState message={error} refresh={refresh} />
          ) : value?.findings.length ? (
            <div className="finding-list">
              {value.findings.map((finding) => (
                <article className="finding-card" key={finding.id}>
                  <div className="finding-title">
                    <div>
                      <strong>{finding.title}</strong>
                      <small>
                        {finding.source} · {finding.node || "node unspecified"}{" "}
                        · {finding.cwe || "CWE unspecified"}
                      </small>
                    </div>
                    <Status value={finding.verdict} />
                  </div>
                  {finding.evidence && <p>{finding.evidence}</p>}
                  {finding.poc && (
                    <details>
                      <summary>Reproduction steps</summary>
                      <pre>{finding.poc}</pre>
                    </details>
                  )}
                  {finding.validation_reason && (
                    <small>
                      Independent validation: {finding.validation_reason}
                    </small>
                  )}
                  {finding.manual_verdict && (
                    <small>Operator verdict: {finding.manual_verdict}</small>
                  )}
                  {finding.artifacts.map((artifact) => (
                    <a
                      key={artifact.digest}
                      href={`/api/arenas/${id}/evidence-artifacts/${encodeURIComponent(artifact.digest)}`}
                    >
                      Artifact {artifact.digest.slice(-12)} · {artifact.bytes}{" "}
                      bytes ↗
                    </a>
                  ))}
                  {finding.transactions.map((transaction) => (
                    <a
                      key={transaction.digest}
                      href={`/console/arena/${id}?tab=http&digest=${encodeURIComponent(transaction.digest)}`}
                    >
                      {transaction.method} {transaction.path} →{" "}
                      {transaction.status} · {transaction.digest.slice(-12)} ↗
                    </a>
                  ))}
                  {editable && (
                    <div className="finding-actions">
                      <button
                        className="button button-outline"
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
                      >
                        Refute
                      </button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="No findings recorded"
              detail="Agent and operator reports will appear here with their proof and review state."
            />
          )}
        </Panel>
      </div>
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
              ? "Choose an immutable evidence digest from this arena. Manual confirmation stays separate from independent validation."
              : "Record why this finding is refuted. The service keeps the decision in the audit trail."}
          </p>
          {selected?.verdict === "confirmed" && (
            <label>
              Evidence digest
              <input
                required
                value={digest}
                onChange={(event) => setDigest(event.target.value)}
                placeholder="sha256:…"
              />
            </label>
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
              disabled={pending}
            >
              {pending ? "Saving…" : `Record ${selected?.verdict}`}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
