import { navigate } from "../router";
import { useEffect, useId, useRef, useState } from "react";
import type React from "react";
import { postJson } from "../api";
import type {
  CampaignFinding,
  CampaignIdentityEntry,
  CampaignListItem,
  CampaignSummary,
  DisclosureState,
} from "../types";
import {
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  formatObserved,
  useWorkspaceData,
  DisabledReason,
} from "../ui";
import "./source-review.css";
import "./campaigns.css";

export const CAMPAIGN_API = "/api/console/research/campaigns";

// Shown on every campaign view. Operator state and evidence are never merged.
const CAPTION =
  "Disclosure state is operator judgment; the outcome column is what the recorded evidence shows.";

const STATES: DisclosureState[] = [
  "internal",
  "reported",
  "fixed",
  "published",
  "regressed",
];
const STATE_LABEL: Record<DisclosureState, string> = {
  internal: "Internal",
  reported: "Reported",
  fixed: "Fixed",
  published: "Published",
  regressed: "Regressed",
};
const OUTCOME_LABEL: Record<string, string> = {
  disappeared_under_controls: "Disappeared under controls",
  still_observed: "Still observed",
  inconclusive: "Inconclusive",
  unknown: "Unknown",
};

function StateBadge({ state }: { state: DisclosureState }) {
  return (
    <span className={`campaign-state campaign-state-${state}`}>
      {STATE_LABEL[state]}
    </span>
  );
}

function outcomeText(finding: CampaignFinding) {
  if (!finding.available) return "Finding records unavailable";
  const outcome = finding.comparison?.outcome ?? "unknown";
  return OUTCOME_LABEL[outcome] ?? outcome;
}

// Says only what the flag says: whether evidence supports a fixed / regressed state.
function supportText(finding: CampaignFinding) {
  if (finding.state_supported_by_evidence === true)
    return "Supported by recorded evidence";
  if (finding.state_supported_by_evidence === false)
    return "Not supported by recorded evidence";
  return "Evidence cannot speak to this state";
}

function identityLabel(entry: CampaignIdentityEntry) {
  const images = Object.entries(entry.identity.images || {});
  if (!entry.identity.known || !images.length)
    return entry.identity.scenario || `arena ${entry.arena_id}`;
  return images
    .map(([node, image]) => `${node}: ${image.image ?? "unknown image"}`)
    .join(", ");
}

function IdentityList({
  title,
  entries,
}: {
  title: string;
  entries: CampaignIdentityEntry[];
}) {
  return (
    <div className="campaign-identities">
      <strong>
        {title} ({entries.length})
      </strong>
      {entries.length ? (
        <ul>
          {entries.map((entry) => (
            <li key={entry.finding_id}>
              <code>{identityLabel(entry)}</code>
              <small>
                {entry.identity.scenario || "unknown scenario"} · finding{" "}
                {entry.finding_id}
              </small>
            </li>
          ))}
        </ul>
      ) : (
        <small>None recorded</small>
      )}
    </div>
  );
}

function NewCampaign() {
  const [name, setName] = useState("");
  const [product, setProduct] = useState("");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setMessage("");
    try {
      const created = await postJson<CampaignSummary>(CAMPAIGN_API, {
        name: name.trim(),
        product: product.trim(),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      navigate(
        `/console/research/campaigns/${encodeURIComponent(created.campaign_id)}`,
        { replace: true },
      );
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "The campaign could not be created",
      );
      setPending(false);
    }
  }
  return (
    <form className="source-review-form" onSubmit={submit}>
      <label>
        Campaign name
        <input
          required
          maxLength={120}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        Product
        <input
          required
          maxLength={120}
          value={product}
          onChange={(event) => setProduct(event.target.value)}
        />
      </label>
      <label>
        Note (optional)
        <textarea
          maxLength={2000}
          rows={2}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <button className="button button-gold" disabled={pending}>
        {pending ? "Creating…" : "Create campaign"}
      </button>
      {message && (
        <p className="source-review-error" role="alert">
          {message}
        </p>
      )}
    </form>
  );
}

export function Campaigns() {
  const [before, setBefore] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const { value, error, loading, refresh } = useWorkspaceData<{
    campaigns: CampaignListItem[];
    next_before: number | null;
  }>(`${CAMPAIGN_API}${before ? `?before=${before}` : ""}`);
  return (
    <>
      <PageHead
        overline="WORKSPACE / RESEARCH / CAMPAIGNS"
        title="Campaigns"
        subtitle="Findings on one product, traced across versions and tracked to disclosure."
        action={
          <button
            type="button"
            className="button button-gold"
            aria-expanded={creating}
            onClick={() => setCreating(!creating)}
          >
            {creating ? "Close form" : "New campaign"}
          </button>
        }
      />
      <p className="source-review-caption">{CAPTION}</p>
      {creating && (
        <Panel eyebrow="NEW" title="New campaign">
          <NewCampaign />
        </Panel>
      )}
      <Panel
        eyebrow="CAMPAIGNS"
        title="Campaigns"
        aside={
          <button type="button" className="subtle-link" onClick={refresh}>
            Refresh ↻
          </button>
        }
      >
        {error && !value ? (
          <ErrorState message={error} refresh={refresh} />
        ) : loading && !value ? (
          <Loading />
        ) : value?.campaigns.length ? (
          <ul className="source-review-sessions campaign-list">
            {value.campaigns.map((item) => (
              <li key={item.campaign_id}>
                <a
                  href={`/console/research/campaigns/${encodeURIComponent(item.campaign_id)}`}
                >
                  <span className="source-review-session-name">
                    <strong>{item.name}</strong>
                    <small>{item.product}</small>
                  </span>
                  <span>
                    {item.finding_groups} finding{" "}
                    {item.finding_groups === 1 ? "group" : "groups"}
                  </span>
                  <span>
                    {formatObserved(item.created_at)} · {item.actor}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            title="No campaigns"
            detail="Create a campaign, then add a finding to trace it across versions."
          />
        )}
        <div className="http-pagination">
          {before ? (
            <button type="button" onClick={() => setBefore(null)}>
              ← Newest campaigns
            </button>
          ) : (
            <span />
          )}
          {value?.next_before && (
            <button type="button" onClick={() => setBefore(value.next_before)}>
              Older campaigns →
            </button>
          )}
        </div>
      </Panel>
    </>
  );
}

function AddFinding({
  campaignId,
  onChanged,
}: {
  campaignId: string;
  onChanged: (summary: CampaignSummary) => void;
}) {
  const [finding, setFinding] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setStatus("");
    if (!/^[0-9a-f]{12}$/.test(finding.trim())) {
      setMessage("A finding id is 12 lowercase hex characters.");
      return;
    }
    setPending(true);
    setMessage("");
    try {
      const result = await postJson<{
        added: boolean;
        research_key: string;
        campaign: CampaignSummary;
      }>(`${CAMPAIGN_API}/${campaignId}/findings`, {
        finding_id: finding.trim(),
      });
      onChanged(result.campaign);
      setFinding("");
      setStatus(
        result.added
          ? `Added finding group ${result.research_key}.`
          : `Finding group ${result.research_key} was already in this campaign; nothing changed.`,
      );
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "The finding could not be added",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <form className="source-review-form campaign-add" onSubmit={submit}>
      <label>
        Finding id
        <input
          value={finding}
          maxLength={12}
          placeholder="12 hex characters"
          onChange={(event) => setFinding(event.target.value)}
        />
      </label>
      <p>
        Adding any finding adds its whole group: every variant linked to it
        across arenas and versions is one row.
      </p>
      <button className="button button-outline" disabled={pending}>
        {pending ? "Adding…" : "Add finding group"}
      </button>
      {message && (
        <p className="source-review-error" role="alert">
          {message}
        </p>
      )}
      {status && <p role="status">{status}</p>}
    </form>
  );
}

function FindingDrawer({
  campaignId,
  finding,
  onChanged,
  onClose,
}: {
  campaignId: string;
  finding: CampaignFinding;
  onChanged: (summary: CampaignSummary) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [state, setState] = useState<DisclosureState>(finding.disclosure.state);
  const [note, setNote] = useState("");
  const [reference, setReference] = useState("");
  const [includePoc, setIncludePoc] = useState(false);
  const [includeEvidence, setIncludeEvidence] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState("");
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    return () => {
      if (element?.open) element.close();
    };
  }, []);
  const base = `${CAMPAIGN_API}/${campaignId}/findings/${encodeURIComponent(finding.research_key)}`;
  async function refreshSummary() {
    const response = await fetch(`${CAMPAIGN_API}/${campaignId}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (response.ok) onChanged((await response.json()) as CampaignSummary);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setSaved("");
    if (
      (state === "regressed" || state === "internal") &&
      note.trim().length < 10
    ) {
      setMessage(
        `${STATE_LABEL[state]} needs a note of at least 10 characters.`,
      );
      return;
    }
    setPending(true);
    setMessage("");
    try {
      const summary = await postJson<CampaignSummary>(`${base}/disclosure`, {
        state,
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(reference.trim() ? { reference: reference.trim() } : {}),
      });
      onChanged(summary);
      setNote("");
      setReference("");
      setSaved(`Recorded as ${STATE_LABEL[state].toLowerCase()}.`);
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "The disclosure state could not be saved",
      );
    } finally {
      setPending(false);
    }
  }
  async function bundle() {
    if (pending) return;
    setPending(true);
    setMessage("");
    setSaved("");
    try {
      const result = await postJson<{ bundle_digest: string }>(
        `${base}/bundles`,
        { include_poc: includePoc, include_evidence: includeEvidence },
      );
      await refreshSummary();
      setSaved(`Bundle ${result.bundle_digest.slice(0, 19)}… generated.`);
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "The bundle could not be generated",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="source-review-drawer"
      aria-labelledby={titleId}
      onClose={onClose}
    >
      <div className="source-review-drawer-head">
        <div>
          <span className="eyebrow">FINDING GROUP</span>
          <h2 id={titleId}>{finding.title || finding.research_key}</h2>
        </div>
        <button
          type="button"
          className="button button-outline"
          onClick={() => dialog.current?.close()}
        >
          Close
        </button>
      </div>
      <p className="source-review-caption">{CAPTION}</p>
      <dl className="source-review-facts">
        <div>
          <dt>Evidence outcome</dt>
          <dd>{outcomeText(finding)}</dd>
        </div>
        <div>
          <dt>Operator disclosure state</dt>
          <dd>
            <StateBadge state={finding.disclosure.state} />
            <small>{supportText(finding)}</small>
          </dd>
        </div>
        <div>
          <dt>Group</dt>
          <dd>
            <code>{finding.research_key}</code>
            <small>
              {finding.cwe || "no CWE"} · {finding.members.length} member
              {finding.members.length === 1 ? "" : "s"}
            </small>
          </dd>
        </div>
      </dl>
      <h3>Identities by verdict</h3>
      <IdentityList title="Affected" entries={finding.identities.affected} />
      <IdentityList
        title="Not observed under controls"
        entries={finding.identities.not_observed_under_controls}
      />
      <IdentityList title="Unknown" entries={finding.identities.unknown} />
      <p className="campaign-limit">
        A version that was not run is not listed anywhere.
      </p>

      <form className="source-review-form" onSubmit={save}>
        <fieldset>
          <legend>Disclosure state</legend>
          <div className="source-review-checks">
            {STATES.map((value) => (
              <label key={value}>
                <input
                  type="radio"
                  name="disclosure-state"
                  checked={state === value}
                  onChange={() => setState(value)}
                />
                {STATE_LABEL[value]}
              </label>
            ))}
          </div>
        </fieldset>
        <label>
          Note (required for regressed and for a return to internal)
          <textarea
            maxLength={2000}
            rows={3}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <label>
          Reference (optional, for example an advisory id)
          <input
            maxLength={120}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
          />
        </label>
        <button className="button button-gold" disabled={pending}>
          {pending ? "Saving…" : "Save disclosure state"}
        </button>
        <p>
          Each save adds an entry. Earlier entries and the evidence are never
          changed.
        </p>
      </form>

      <h3>Disclosure history</h3>
      {finding.disclosure_history.length ? (
        <ul className="source-review-history">
          {finding.disclosure_history.map((entry, index) => (
            <li key={`${entry.at}-${index}`}>
              <StateBadge state={entry.state} />
              {entry.note && <p>{entry.note}</p>}
              {entry.reference && <p>Reference: {entry.reference}</p>}
              <span>
                {entry.at ? formatObserved(entry.at) : ""} · {entry.actor}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p>No entry yet; the state is internal by default.</p>
      )}
      {finding.disclosure_history_total > finding.disclosure_history.length && (
        <p>
          Showing the newest {finding.disclosure_history.length} of{" "}
          {finding.disclosure_history_total} entries.
        </p>
      )}

      <h3>Disclosure bundle</h3>
      <div className="source-review-form campaign-bundle">
        <p>
          A bundle is a file for you to review. Nothing is sent anywhere. By
          default it carries digests only.
        </p>
        <div className="source-review-checks">
          <label>
            <input
              type="checkbox"
              checked={includePoc}
              onChange={(event) => setIncludePoc(event.target.checked)}
            />
            Include PoC text (redacted)
          </label>
          <label>
            <input
              type="checkbox"
              checked={includeEvidence}
              onChange={(event) => setIncludeEvidence(event.target.checked)}
            />
            Include evidence bodies (redacted)
          </label>
        </div>
        {(includePoc || includeEvidence) && (
          <p className="campaign-limit">
            Redaction is pattern-based. Read the bundle before sharing it.
          </p>
        )}
        <button
          type="button"
          className="button button-outline"
          disabled={pending || !finding.available}
          aria-describedby={
            !finding.available
              ? `bundle-why-${finding.research_key}`
              : undefined
          }
          onClick={bundle}
        >
          {pending ? "Working…" : "Generate bundle"}
        </button>
        {!finding.available && (
          <DisabledReason id={`bundle-why-${finding.research_key}`}>
            The finding records are unavailable, so there is nothing to bundle.
            Reopen the source arena to restore them.
          </DisabledReason>
        )}
      </div>
      {finding.bundles.length ? (
        <ul className="source-review-history campaign-bundles">
          {finding.bundles.map((item, index) => (
            <li key={`${item.bundle_digest}-${index}`}>
              <a
                href={`${CAMPAIGN_API}/${campaignId}/bundles/${encodeURIComponent(item.bundle_digest)}`}
                download={`disclosure-bundle-${item.bundle_digest.slice(7, 19)}.json`}
              >
                <code>{item.bundle_digest}</code>
              </a>
              <p>
                {item.include_poc ? "PoC text included" : "PoC digest only"} ·{" "}
                {item.include_evidence
                  ? "evidence bodies included"
                  : "evidence digests only"}{" "}
                · {item.bytes} bytes
              </p>
              {item.unresolved_artifacts > 0 && (
                <p className="source-review-cut">
                  {item.unresolved_artifacts} artifact
                  {item.unresolved_artifacts === 1 ? "" : "s"} did not resolve
                </p>
              )}
              <span>
                {formatObserved(item.at)} · {item.actor}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p>No bundle generated yet.</p>
      )}
      {message && (
        <p className="source-review-error" role="alert">
          {message}
        </p>
      )}
      {saved && <p role="status">{saved}</p>}
    </dialog>
  );
}

export function Campaign({ id }: { id: string }) {
  const valid = /^[0-9a-f]{32}$/.test(id);
  const { value, error, loading, refresh } = useWorkspaceData<CampaignSummary>(
    valid ? `${CAMPAIGN_API}/${id}` : `${CAMPAIGN_API}/invalid`,
  );
  const [override, setOverride] = useState<CampaignSummary | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => setOverride(null), [value]);
  const summary = override ?? value;
  const selected = summary?.findings.find((item) => item.research_key === open);
  // The first lines are specific reasons; the last is the standing limits note.
  const reasons = summary ? summary.unresolved.slice(0, -1) : [];
  const standing = summary
    ? summary.unresolved[summary.unresolved.length - 1]
    : "";
  return (
    <>
      <PageHead
        overline="WORKSPACE / RESEARCH / CAMPAIGNS"
        title={summary?.name ?? "Campaign"}
        subtitle={summary ? `Product: ${summary.product}` : ""}
        action={
          <a
            className="button button-outline"
            href="/console/research/campaigns"
          >
            All campaigns
          </a>
        }
      />
      <p className="source-review-caption">{CAPTION}</p>
      {error && !value ? (
        <ErrorState message={error} refresh={refresh} />
      ) : loading && !summary ? (
        <Loading />
      ) : summary ? (
        <>
          <Panel eyebrow="01 / CAMPAIGN" title="Campaign">
            <dl className="source-review-facts source-review-identity">
              <div>
                <dt>Campaign</dt>
                <dd>
                  <code>{summary.campaign_id}</code>
                  <small>
                    {formatObserved(summary.created_at)} · {summary.actor}
                  </small>
                </dd>
              </div>
              <div>
                <dt>Disclosure states</dt>
                <dd>
                  {STATES.map((state) => (
                    <span key={state} className="campaign-count">
                      {STATE_LABEL[state]} {summary.by_disclosure_state[state]}
                    </span>
                  ))}
                </dd>
              </div>
              {summary.note && (
                <div>
                  <dt>Note</dt>
                  <dd>{summary.note}</dd>
                </div>
              )}
            </dl>
            <div
              className={`source-review-banner${reasons.length ? " incomplete" : ""}`}
            >
              <strong>
                {reasons.length
                  ? "Open points in this campaign"
                  : "Limits of this campaign"}
              </strong>
              <ul>
                {[...reasons, standing].map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          </Panel>
          <Panel eyebrow="02 / FINDINGS" title="Finding groups">
            {summary.findings.length ? (
              <div className="source-review-scroll">
                <table className="source-review-table campaign-findings">
                  <caption>{CAPTION}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Finding group</th>
                      <th scope="col">Evidence outcome</th>
                      <th scope="col">Identities by verdict</th>
                      <th scope="col">Disclosure state</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.findings.map((finding) => (
                      <tr key={finding.research_key}>
                        <th scope="row" data-label="Finding group">
                          <button
                            type="button"
                            aria-haspopup="dialog"
                            onClick={(event) => {
                              opener.current = event.currentTarget;
                              setOpen(finding.research_key);
                            }}
                          >
                            {finding.title || finding.research_key}
                          </button>
                          <small>
                            {finding.research_key} · {finding.cwe || "no CWE"}
                          </small>
                        </th>
                        <td data-label="Evidence outcome">
                          <span className="source-review-machine">
                            {outcomeText(finding)}
                          </span>
                        </td>
                        <td data-label="Identities by verdict">
                          <span>
                            Affected {finding.identities.affected.length}
                          </span>
                          <small>
                            Not observed under controls{" "}
                            {
                              finding.identities.not_observed_under_controls
                                .length
                            }{" "}
                            · unknown {finding.identities.unknown.length}
                          </small>
                        </td>
                        <td data-label="Disclosure state">
                          <StateBadge state={finding.disclosure.state} />
                          {finding.state_supported_by_evidence === false && (
                            <small className="source-review-cut">
                              Not supported by recorded evidence
                            </small>
                          )}
                          {finding.bundles_total > 0 && (
                            <small>
                              {finding.bundles_total} bundle
                              {finding.bundles_total === 1 ? "" : "s"}
                            </small>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty
                title="No finding groups"
                detail="Add a finding id below. Its linked variants come with it."
              />
            )}
            <AddFinding
              campaignId={summary.campaign_id}
              onChanged={setOverride}
            />
          </Panel>
          {selected && (
            <FindingDrawer
              key={selected.research_key}
              campaignId={summary.campaign_id}
              finding={selected}
              onChanged={setOverride}
              onClose={() => {
                setOpen(null);
                opener.current?.focus();
              }}
            />
          )}
        </>
      ) : null}
    </>
  );
}
