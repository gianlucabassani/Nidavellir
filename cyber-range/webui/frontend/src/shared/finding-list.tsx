// UX-18: findings as one list of rows you open in place. A closed row shows
// the title, the reporter's severity, where it came from, the validator's
// verdict and the operator's decision side by side (kept apart), and how much
// evidence is attached. Opening it shows the claim, how to reproduce it, what
// the validator saw, and the actions. Severity tiles and a state switch filter
// the list; `?finding=<id>` opens one row on arrival.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { FindingRecord, Severity } from "../types";
import { Empty, Status, formatObserved } from "../ui";
import { Icon } from "../shell/icons";
import { FindingReportView } from "./finding-report";
import "./finding-list.css";

export const SEVERITIES: { key: Severity | "none"; label: string }[] = [
  { key: "critical", label: "Critical" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
  { key: "info", label: "Info" },
  { key: "none", label: "Unrated" },
];
const RANK: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
  none: 5,
};
type StateFilter = "awaiting" | "decided" | "all";

const sevKey = (finding: FindingRecord) => finding.severity || "none";
// Finding ids are unique per platform today; the arena keeps keys unique even
// for records imported or replayed with a reused id.
const rowKey = (finding: FindingRecord) =>
  `${finding.arena_id || ""}:${finding.id}`;

function SeverityMark({ severity }: { severity: FindingRecord["severity"] }) {
  const key = severity || "none";
  const label = SEVERITIES.find((item) => item.key === key)?.label;
  return (
    <span className={`sev sev-${key}`} title="The reporter's own rating">
      {label}
    </span>
  );
}

export function FindingList({
  findings,
  showArena = false,
  arenaId,
  arenaHref,
  body,
  actions,
  empty,
}: {
  findings: FindingRecord[];
  showArena?: boolean;
  /** The arena every finding belongs to, when the list is arena-scoped. */
  arenaId?: string;
  /** Where the arena-scoped view of a finding lives. */
  arenaHref?: (finding: FindingRecord) => string | null;
  /** Extra content inside an open row (e.g. the evidence review). */
  body?: (finding: FindingRecord) => ReactNode;
  /** Buttons at the foot of an open row. */
  actions?: (finding: FindingRecord) => ReactNode;
  empty?: ReactNode;
}) {
  const wanted = new URLSearchParams(window.location.search).get("finding");
  const [severity, setSeverity] = useState<string>("");
  const [state, setState] = useState<StateFilter>("all");
  // UX-24: an open row shows the report or the review. A finding still
  // awaiting your decision opens on the review; a decided one on the report.
  const [tabs, setTabs] = useState<Record<string, "report" | "review">>({});
  const [open, setOpen] = useState<Set<string>>(
    () =>
      new Set(
        wanted
          ? findings
              .filter((finding) => finding.id === wanted)
              .slice(0, 1)
              .map(rowKey)
          : [],
      ),
  );
  useEffect(() => {
    if (!wanted) return;
    window.setTimeout(
      () =>
        document
          .getElementById(`finding-${wanted}`)
          ?.scrollIntoView({ block: "center" }),
      50,
    );
  }, [wanted]);
  const awaiting = findings.filter((finding) => !finding.manual_verdict);
  const tabOf = (key: string, finding: FindingRecord) =>
    tabs[key] || (finding.manual_verdict ? "report" : "review");
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const finding of findings)
      out[sevKey(finding)] = (out[sevKey(finding)] || 0) + 1;
    return out;
  }, [findings]);
  const shown = findings
    .filter((finding) => !severity || sevKey(finding) === severity)
    .filter((finding) =>
      state === "all"
        ? true
        : state === "awaiting"
          ? !finding.manual_verdict
          : !!finding.manual_verdict,
    )
    .sort(
      (a, b) =>
        RANK[sevKey(a)] - RANK[sevKey(b)] ||
        (b.at || "").localeCompare(a.at || ""),
    );
  if (!findings.length)
    return (
      <>
        {empty || (
          <Empty
            title="No findings yet"
            detail="A finding appears here when an agent or you submit one."
          />
        )}
      </>
    );
  return (
    <div className="fl">
      <div className="fl-tiles" role="group" aria-label="Filter by severity">
        {SEVERITIES.filter((item) => item.key !== "none" || counts.none).map(
          (item) => (
            <button
              key={item.key}
              type="button"
              className={`fl-tile sev-${item.key}`}
              aria-pressed={severity === item.key}
              onClick={() => setSeverity(severity === item.key ? "" : item.key)}
            >
              <span className="sev-label">{item.label}</span>
              <b>{counts[item.key] || 0}</b>
            </button>
          ),
        )}
      </div>
      <div className="fl-bar">
        <span>
          {findings.length} finding{findings.length === 1 ? "" : "s"} ·{" "}
          {awaiting.length} awaiting your decision
          {severity
            ? ` · showing ${SEVERITIES.find((item) => item.key === severity)?.label}`
            : ""}
        </span>
        <div className="seg" role="group" aria-label="Filter by decision">
          {(
            [
              ["awaiting", "Awaiting you"],
              ["decided", "Decided"],
              ["all", "All"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={state === key}
              onClick={() => setState(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {shown.length ? (
        <ul className="fl-list">
          {shown.map((finding) => {
            const key = rowKey(finding);
            const isOpen = open.has(key);
            const evidence =
              finding.artifacts.length + finding.transactions.length;
            const toArena = arenaHref?.(finding);
            const aid = finding.arena_id || arenaId || "";
            return (
              <li
                key={key}
                id={`finding-${finding.id}`}
                className={`fl-row sev-${sevKey(finding)} ${isOpen ? "open" : ""}`}
              >
                <button
                  type="button"
                  className="fl-sum"
                  aria-expanded={isOpen}
                  aria-controls={`finding-body-${finding.id}`}
                  onClick={() =>
                    setOpen((current) => {
                      const next = new Set(current);
                      if (next.has(key)) next.delete(key);
                      else next.add(key);
                      return next;
                    })
                  }
                >
                  <SeverityMark severity={finding.severity} />
                  <span className="fl-title">
                    <b>{finding.title}</b>
                    <small>
                      {finding.id} · {finding.source}
                      {showArena && finding.arena_name
                        ? ` · ${finding.arena_name}`
                        : ""}
                      {finding.at ? ` · ${formatObserved(finding.at)}` : ""}
                    </small>
                  </span>
                  <span className="fl-vd">
                    <small>Validator</small>
                    <Status value={finding.validator_verdict} />
                  </span>
                  <span className="fl-vd">
                    <small>You</small>
                    <Status value={finding.manual_verdict || "awaiting you"} />
                  </span>
                  <span className="fl-ev">{evidence} evidence</span>
                  <Icon name="chev" size={15} />
                </button>
                {isOpen && (
                  <div className="fl-body" id={`finding-body-${finding.id}`}>
                    {aid && (
                      <div
                        className="seg fl-tabs"
                        role="group"
                        aria-label="Finding view"
                      >
                        {(["report", "review"] as const).map((tab) => (
                          <button
                            key={tab}
                            type="button"
                            aria-pressed={tabOf(key, finding) === tab}
                            onClick={() =>
                              setTabs((current) => ({ ...current, [key]: tab }))
                            }
                          >
                            {tab === "report" ? "Report" : "Review"}
                          </button>
                        ))}
                      </div>
                    )}
                    {aid && tabOf(key, finding) === "report" ? (
                      <FindingReportView arenaId={aid} findingId={finding.id} />
                    ) : (
                      <div className="fl-cols">
                        <div className="fl-main">
                          <section>
                            <h3 className="label">What the reporter claims</h3>
                            <p>
                              {finding.evidence || (
                                <span className="muted">
                                  No description was given.
                                </span>
                              )}
                            </p>
                          </section>
                          <section>
                            <h3 className="label">How to reproduce</h3>
                            {finding.poc ? (
                              <pre className="fl-poc">{finding.poc}</pre>
                            ) : (
                              <p className="muted">
                                No reproduction steps were given.
                              </p>
                            )}
                          </section>
                          <section>
                            <h3 className="label">What the validator saw</h3>
                            <p>
                              <Status value={finding.validator_verdict} />{" "}
                              {finding.validation_reason
                                ? finding.validation_reason.replaceAll("_", " ")
                                : "No independent conclusion recorded."}
                            </p>
                            {body?.(finding)}
                          </section>
                        </div>
                        <div className="fl-side">
                          <dl className="fl-kv">
                            <div>
                              <dt>Severity</dt>
                              <dd>
                                {finding.severity
                                  ? `${SEVERITIES.find((item) => item.key === finding.severity)?.label} (reporter's rating)`
                                  : "Not rated"}
                              </dd>
                            </div>
                            <div>
                              <dt>Weakness</dt>
                              <dd>{finding.cwe || "Not stated"}</dd>
                            </div>
                            <div>
                              <dt>Station</dt>
                              <dd>{finding.node || "Not stated"}</dd>
                            </div>
                            <div>
                              <dt>Reported by</dt>
                              <dd>{finding.source}</dd>
                            </div>
                            {showArena && (
                              <div>
                                <dt>Arena</dt>
                                <dd>
                                  {finding.arena_known && finding.arena_id ? (
                                    <a
                                      href={`/console/arena/${encodeURIComponent(finding.arena_id)}`}
                                    >
                                      {finding.arena_name}
                                    </a>
                                  ) : (
                                    `${finding.arena_name || "Unknown"} (record removed)`
                                  )}
                                </dd>
                              </div>
                            )}
                          </dl>
                          <section>
                            <h3 className="label">Evidence</h3>
                            {evidence ? (
                              <ul className="fl-evidence">
                                {finding.transactions.map((transaction) => (
                                  <li key={transaction.digest}>
                                    <Icon name="swap" size={14} />
                                    {aid ? (
                                      <a
                                        href={`/console/arena/${encodeURIComponent(aid)}?tab=http&digest=${encodeURIComponent(transaction.digest)}`}
                                      >
                                        {transaction.method} {transaction.path}{" "}
                                        → {transaction.status}
                                      </a>
                                    ) : (
                                      <span>
                                        {transaction.method} {transaction.path}
                                      </span>
                                    )}
                                    <small>
                                      {transaction.digest.slice(-12)}
                                    </small>
                                  </li>
                                ))}
                                {finding.artifacts.map((artifact) => (
                                  <li key={artifact.digest}>
                                    <Icon name="file" size={14} />
                                    <a
                                      href={`/api/arenas/${encodeURIComponent(aid)}/evidence-artifacts/${encodeURIComponent(artifact.digest)}`}
                                    >
                                      Artifact · {artifact.bytes} bytes
                                    </a>
                                    <small>{artifact.digest.slice(-12)}</small>
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p className="muted">No evidence attached.</p>
                            )}
                          </section>
                        </div>
                      </div>
                    )}
                    <div className="fl-foot">
                      {actions?.(finding)}
                      <span className="fl-sp" />
                      {toArena && (
                        <a className="button button-outline" href={toArena}>
                          Open in arena
                        </a>
                      )}
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <Empty
          title="No findings match"
          detail="Change the severity or decision filter to see the rest."
        />
      )}
    </div>
  );
}
