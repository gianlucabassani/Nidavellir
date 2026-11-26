// UX-24: a finding as a report you can send. The report is assembled by the
// console from the finding, its hypothesis and evidence, plus your write-up
// for what only you can say (impact, remediation, affected product). Every
// section says where its text came from; the readiness list names each gap.
// Copy it as Markdown or as a CVE request, or download the .md file.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { getJson, postJson } from "../api";
import type {
  FindingReport,
  ReportFact,
  ReportOrigin,
  ReportSection,
  Writeup,
  WriteupReference,
} from "../types";
import { Icon } from "../shell/icons";
import { formatObserved } from "../ui";
import "./finding-report.css";

const FACTS: [string, string][] = [
  ["severity", "Severity"],
  ["cwe", "Weakness"],
  ["vendor", "Vendor"],
  ["product", "Product"],
  ["affected_versions", "Affected versions"],
  ["fixed_versions", "Fixed versions"],
  ["component", "Component"],
  ["attack_type", "Attack type"],
  ["impact_type", "Impact type"],
  ["cvss_vector", "CVSS 3.1"],
  ["discoverer", "Discovered by"],
  ["station", "Station"],
];
const LABELS: Record<string, string> = {
  remote: "Remote",
  adjacent: "Adjacent network",
  local: "Local",
  physical: "Physical",
  code_execution: "Code execution",
  information_disclosure: "Information disclosure",
  denial_of_service: "Denial of service",
  privilege_escalation: "Escalation of privileges",
  other: "Other",
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};
const ORIGIN: Record<ReportOrigin, string> = {
  operator: "Your text",
  derived: "From the record",
  missing: "Not written yet",
};

function OriginTag({
  origin,
  source,
}: {
  origin: ReportOrigin;
  source?: string;
}) {
  return (
    <span
      className={`fr-origin ${origin}`}
      title={source ? `From ${source}` : undefined}
    >
      {ORIGIN[origin]}
    </span>
  );
}

function factText(key: string, fact: ReportFact, report: FindingReport) {
  if (!fact.value) return null;
  if (key === "cwe" && report.cwe)
    return report.cwe.name
      ? `${report.cwe.id}: ${report.cwe.name}`
      : report.cwe.id;
  return LABELS[fact.value] || fact.value;
}

function Section({ section }: { section: ReportSection }) {
  let body: ReactNode;
  if (section.origin === "missing")
    body = <p className="muted">Not written yet.</p>;
  else if (section.key === "references")
    body = (
      <ul className="fr-list">
        {(section.links || []).map((link) => (
          <li key={link.url}>
            <a href={link.url} target="_blank" rel="noreferrer noopener">
              {link.title || link.url}
            </a>
          </li>
        ))}
      </ul>
    );
  else
    body = (
      <>
        {section.text && <p className="fr-text">{section.text}</p>}
        {section.code && <pre className="fl-poc">{section.code}</pre>}
        {section.items && (
          <ul className="fr-list">
            {section.items.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        )}
      </>
    );
  return (
    <section className={`fr-section ${section.origin}`}>
      <div className="fr-section-head">
        <h3 className="label">{section.title}</h3>
        <OriginTag origin={section.origin} source={section.source} />
      </div>
      {body}
    </section>
  );
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API refused (insecure context): fall back to a selection.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export function FindingReportView({
  arenaId,
  findingId,
}: {
  arenaId: string;
  findingId: string;
}) {
  const base = `/api/console/arenas/${encodeURIComponent(arenaId)}/findings/${encodeURIComponent(findingId)}`;
  const [report, setReport] = useState<FindingReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getJson<FindingReport>(`${base}/report`, controller.signal)
      .then(setReport)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "Report unavailable",
          );
      });
    return () => controller.abort();
  }, [base]);
  if (error) return <p className="fr-error">{error}</p>;
  if (!report) return <p className="muted">Assembling the report…</p>;
  const doCopy = async (what: "markdown" | "cve") => {
    const ok = await copy(
      what === "markdown" ? report.markdown : report.cve_request,
    );
    setCopied(ok ? what : "failed");
    window.setTimeout(() => setCopied(null), 2200);
  };
  const gaps = report.readiness.missing.length;
  return (
    <div className="fr">
      <div className="fr-bar">
        <span className={`fr-ready ${report.readiness.ready ? "ok" : "gap"}`}>
          <Icon name={report.readiness.ready ? "check" : "alert"} size={14} />
          {report.readiness.ready
            ? "Ready to send"
            : `${gaps} ${gaps === 1 ? "gap" : "gaps"} before sending`}
        </span>
        <span className="fl-sp" />
        <button
          type="button"
          className="button button-outline"
          onClick={() => void doCopy("markdown")}
        >
          <Icon name="copy" size={14} />
          Copy report
        </button>
        <button
          type="button"
          className="button button-outline"
          onClick={() => void doCopy("cve")}
        >
          <Icon name="copy" size={14} />
          Copy CVE request
        </button>
        <a className="button button-outline" href={`${base}/report.md`}>
          <Icon name="download" size={14} />
          .md
        </a>
        <button
          type="button"
          className="button"
          aria-expanded={editing}
          onClick={() => setEditing(!editing)}
        >
          <Icon name="edit" size={14} />
          {editing ? "Close editor" : "Edit write-up"}
        </button>
        <span className="fr-copied" role="status" aria-live="polite">
          {copied === "markdown"
            ? "Report copied as Markdown"
            : copied === "cve"
              ? "CVE request copied"
              : copied === "failed"
                ? "Copy failed: use the .md download"
                : ""}
        </span>
      </div>
      {editing && (
        <WriteupEditor
          report={report}
          path={`${base}/writeup`}
          onSaved={(next) => {
            setReport(next);
            setEditing(false);
          }}
          onCancel={() => setEditing(false)}
        />
      )}
      <div className="fr-cols">
        <div className="fr-main">
          {report.sections.map((section) => (
            <Section key={section.key} section={section} />
          ))}
        </div>
        <aside className="fr-side">
          <section aria-label="Report readiness" className="fr-checks">
            <h3 className="label">Readiness</h3>
            <ul>
              {report.readiness.checks.map((check) => (
                <li
                  key={check.id}
                  className={
                    check.ok ? "ok" : check.blocking ? "gap" : "advisory"
                  }
                >
                  <Icon
                    name={check.ok ? "check" : check.blocking ? "alert" : "dot"}
                    size={13}
                  />
                  <span>
                    {check.label}
                    {!check.blocking && !check.ok && <small> · optional</small>}
                    {check.message && (
                      <small className="fr-why">{check.message}</small>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <dl className="fl-kv fr-facts">
            <div>
              <dt>Report ID</dt>
              <dd>{report.id}</dd>
            </div>
            {FACTS.map(([key, label]) => {
              const fact = report.facts[key];
              if (!fact) return null;
              const text = factText(key, fact, report);
              return (
                <div key={key}>
                  <dt title={fact.source ? `From ${fact.source}` : undefined}>
                    {label}{" "}
                    {fact.origin !== "derived" && (
                      <OriginTag origin={fact.origin} source={fact.source} />
                    )}
                  </dt>
                  <dd className={text ? "" : "muted"}>
                    {text || "Not stated"}
                  </dd>
                </div>
              );
            })}
          </dl>
          {report.updated_by && (
            <p className="fr-meta">
              Write-up by {report.updated_by}
              {report.updated_at
                ? ` · ${formatObserved(report.updated_at)}`
                : ""}
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

type Draft = Required<Omit<Writeup, "references" | "severity">> & {
  severity: string;
  references: WriteupReference[];
};
const TEXT_FIELDS = [
  "cwe",
  "summary",
  "impact",
  "description",
  "remediation",
  "vendor",
  "product",
  "affected_versions",
  "fixed_versions",
  "component",
  "attack_type",
  "impact_type",
  "cvss_vector",
  "discoverer",
] as const;

function draftOf(report: FindingReport): Draft {
  const w = report.writeup;
  const draft = {
    severity: w.severity || "",
    references: w.references || [],
  } as Draft;
  for (const key of TEXT_FIELDS) draft[key] = w[key] || "";
  return draft;
}

function WriteupEditor({
  report,
  path,
  onSaved,
  onCancel,
}: {
  report: FindingReport;
  path: string;
  onSaved: (report: FindingReport) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(report));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const hint = (key: string) => {
    const fact = report.facts[key];
    if (fact?.origin === "derived" && fact.value)
      return `From the record: ${LABELS[fact.value] || fact.value}`;
    const section = report.sections.find((item) => item.key === key);
    if (section?.origin === "derived" && section.text)
      return section.text.slice(0, 160);
    return undefined;
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {};
    for (const key of TEXT_FIELDS)
      if (draft[key].trim()) body[key] = draft[key].trim();
    if (draft.severity) body.severity = draft.severity;
    const refs = draft.references
      .filter((ref) => ref.url.trim())
      .map((ref) => ({
        url: ref.url.trim(),
        ...(ref.title?.trim() ? { title: ref.title.trim() } : {}),
      }));
    if (refs.length) body.references = refs;
    try {
      onSaved(await postJson<FindingReport>(path, body));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Write-up not saved");
    } finally {
      setBusy(false);
    }
  };
  const input = (
    key: (typeof TEXT_FIELDS)[number],
    label: string,
    placeholder?: string,
  ) => (
    <label className="fr-field">
      <span>{label}</span>
      <input
        value={draft[key]}
        placeholder={placeholder || hint(key)}
        onChange={(event) => set(key, event.target.value)}
      />
    </label>
  );
  const area = (
    key: "summary" | "impact" | "description" | "remediation",
    label: string,
    help: string,
    rows: number,
  ) => (
    <label className="fr-field wide">
      <span>
        {label}
        <small>{help}</small>
      </span>
      <textarea
        rows={rows}
        value={draft[key]}
        placeholder={hint(key)}
        onChange={(event) => set(key, event.target.value)}
      />
    </label>
  );
  return (
    <form className="fr-editor" aria-label="Edit write-up" onSubmit={submit}>
      <p className="muted">
        Leave a field empty to keep what the record says. Your text replaces it
        in the report; the finding itself never changes. Plain text only: no
        credentials or tokens.
      </p>
      <div className="fr-grid">
        <label className="fr-field">
          <span>Severity</span>
          <select
            value={draft.severity}
            onChange={(event) => set("severity", event.target.value)}
          >
            <option value="">
              Reporter's rating ({report.facts.severity?.value || "none"})
            </option>
            {["critical", "high", "medium", "low", "info"].map((level) => (
              <option key={level} value={level}>
                {LABELS[level]}
              </option>
            ))}
          </select>
        </label>
        {input("cwe", "Weakness (CWE)", report.cwe?.id || "CWE-639")}
        {input(
          "cvss_vector",
          "CVSS 3.1 vector",
          "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        )}
        {input("vendor", "Vendor")}
        {input("product", "Product")}
        {input("affected_versions", "Affected versions", "e.g. 22.0, ≤ 21.4")}
        {input("fixed_versions", "Fixed versions")}
        {input("component", "Component")}
        {input("discoverer", "Discovered by")}
        <label className="fr-field">
          <span>Attack type</span>
          <select
            value={draft.attack_type}
            onChange={(event) => set("attack_type", event.target.value)}
          >
            <option value="">{hint("attack_type") || "Not stated"}</option>
            {["remote", "adjacent", "local", "physical"].map((value) => (
              <option key={value} value={value}>
                {LABELS[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="fr-field">
          <span>Impact type</span>
          <select
            value={draft.impact_type}
            onChange={(event) => set("impact_type", event.target.value)}
          >
            <option value="">{hint("impact_type") || "Not stated"}</option>
            {[
              "code_execution",
              "information_disclosure",
              "denial_of_service",
              "privilege_escalation",
              "other",
            ].map((value) => (
              <option key={value} value={value}>
                {LABELS[value]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {area(
        "summary",
        "Summary",
        "One paragraph you could paste as the CVE description: product, version, attacker, impact, vector.",
        3,
      )}
      {area(
        "impact",
        "Impact",
        "Attacker capability, affected asset, consequence. No reproduction details.",
        3,
      )}
      {area(
        "description",
        "Description",
        "Vulnerable component, trust boundary, root cause.",
        5,
      )}
      {area(
        "remediation",
        "Remediation",
        "The concrete fix: what to check, where, against which policy.",
        4,
      )}
      <fieldset className="fr-refs">
        <legend>References</legend>
        {draft.references.map((ref, index) => (
          <div key={index} className="fr-ref">
            <input
              aria-label={`Reference ${index + 1} title`}
              placeholder="Title"
              value={ref.title || ""}
              onChange={(event) =>
                set(
                  "references",
                  draft.references.map((item, j) =>
                    j === index ? { ...item, title: event.target.value } : item,
                  ),
                )
              }
            />
            <input
              aria-label={`Reference ${index + 1} URL`}
              placeholder="https://"
              value={ref.url}
              onChange={(event) =>
                set(
                  "references",
                  draft.references.map((item, j) =>
                    j === index ? { ...item, url: event.target.value } : item,
                  ),
                )
              }
            />
            <button
              type="button"
              className="button button-outline"
              aria-label={`Remove reference ${index + 1}`}
              onClick={() =>
                set(
                  "references",
                  draft.references.filter((_, j) => j !== index),
                )
              }
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        ))}
        <button
          type="button"
          className="button button-outline fr-add"
          disabled={draft.references.length >= 10}
          onClick={() =>
            set("references", [...draft.references, { url: "", title: "" }])
          }
        >
          Add reference
        </button>
      </fieldset>
      {error && (
        <p role="alert" className="fr-error">
          {error}
        </p>
      )}
      <div className="fr-actions">
        <button className="button" disabled={busy}>
          {busy ? "Saving…" : "Save write-up"}
        </button>
        <button
          type="button"
          className="button button-outline"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
