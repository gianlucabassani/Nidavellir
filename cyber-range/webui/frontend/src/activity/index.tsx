import { useState } from "react";
import type { ActivityData } from "../types";
import {
  Empty,
  ErrorState,
  formatObserved,
  Loading,
  PageHead,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

type Section = "findings" | "evidence" | "audit";
const sections: Section[] = ["findings", "evidence", "audit"];

export function Activity() {
  const requested = new URLSearchParams(window.location.search).get("section");
  const [section, setSection] = useState<Section>(
    sections.includes(requested as Section)
      ? (requested as Section)
      : "findings",
  );
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState("all");
  const [source, setSource] = useState("all");
  const { value, error, loading, refresh } = useWorkspaceData<ActivityData>(
    "/api/console/activity",
  );
  function select(next: Section) {
    setSection(next);
    const url = new URL(window.location.href);
    url.searchParams.set("section", next);
    window.history.replaceState(null, "", url);
  }
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const filter = (text: string) =>
    text.toLowerCase().includes(query.trim().toLowerCase());
  const verdicts = [...new Set(value.findings.map((item) => item.verdict))];
  const findings = value.findings.filter(
    (item) =>
      (verdict === "all" || item.verdict === verdict) &&
      filter(`${item.title} ${item.arena_name} ${item.verdict}`),
  );
  const artifacts = value.artifacts.filter((item) =>
    filter(`${item.finding_title} ${item.arena_name} ${item.digest}`),
  );
  const signals = value.signals.filter((item) =>
    filter(`${item.summary} ${item.kind} ${item.arena_name}`),
  );
  const audit = value.audit.filter(
    (item) =>
      (source === "all" || item.source === source) &&
      filter(`${item.type} ${item.actor} ${item.arena_name}`),
  );
  const chips = (
    label: string,
    options: string[],
    current: string,
    set: (next: string) => void,
    count: (option: string) => number,
  ) => (
    <nav className="filter-chips" aria-label={label}>
      {["all", ...options].map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={current === option}
          onClick={() => set(option)}
        >
          {option === "all"
            ? "All"
            : option[0].toUpperCase() + option.slice(1).replaceAll("_", " ")}
          <b>{count(option)}</b>
        </button>
      ))}
    </nav>
  );
  return (
    <>
      <PageHead
        overline="SHARED / RECORDS"
        title="Activity & evidence"
        subtitle="Review operator findings, protected proof, monitor signals and the audit trail across arenas."
        observed={value.observed_at}
        action={
          <a
            className="button button-outline"
            href="/console?workspace=research"
          >
            Open Research ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="activity-stats">
        <div>
          <strong>{value.findings.length}</strong>
          <span>Findings</span>
        </div>
        <div>
          <strong>{value.artifacts.length}</strong>
          <span>Artifacts</span>
        </div>
        <div>
          <strong>{value.signals.length}</strong>
          <span>Monitor signals</span>
        </div>
        <div>
          <strong>{value.audit.length}</strong>
          <span>Recent events</span>
        </div>
      </div>
      <div className="activity-toolbar">
        <nav className="registry-tabs" aria-label="Activity sections">
          {sections.map((item) => (
            <button
              key={item}
              type="button"
              aria-current={section === item ? "page" : undefined}
              onClick={() => select(item)}
            >
              {item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </nav>
        <label className="activity-search">
          Filter records
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Finding, arena, digest or actor"
          />
        </label>
      </div>
      {section === "findings" && (
        <Panel
          eyebrow="01 / OBSERVATIONS"
          title="Reported findings"
          aside={<span className="tiny-tag">{findings.length} SHOWN</span>}
        >
          {chips(
            "Filter findings by verdict",
            verdicts,
            verdict,
            setVerdict,
            (option) =>
              value.findings.filter(
                (item) => option === "all" || item.verdict === option,
              ).length,
          )}
          {findings.length ? (
            <div className="activity-list">
              {findings.map((item, index) => (
                <article className="activity-row" key={`${item.id}-${index}`}>
                  <div>
                    <strong>{item.title}</strong>
                    <Status value={item.verdict} />
                  </div>
                  <small>
                    {item.arena_name} ·{" "}
                    {item.ts ? formatObserved(item.ts) : "Time unknown"} ·{" "}
                    {item.artifact_count} artifacts
                  </small>
                  {item.arena_known && item.arena_id ? (
                    <a
                      className="inline-action"
                      href={`/console/arena/${encodeURIComponent(item.arena_id)}?tab=findings`}
                    >
                      Review in arena ↗
                    </a>
                  ) : (
                    <span className="activity-unavailable">
                      Arena record unavailable
                    </span>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="No matching findings"
              detail={
                query
                  ? "Clear the filter to see all reported findings."
                  : "Agent and operator reports will appear here."
              }
            />
          )}
        </Panel>
      )}
      {section === "evidence" && (
        <div className="activity-evidence-grid">
          <Panel eyebrow="02 / ARTIFACTS" title="Attached proof">
            {artifacts.length ? (
              <div className="activity-list">
                {artifacts.map((item, index) => (
                  <article
                    className="activity-row"
                    key={`${item.digest}-${index}`}
                  >
                    <strong>{item.finding_title}</strong>
                    <small>
                      {item.arena_name} · {item.bytes} bytes
                    </small>
                    <code>{item.digest}</code>
                    {item.arena_known && item.arena_id ? (
                      <a
                        className="inline-action"
                        href={`/api/arenas/${encodeURIComponent(item.arena_id)}/evidence-artifacts/${encodeURIComponent(item.digest)}`}
                      >
                        Open artifact ↗
                      </a>
                    ) : (
                      <span className="activity-unavailable">
                        Arena record unavailable
                      </span>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <Empty
                title="No matching artifacts"
                detail="Artifacts attached to findings appear here."
              />
            )}
          </Panel>
          <Panel eyebrow="03 / TELEMETRY" title="Monitor signals">
            {signals.length ? (
              <div className="activity-list">
                {signals.map((item, index) => (
                  <article
                    className="activity-row"
                    key={`${item.arena_id}-${item.ts}-${index}`}
                  >
                    <div>
                      <strong>
                        {item.summary || item.kind || "Monitor signal"}
                      </strong>
                      <Status value={item.severity || "observed"} />
                    </div>
                    <small>
                      {item.arena_name} · {item.node || "arena"} ·{" "}
                      {item.ts ? formatObserved(item.ts) : "Time unknown"}
                    </small>
                    {item.arena_known && item.arena_id && (
                      <a
                        className="inline-action"
                        href={`/console/arena/${encodeURIComponent(item.arena_id)}?tab=evidence`}
                      >
                        Review evidence ↗
                      </a>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <Empty
                title="No matching signals"
                detail="Observed target telemetry will appear here."
              />
            )}
          </Panel>
        </div>
      )}
      {section === "audit" && (
        <Panel
          eyebrow="04 / TRACE"
          title="Audit trail"
          aside={<span className="tiny-tag">LATEST 200</span>}
        >
          {chips(
            "Filter audit events by source",
            ["agent", "human", "system"],
            source,
            setSource,
            (option) =>
              value.audit.filter(
                (item) => option === "all" || item.source === option,
              ).length,
          )}
          {audit.length ? (
            <div className="activity-list">
              {audit.map((item, index) => (
                <article
                  className="activity-row activity-audit-row"
                  key={`${item.ts}-${index}`}
                >
                  <span className="activity-source">{item.source}</span>
                  <strong>{item.type.replaceAll("_", " ")}</strong>
                  <small>
                    {item.actor} · {item.arena_name || "platform"} ·{" "}
                    {item.ts ? formatObserved(item.ts) : "Time unknown"}
                  </small>
                  {item.arena_known && item.arena_id && (
                    <a
                      className="inline-action"
                      href={`/console/arena/${encodeURIComponent(item.arena_id)}`}
                    >
                      Open arena ↗
                    </a>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="No matching events"
              detail="Lifecycle and research events appear in the append-only record."
            />
          )}
        </Panel>
      )}
    </>
  );
}
