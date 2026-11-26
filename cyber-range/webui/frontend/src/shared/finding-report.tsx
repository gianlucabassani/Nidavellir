// UX-24/25: a finding as a report you can send. The reporting agent writes the
// report (the structured write-up); you can take any section over, after
// which the agent can no longer change it. Where a section is still empty the
// console falls back to what the platform recorded and says so. The readiness
// list comes from the orchestrator and names every gap. Copy it as Markdown or
// as a CVE request, or download the .md file.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { getJson, postJson } from "../api";
import type {
  FindingReport,
  ReportFact,
  ReportOrigin,
  ReportSection,
  Writeup,
  WriteupAsset,
  WriteupCwe,
  WriteupReference,
} from "../types";
import { Icon } from "../shell/icons";
import { formatObserved } from "../ui";
import "./finding-report.css";

const FACTS: [string, string][] = [
  ["severity", "Severity"],
  ["cwe", "Weakness"],
  ["affected_assets", "Affected assets"],
  ["vendor", "Vendor"],
  ["product", "Product"],
  ["affected_versions", "Affected versions"],
  ["fixed_versions", "Fixed versions"],
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
  agent: "Agent",
  operator: "Your text",
  derived: "From the record",
  missing: "Not written yet",
};
const ASSET_KINDS = [
  "endpoint",
  "url",
  "parameter",
  "component",
  "host",
  "file",
];

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

/** The write-up's Markdown subset as React text nodes (never HTML):
 * paragraphs, fenced code blocks, bullet and numbered lines, `inline code`. */
function Prose({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split("\n");
  const inline = (line: string) =>
    line
      .split(/(`[^`]+`)/g)
      .map((part, index) =>
        part.startsWith("`") && part.endsWith("`") && part.length > 2 ? (
          <code key={index}>{part.slice(1, -1)}</code>
        ) : (
          part
        ),
      );
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      for (i += 1; i < lines.length && !lines[i].trim().startsWith("```"); i++)
        code.push(lines[i]);
      blocks.push(
        <pre key={blocks.length} className="fl-poc">
          {code.join("\n")}
        </pre>,
      );
    } else if (/^\s*([-*+]|\d+\.) /.test(line)) {
      blocks.push(
        <p key={blocks.length} className="fr-text fr-li">
          {inline(line.trim())}
        </p>,
      );
    } else if (line.trim()) {
      blocks.push(
        <p key={blocks.length} className="fr-text">
          {inline(line)}
        </p>,
      );
    }
  }
  return <div className="fr-prose">{blocks}</div>;
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
  else {
    const rep = section.reproduction;
    body = (
      <>
        {section.text && <Prose text={section.text} />}
        {rep && (
          <div className="fr-repro">
            {(rep.prerequisites || rep.auth_role) && (
              <dl className="fr-repro-meta">
                {rep.prerequisites && (
                  <div>
                    <dt>Prerequisites</dt>
                    <dd>{rep.prerequisites}</dd>
                  </div>
                )}
                {rep.auth_role && (
                  <div>
                    <dt>Authentication role</dt>
                    <dd>{rep.auth_role}</dd>
                  </div>
                )}
              </dl>
            )}
            {rep.steps.length > 0 && (
              <ol className="fr-steps">
                {rep.steps.map((step, index) => (
                  <li key={index}>
                    <Prose text={step.action} />
                    {step.expected && (
                      <p className="fr-expected">
                        <span>Expected</span> {step.expected}
                      </p>
                    )}
                    {step.evidence.length > 0 && (
                      <p className="fr-cites">
                        {step.evidence.map((item) => (
                          <span key={item.digest} title={item.digest}>
                            {item.label}
                          </span>
                        ))}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            )}
            {rep.cleanup && (
              <p className="fr-expected">
                <span>Cleanup</span> {rep.cleanup}
              </p>
            )}
          </div>
        )}
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
  }
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

function factText(fact: ReportFact) {
  return fact.value ? LABELS[fact.value] || fact.value : null;
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
  const gaps = report.readiness.checks.filter(
    (check) => check.blocking && !check.ok,
  ).length;
  const agentSections = Object.values(report.origin).filter(
    (owner) => owner === "agent",
  ).length;
  return (
    <div className="fr">
      <div className="fr-bar">
        <span className={`fr-ready ${report.readiness.ready ? "ok" : "gap"}`}>
          <Icon name={report.readiness.ready ? "check" : "alert"} size={14} />
          {report.readiness.ready
            ? "Ready to send"
            : `${gaps} ${gaps === 1 ? "gap" : "gaps"} before sending`}
        </span>
        <span className="fr-by">
          {agentSections
            ? `${agentSections} sections written by the agent`
            : "The agent has not written this up yet"}
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
                    {!check.ok &&
                      check.messages.map((message) => (
                        <small key={message} className="fr-why">
                          {message}
                        </small>
                      ))}
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
              const text = factText(fact);
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
          {report.updated?.by && (
            <p className="fr-meta">
              Last written by {report.updated.by} (
              {report.updated.role === "operator" ? "operator" : "agent"})
              {report.updated.at
                ? ` · ${formatObserved(report.updated.at)}`
                : ""}
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

const TEXTS = ["summary", "impact", "description", "remediation"] as const;
const SHORTS = [
  "vendor",
  "product",
  "affected_versions",
  "fixed_versions",
  "discoverer",
  "cvss_vector",
] as const;
type Step = { action: string; expected: string; evidence: string[] };
type Draft = Record<
  (typeof TEXTS)[number] | (typeof SHORTS)[number],
  string
> & {
  severity: string;
  attack_type: string;
  impact_type: string;
  assets: WriteupAsset[];
  cwes: WriteupCwe[];
  prerequisites: string;
  auth_role: string;
  cleanup: string;
  steps: Step[];
  references: WriteupReference[];
};

function draftOf(w: Writeup): Draft {
  const draft = {
    severity: w.severity || "",
    attack_type: w.attack_type || "",
    impact_type: w.impact_type || "",
    assets: w.affected_assets || [],
    cwes: w.cwes || [],
    prerequisites: w.reproduction?.prerequisites || "",
    auth_role: w.reproduction?.auth_role || "",
    cleanup: w.reproduction?.cleanup || "",
    steps: (w.reproduction?.steps || []).map((step) => ({
      action: step.action,
      expected: step.expected || "",
      evidence: step.evidence || [],
    })),
    references: w.references || [],
  } as Draft;
  for (const key of [...TEXTS, ...SHORTS]) draft[key] = w[key] || "";
  return draft;
}

/** The sections that changed, as a patch: an emptied section is cleared. */
function patchOf(draft: Draft, before: Writeup): Record<string, unknown> {
  const next: Record<string, unknown> = {};
  for (const key of [...TEXTS, ...SHORTS])
    next[key] = draft[key].trim() || null;
  for (const key of ["severity", "attack_type", "impact_type"] as const)
    next[key] = draft[key] || null;
  const assets = draft.assets
    .filter((asset) => asset.value.trim())
    .map((asset) => ({ kind: asset.kind, value: asset.value.trim() }));
  next.affected_assets = assets.length ? assets : null;
  const cwes = draft.cwes
    .filter((cwe) => cwe.id.trim())
    .map((cwe) => ({
      id: cwe.id.trim().toUpperCase(),
      name: cwe.name.trim() || cwe.id.trim().toUpperCase(),
    }));
  next.cwes = cwes.length ? cwes : null;
  const refs = draft.references
    .filter((ref) => ref.url.trim())
    .map((ref) => ({
      url: ref.url.trim(),
      ...(ref.title?.trim() ? { title: ref.title.trim() } : {}),
    }));
  next.references = refs.length ? refs : null;
  const steps = draft.steps
    .filter((step) => step.action.trim())
    .map((step) => ({
      action: step.action.trim(),
      ...(step.expected.trim() ? { expected: step.expected.trim() } : {}),
      evidence: step.evidence,
    }));
  const rep = {
    ...(draft.prerequisites.trim()
      ? { prerequisites: draft.prerequisites.trim() }
      : {}),
    ...(draft.auth_role.trim() ? { auth_role: draft.auth_role.trim() } : {}),
    ...(draft.cleanup.trim() ? { cleanup: draft.cleanup.trim() } : {}),
    steps,
  };
  next.reproduction = steps.length || Object.keys(rep).length > 1 ? rep : null;
  const prev = before as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(next).filter(
      ([key, value]) =>
        JSON.stringify(value ?? null) !== JSON.stringify(prev[key] ?? null),
    ),
  );
}

function Rows<T>({
  label,
  noun,
  rows,
  blank,
  render,
  onChange,
  max = 20,
}: {
  label: string;
  noun: string;
  rows: T[];
  blank: T;
  render: (row: T, set: (value: T) => void, index: number) => ReactNode;
  onChange: (rows: T[]) => void;
  max?: number;
}) {
  return (
    <fieldset className="fr-refs">
      <legend>{label}</legend>
      {rows.map((row, index) => (
        <div key={index} className="fr-ref">
          {render(
            row,
            (value) =>
              onChange(rows.map((item, j) => (j === index ? value : item))),
            index,
          )}
          <button
            type="button"
            className="button button-outline"
            aria-label={`Remove ${noun} ${index + 1}`}
            onClick={() => onChange(rows.filter((_, j) => j !== index))}
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      ))}
      <button
        type="button"
        className="button button-outline fr-add"
        disabled={rows.length >= max}
        onClick={() => onChange([...rows, blank])}
      >
        Add {noun}
      </button>
    </fieldset>
  );
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
  const [draft, setDraft] = useState<Draft>(() => draftOf(report.writeup));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const setStep = (index: number, change: Partial<Step>) =>
    set(
      "steps",
      draft.steps.map((item, j) =>
        j === index ? { ...item, ...change } : item,
      ),
    );
  const hint = (key: string) => {
    const fact = report.facts[key];
    if (fact?.origin === "derived" && fact.value)
      return `From the record: ${LABELS[fact.value] || fact.value}`;
    const section = report.sections.find((item) => item.key === key);
    if (section?.origin === "derived" && section.text)
      return section.text.slice(0, 160);
    return undefined;
  };
  const owner = (key: string) =>
    report.origin[key] === "agent" ? " · written by the agent" : "";
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const patch = patchOf(draft, report.writeup);
    if (!Object.keys(patch).length) {
      setError("Nothing changed.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(await postJson<FindingReport>(path, { patch }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Write-up not saved");
    } finally {
      setBusy(false);
    }
  };
  const input = (
    key: (typeof SHORTS)[number],
    label: string,
    placeholder?: string,
  ) => (
    <label className="fr-field">
      <span>{label}</span>
      <input
        value={draft[key]}
        placeholder={placeholder || hint(key)}
        title={owner(key) || undefined}
        onChange={(event) => set(key, event.target.value)}
      />
    </label>
  );
  const select = (
    key: "severity" | "attack_type" | "impact_type",
    label: string,
    options: string[],
  ) => (
    <label className="fr-field">
      <span>{label}</span>
      <select
        value={draft[key]}
        onChange={(event) => set(key, event.target.value)}
      >
        <option value="">{hint(key) || "Not stated"}</option>
        {options.map((value) => (
          <option key={value} value={value}>
            {LABELS[value]}
          </option>
        ))}
      </select>
    </label>
  );
  const area = (
    key: (typeof TEXTS)[number],
    label: string,
    help: string,
    rows: number,
  ) => (
    <label className="fr-field wide">
      <span>
        {label}
        <small>
          {help}
          {owner(key)}
        </small>
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
        The agent writes this report. A section you save becomes yours: the
        agent can no longer change it (empty it to hand it back). Markdown, one
        paragraph per line, code in fenced blocks with a language; no
        credentials.
      </p>
      <div className="fr-grid">
        {select("severity", "Severity", [
          "critical",
          "high",
          "medium",
          "low",
          "info",
        ])}
        {input(
          "cvss_vector",
          "CVSS 3.1 vector",
          "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        )}
        {input("vendor", "Vendor")}
        {input("product", "Product")}
        {input("affected_versions", "Affected versions", "e.g. 22.0, ≤ 21.4")}
        {input("fixed_versions", "Fixed versions")}
        {input("discoverer", "Discovered by")}
        {select("attack_type", "Attack type", [
          "remote",
          "adjacent",
          "local",
          "physical",
        ])}
        {select("impact_type", "Impact type", [
          "code_execution",
          "information_disclosure",
          "denial_of_service",
          "privilege_escalation",
          "other",
        ])}
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
        "Two or three lines (a blank line between them): attacker capability, affected asset, consequence.",
        3,
      )}
      {area(
        "description",
        "Description",
        "Vulnerable component, trust boundary, root cause.",
        5,
      )}
      <Rows
        label="Affected assets"
        noun="asset"
        rows={draft.assets}
        blank={{ kind: "endpoint", value: "" }}
        onChange={(rows) => set("assets", rows)}
        render={(row, update, index) => (
          <>
            <select
              aria-label={`Asset ${index + 1} kind`}
              value={row.kind}
              onChange={(event) => update({ ...row, kind: event.target.value })}
            >
              {ASSET_KINDS.map((kind) => (
                <option key={kind}>{kind}</option>
              ))}
            </select>
            <input
              aria-label={`Asset ${index + 1}`}
              value={row.value}
              onChange={(event) =>
                update({ ...row, value: event.target.value })
              }
            />
          </>
        )}
      />
      <Rows
        label="CWEs"
        noun="CWE"
        rows={draft.cwes}
        blank={{ id: "", name: "" }}
        max={10}
        onChange={(rows) => set("cwes", rows)}
        render={(row, update, index) => (
          <>
            <input
              aria-label={`CWE ${index + 1} id`}
              placeholder="CWE-639"
              value={row.id}
              onChange={(event) => update({ ...row, id: event.target.value })}
            />
            <input
              aria-label={`CWE ${index + 1} name`}
              value={row.name}
              onChange={(event) => update({ ...row, name: event.target.value })}
            />
          </>
        )}
      />
      <fieldset className="fr-repro-edit">
        <legend>Reproduction{owner("reproduction")}</legend>
        <div className="fr-grid">
          <label className="fr-field">
            <span>Prerequisites</span>
            <input
              value={draft.prerequisites}
              onChange={(event) => set("prerequisites", event.target.value)}
            />
          </label>
          <label className="fr-field">
            <span>Authentication role</span>
            <input
              value={draft.auth_role}
              placeholder="unauthenticated, author, admin…"
              onChange={(event) => set("auth_role", event.target.value)}
            />
          </label>
        </div>
        <ol className="fr-step-edit">
          {draft.steps.map((step, index) => (
            <li key={index}>
              <label className="fr-field wide">
                <span>Step {index + 1}: action</span>
                <textarea
                  rows={2}
                  value={step.action}
                  onChange={(event) =>
                    setStep(index, { action: event.target.value })
                  }
                />
              </label>
              <label className="fr-field wide">
                <span>Step {index + 1}: expected result</span>
                <input
                  value={step.expected}
                  onChange={(event) =>
                    setStep(index, { expected: event.target.value })
                  }
                />
              </label>
              {report.evidence_options.length > 0 && (
                <fieldset className="fr-cite-edit">
                  <legend>Evidence for step {index + 1}</legend>
                  {report.evidence_options.map((option) => (
                    <label key={option.digest}>
                      <input
                        type="checkbox"
                        checked={step.evidence.includes(option.digest)}
                        onChange={(event) =>
                          setStep(index, {
                            evidence: event.target.checked
                              ? [...step.evidence, option.digest]
                              : step.evidence.filter(
                                  (digest) => digest !== option.digest,
                                ),
                          })
                        }
                      />
                      {option.label} {option.what}
                    </label>
                  ))}
                </fieldset>
              )}
              <button
                type="button"
                className="button button-outline fr-add"
                onClick={() =>
                  set(
                    "steps",
                    draft.steps.filter((_, j) => j !== index),
                  )
                }
              >
                Remove step {index + 1}
              </button>
            </li>
          ))}
        </ol>
        <button
          type="button"
          className="button button-outline fr-add"
          onClick={() =>
            set("steps", [
              ...draft.steps,
              { action: "", expected: "", evidence: [] },
            ])
          }
        >
          Add step
        </button>
        <label className="fr-field wide">
          <span>Cleanup</span>
          <input
            value={draft.cleanup}
            onChange={(event) => set("cleanup", event.target.value)}
          />
        </label>
      </fieldset>
      {area(
        "remediation",
        "Remediation",
        "The concrete fix: what to check, where, against which policy.",
        4,
      )}
      <Rows
        label="References"
        noun="reference"
        rows={draft.references}
        blank={{ url: "", title: "" }}
        onChange={(rows) => set("references", rows)}
        render={(row, update, index) => (
          <>
            <input
              aria-label={`Reference ${index + 1} title`}
              placeholder="Title"
              value={row.title || ""}
              onChange={(event) =>
                update({ ...row, title: event.target.value })
              }
            />
            <input
              aria-label={`Reference ${index + 1} URL`}
              placeholder="https://"
              value={row.url}
              onChange={(event) => update({ ...row, url: event.target.value })}
            />
          </>
        )}
      />
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
