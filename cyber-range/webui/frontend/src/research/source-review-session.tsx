import { useEffect, useId, useRef, useState } from "react";
import type React from "react";
import { postJson } from "../api";
import type {
  ReviewState,
  SiteReview,
  SourceReviewFixLink,
  SourceReviewFixLinkSummary,
  SourceReviewPattern,
  SourceReviewSite,
  SourceReviewSitesPage,
  SourceReviewSummary,
} from "../types";
import {
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  formatObserved,
  useWorkspaceData,
} from "../ui";
import { CaptureBadge, REVIEW_API } from "./source-review";
import "./source-review.css";

const PAGE_SIZE = 50;
const STATE_LABEL: Record<ReviewState, string> = {
  unreviewed: "Unreviewed",
  in_review: "In review",
  dismissed: "Dismissed",
  candidate: "Candidate",
};
const STATES = Object.keys(STATE_LABEL) as ReviewState[];
// Shown with every site table. It is fixed text, not data.
const CAPTION =
  "Statuses and classifications are syntactic candidates, not findings.";

type Query = {
  pattern: string;
  offset: number;
  status: string;
  classification: string;
  review_state: string;
  file_prefix: string;
};
const FILTERS = [
  "status",
  "classification",
  "review_state",
  "file_prefix",
] as const;

function queryFromUrl(): Query {
  const params = new URLSearchParams(window.location.search);
  const offset = Number(params.get("offset"));
  return {
    pattern: params.get("pattern") || "",
    offset: Number.isInteger(offset) && offset > 0 ? offset : 0,
    status: params.get("status") || "",
    classification: params.get("classification") || "",
    review_state: params.get("review_state") || "",
    file_prefix: params.get("file_prefix") || "",
  };
}

function queryString(query: Query) {
  const params = new URLSearchParams({ pattern: query.pattern });
  if (query.offset) params.set("offset", String(query.offset));
  for (const key of FILTERS) if (query[key]) params.set(key, query[key]);
  return params.toString();
}

function ReviewBadge({ state }: { state: ReviewState }) {
  return (
    <span className={`source-review-state source-review-state-${state}`}>
      {STATE_LABEL[state]}
    </span>
  );
}

function Machine({ site }: { site: SourceReviewSite }) {
  return (
    <>
      <span className="source-review-machine">{site.status}</span>
      <small>{site.classification}</small>
    </>
  );
}

function PatternTable({
  patterns,
  selected,
  onSelect,
}: {
  patterns: SourceReviewPattern[];
  selected: string;
  onSelect: (pattern: string) => void;
}) {
  return (
    <div className="source-review-scroll">
      <table className="source-review-table source-review-patterns">
        <caption className="visually-hidden">
          Patterns in this session with match counts and review progress
        </caption>
        <thead>
          <tr>
            <th scope="col">Pattern</th>
            <th scope="col">Matches</th>
            <th scope="col">Count is</th>
            <th scope="col">Retained</th>
            {STATES.map((state) => (
              <th scope="col" key={state}>
                {STATE_LABEL[state]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {patterns.map((pattern) => (
            <tr
              key={pattern.pattern}
              className={pattern.pattern === selected ? "selected" : ""}
            >
              <th scope="row" data-label="Pattern">
                <button
                  type="button"
                  aria-pressed={pattern.pattern === selected}
                  onClick={() => onSelect(pattern.pattern)}
                >
                  {pattern.pattern}
                </button>
                {pattern.truncation_notes.map((note) => (
                  <small key={note}>{note}</small>
                ))}
              </th>
              <td data-label="Matches">{pattern.total_matches ?? "—"}</td>
              <td data-label="Count is">
                {pattern.total_matches_complete === null ? (
                  "—"
                ) : pattern.total_matches_complete ? (
                  "exact"
                ) : (
                  <strong className="source-review-lower-bound">
                    lower bound
                  </strong>
                )}
              </td>
              <td data-label="Retained">{pattern.retained_sites ?? "—"}</td>
              {STATES.map((state) => (
                <td data-label={STATE_LABEL[state]} key={state}>
                  {pattern.by_review_state[state] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function History({ site }: { site: SourceReviewSite }) {
  if (!site.review_history.length)
    return <p>No review recorded. This site is unreviewed.</p>;
  return (
    <>
      <ol className="source-review-history">
        {site.review_history.map((entry, index) => (
          <li key={`${entry.at}-${index}`}>
            <ReviewBadge state={entry.state} />
            <span>
              {entry.actor} · {entry.at ? formatObserved(entry.at) : "—"}
            </span>
            {entry.note && <p>{entry.note}</p>}
            {entry.finding_id && (
              <a href={`/api/console/findings/${entry.finding_id}`}>
                Finding group {entry.finding_id}
              </a>
            )}
          </li>
        ))}
      </ol>
      {site.review_history_total > site.review_history.length && (
        <p>
          Showing the newest {site.review_history.length} of{" "}
          {site.review_history_total} entries.
        </p>
      )}
    </>
  );
}

function SiteDrawer({
  sessionId,
  site,
  onClose,
  onSaved,
  onFixLink,
}: {
  sessionId: string;
  site: SourceReviewSite;
  onClose: () => void;
  onSaved: (site: SourceReviewSite) => void;
  onFixLink: (linkId: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const noteHelp = useId();
  const [state, setState] = useState<ReviewState>(
    site.review.state === "unreviewed" ? "in_review" : site.review.state,
  );
  const [note, setNote] = useState("");
  const [finding, setFinding] = useState("");
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
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setSaved("");
    if (state === "dismissed" && note.trim().length < 10) {
      setMessage("Dismissing a site needs a note of at least 10 characters.");
      return;
    }
    if (finding && !/^[0-9a-f]{12}$/.test(finding.trim())) {
      setMessage("A finding id is 12 lowercase hex characters.");
      return;
    }
    setPending(true);
    setMessage("");
    try {
      const result = await postJson<{
        review: SiteReview;
        review_history: SiteReview[];
        review_history_total: number;
      }>(
        `${REVIEW_API}/${sessionId}/sites/${encodeURIComponent(site.site_key)}/review`,
        {
          state,
          note: note.trim(),
          ...(state === "candidate" && finding.trim()
            ? { finding_id: finding.trim() }
            : {}),
        },
      );
      onSaved({ ...site, ...result });
      setNote("");
      setFinding("");
      setSaved(
        `Recorded as ${STATE_LABEL[result.review.state].toLowerCase()}.`,
      );
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "The review could not be saved",
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
          <span className="eyebrow">SITE</span>
          <h2 id={titleId}>
            {site.file}:{site.line}
          </h2>
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
          <dt>Machine status</dt>
          <dd>{site.status}</dd>
        </div>
        <div>
          <dt>Classification reason</dt>
          <dd>{site.classification}</dd>
        </div>
        <div>
          <dt>Operator review state</dt>
          <dd>
            <ReviewBadge state={site.review.state} />
          </dd>
        </div>
      </dl>
      <h3>Evidence line</h3>
      <pre className="source-review-evidence">{site.evidence}</pre>
      {site.evidence_clipped && (
        <p>The line was longer than 160 bytes and is cut here.</p>
      )}
      <h3>Fix links touching this file</h3>
      {site.fix_links_touching_file.length ? (
        <ul className="source-review-touching">
          {site.fix_links_touching_file.map((link) => (
            <li key={link.link_id}>
              <button
                type="button"
                className="subtle-link"
                onClick={() => {
                  dialog.current?.close();
                  onFixLink(link.link_id);
                }}
              >
                Same file as fix {link.link_id} ({link.label})
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p>No declared fix link changed this file.</p>
      )}
      <form className="source-review-form" onSubmit={save}>
        <fieldset>
          <legend>Record a review state</legend>
          <div className="source-review-checks">
            {(["in_review", "dismissed", "candidate"] as const).map((item) => (
              <label key={item}>
                <input
                  type="radio"
                  name="review-state"
                  value={item}
                  checked={state === item}
                  onChange={() => setState(item)}
                />
                {STATE_LABEL[item]}
              </label>
            ))}
          </div>
        </fieldset>
        <label>
          Note{state === "dismissed" ? " (required)" : " (optional)"}
          <textarea
            rows={3}
            maxLength={2000}
            value={note}
            aria-describedby={noteHelp}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <p id={noteHelp}>
          {state === "dismissed"
            ? "Dismissed means you judged this site not worth probing. It does not mean the site is safe. Say why, in at least 10 characters."
            : state === "candidate"
              ? "A candidate is worth probing. It is not a finding until a probe confirms it."
              : "In review means you are still looking at this site."}
        </p>
        {state === "candidate" && (
          <label>
            Linked finding id (optional)
            <input
              value={finding}
              maxLength={12}
              onChange={(event) => setFinding(event.target.value)}
              placeholder="12 hex characters"
              spellCheck={false}
            />
          </label>
        )}
        <button className="button button-gold" disabled={pending}>
          {pending ? "Saving…" : "Save review state"}
        </button>
        {message && (
          <p className="source-review-error" role="alert">
            {message}
          </p>
        )}
        {saved && <p role="status">{saved}</p>}
        <p>
          Each save adds an entry. Earlier entries and the machine fields are
          never changed.
        </p>
      </form>
      <h3>Review history</h3>
      <History site={site} />
    </dialog>
  );
}

function SiteTable({
  sessionId,
  summary,
  query,
  onQuery,
  onChanged,
  onFixLink,
}: {
  sessionId: string;
  summary: SourceReviewPattern;
  query: Query;
  onQuery: (query: Query) => void;
  onChanged: () => void;
  onFixLink: (linkId: string) => void;
}) {
  const { value, error, loading, refresh } =
    useWorkspaceData<SourceReviewSitesPage>(
      `${REVIEW_API}/${sessionId}/sites?${queryString(query)}&limit=${PAGE_SIZE}`,
    );
  const [open, setOpen] = useState<SourceReviewSite | null>(null);
  const [prefix, setPrefix] = useState(query.file_prefix);
  const opener = useRef<HTMLElement | null>(null);
  const [jump, setJump] = useState("");
  useEffect(() => setPrefix(query.file_prefix), [query.file_prefix]);
  const total = value?.filtered_total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // Describe the page that is on screen, not the one still loading.
  const shown = value?.offset ?? query.offset;
  const page = Math.floor(shown / PAGE_SIZE) + 1;
  const goto = (target: number) =>
    onQuery({
      ...query,
      offset: (Math.min(Math.max(target, 1), pages) - 1) * PAGE_SIZE,
    });
  const filter = (key: (typeof FILTERS)[number], next: string) =>
    onQuery({ ...query, [key]: next, offset: 0 });
  return (
    <>
      <form
        className="source-review-filters"
        onSubmit={(event) => {
          event.preventDefault();
          filter("file_prefix", prefix.trim());
        }}
      >
        <label>
          Machine status
          <select
            value={query.status}
            onChange={(event) => filter("status", event.target.value)}
          >
            <option value="">Any</option>
            {Object.entries(summary.by_status).map(([name, count]) => (
              <option key={name} value={name}>
                {name} ({count})
              </option>
            ))}
          </select>
        </label>
        <label>
          Classification reason
          <select
            value={query.classification}
            onChange={(event) => filter("classification", event.target.value)}
          >
            <option value="">Any</option>
            {Object.entries(summary.by_classification).map(([name, count]) => (
              <option key={name} value={name}>
                {name} ({count})
              </option>
            ))}
          </select>
        </label>
        <label>
          Review state
          <select
            value={query.review_state}
            onChange={(event) => filter("review_state", event.target.value)}
          >
            <option value="">Any</option>
            {STATES.map((state) => (
              <option key={state} value={state}>
                {STATE_LABEL[state]}
              </option>
            ))}
          </select>
        </label>
        <label>
          File path starts with
          <input
            value={prefix}
            maxLength={256}
            onChange={(event) => setPrefix(event.target.value)}
            spellCheck={false}
          />
        </label>
        <button className="button button-outline">Apply path</button>
      </form>
      {error ? (
        <ErrorState message={error} refresh={refresh} />
      ) : loading && !value ? (
        <Loading />
      ) : value?.sites.length ? (
        <div className="source-review-scroll" aria-busy={loading}>
          <table className="source-review-table source-review-sites">
            <caption>{CAPTION}</caption>
            <thead>
              <tr>
                <th scope="col">Site</th>
                <th scope="col">Machine status and reason</th>
                <th scope="col">Evidence line</th>
                <th scope="col">Review state</th>
              </tr>
            </thead>
            <tbody>
              {value.sites.map((site) => (
                <tr key={site.site_key}>
                  <th scope="row" data-label="Site">
                    <button
                      type="button"
                      aria-haspopup="dialog"
                      onClick={(event) => {
                        opener.current = event.currentTarget;
                        setOpen(site);
                      }}
                    >
                      {site.file}:{site.line}
                    </button>
                    {site.fix_links_touching_file.map((link) => (
                      <small key={link.link_id}>
                        Same file as fix {link.link_id}
                      </small>
                    ))}
                  </th>
                  <td data-label="Machine status and reason">
                    <Machine site={site} />
                  </td>
                  <td data-label="Evidence line">
                    <code>{site.evidence}</code>
                    {site.evidence_clipped && <small>line cut</small>}
                  </td>
                  <td data-label="Review state">
                    <ReviewBadge state={site.review.state} />
                    {site.review.note && <small>{site.review.note}</small>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty
          title="No sites on this page"
          detail={
            total
              ? "This page is past the end of the filtered sites."
              : "No retained site matches these filters. This says nothing about the code outside the retained matches."
          }
          action={
            query.offset > 0 ? (
              <button
                type="button"
                className="button button-outline"
                onClick={() => goto(1)}
              >
                First page
              </button>
            ) : undefined
          }
        />
      )}
      {value && (
        <nav className="source-review-paging" aria-label="Site pages">
          <span role="status">
            {total
              ? `Sites ${Math.min(shown + 1, total)}–${Math.min(shown + value.sites.length, total)} of ${total}`
              : "0 sites"}
            {total !== value.pattern_total &&
              ` (filtered from ${value.pattern_total})`}{" "}
            · page {page} of {pages}
          </span>
          <div>
            <button
              type="button"
              disabled={loading || page <= 1}
              onClick={() => goto(1)}
            >
              First
            </button>
            <button
              type="button"
              disabled={loading || page <= 1}
              onClick={() => goto(page - 1)}
            >
              ← Previous
            </button>
            <button
              type="button"
              disabled={loading || value.next_offset === null}
              onClick={() => goto(page + 1)}
            >
              Next →
            </button>
            <button
              type="button"
              disabled={loading || page >= pages}
              onClick={() => goto(pages)}
            >
              Last
            </button>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const target = Number(jump);
              if (Number.isInteger(target) && target >= 1) goto(target);
              setJump("");
            }}
          >
            <label>
              Go to page
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={jump}
                onChange={(event) => setJump(event.target.value)}
              />
            </label>
            <button>Go</button>
          </form>
        </nav>
      )}
      {open && (
        <SiteDrawer
          key={open.site_key}
          sessionId={sessionId}
          site={open}
          onClose={() => {
            setOpen(null);
            opener.current?.focus();
          }}
          onSaved={(site) => {
            setOpen(site);
            refresh();
            onChanged();
          }}
          onFixLink={onFixLink}
        />
      )}
    </>
  );
}

type PatchCall = { call: string; context: string; line: string };
type PatchHunk = { file: string; added_perm_calls: PatchCall[] };
type DeltaSite = {
  file: string;
  side: string;
  context: string;
  calls: string[];
};

function Cut({ note }: { note: string }) {
  return (
    <p className="source-review-cut" role="note">
      <strong>Output was cut.</strong> {note || "No reason was recorded."}
    </p>
  );
}

function FixLinkDetail({
  sessionId,
  linkId,
}: {
  sessionId: string;
  linkId: string;
}) {
  const { value, error, loading, refresh } =
    useWorkspaceData<SourceReviewFixLink>(
      `${REVIEW_API}/${sessionId}/fix-links/${encodeURIComponent(linkId)}`,
    );
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (loading || !value) return <Loading />;
  const patch = value.fix_lookup.data as {
    subject?: string;
    check_line?: string;
    files_changed?: string[];
    hunks?: PatchHunk[];
    counts_complete?: boolean;
  };
  const delta = value.layer_diff.data as {
    paths?: string[];
    files?: Record<string, { added: number; removed: number }>;
    sites?: DeltaSite[];
    counts_complete?: boolean;
  };
  const files = Object.entries(delta.files || {});
  return (
    <div className="source-review-fix-detail">
      <p>
        <span
          className={`status status-${value.counts_complete ? "success" : "warning"}`}
        >
          <i aria-hidden="true" />
          {value.counts_complete ? "Counts complete" : "Counts incomplete"}
        </span>
      </p>
      <dl className="source-review-facts">
        <div>
          <dt>Fix commit</dt>
          <dd>
            <code>{value.fix_ref}</code>
          </dd>
        </div>
        <div>
          <dt>Affected</dt>
          <dd>
            <code>{value.affected_ref}</code>
            {value.requested_affected_ref !== value.affected_ref && (
              <small>requested as {value.requested_affected_ref}</small>
            )}
          </dd>
        </div>
        <div>
          <dt>Fixed</dt>
          <dd>
            <code>{value.fixed_ref}</code>
            {value.requested_fixed_ref !== value.fixed_ref && (
              <small>requested as {value.requested_fixed_ref}</small>
            )}
          </dd>
        </div>
      </dl>
      <h4>Patch facts</h4>
      {value.fix_lookup.truncation.truncated && (
        <Cut note={value.fix_lookup.truncation.note} />
      )}
      <p>{patch.subject || "No commit subject retained."}</p>
      <p>
        <strong>Check summary:</strong> {patch.check_line || "—"}
      </p>
      <p>
        Files changed
        {patch.counts_complete === false ? " (list may be incomplete)" : ""}:
      </p>
      <ul className="source-review-files">
        {(patch.files_changed || []).map((file) => (
          <li key={file}>
            <code>{file}</code>
          </li>
        ))}
      </ul>
      {(patch.hunks || []).some((hunk) => hunk.added_perm_calls.length) && (
        <details>
          <summary>Permission calls added by the fix</summary>
          <ul className="source-review-files">
            {(patch.hunks || []).flatMap((hunk) =>
              hunk.added_perm_calls.map((call, index) => (
                <li key={`${hunk.file}-${index}`}>
                  <code>{hunk.file}</code> · {call.context}
                  <pre className="source-review-evidence">{call.line}</pre>
                </li>
              )),
            )}
          </ul>
        </details>
      )}
      <h4>Permission-call delta, affected to fixed</h4>
      {value.layer_diff.truncation.truncated && (
        <Cut note={value.layer_diff.truncation.note} />
      )}
      {files.length ? (
        <div className="source-review-scroll">
          <table className="source-review-table source-review-delta">
            <caption className="visually-hidden">
              Permission calls added and removed per file
            </caption>
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Added</th>
                <th scope="col">Removed</th>
              </tr>
            </thead>
            <tbody>
              {files.map(([file, counts]) => (
                <tr key={file}>
                  <th scope="row" data-label="File">
                    <code>{file}</code>
                  </th>
                  <td data-label="Added">
                    {delta.counts_complete === false ? "at least " : ""}
                    {counts.added}
                  </td>
                  <td data-label="Removed">
                    {delta.counts_complete === false ? "at least " : ""}
                    {counts.removed}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>
          No changed file in the compared paths
          {delta.counts_complete === false ? " within the retained output" : ""}
          . Compared paths: {(delta.paths || []).join(", ") || "—"}.
        </p>
      )}
      {!!delta.sites?.length && (
        <details>
          <summary>Added permission calls by context</summary>
          <ul className="source-review-files">
            {delta.sites.map((site, index) => (
              <li key={index}>
                <code>{site.file}</code> · {site.context} ·{" "}
                {site.calls.join(", ")}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p>
        A site in the same file as a fix is not thereby the same flaw. Runtime
        affected-versus-fixed evidence lives with the linked finding group.
      </p>
    </div>
  );
}

function FixLinks({
  sessionId,
  links,
  open,
  onOpen,
}: {
  sessionId: string;
  links: SourceReviewFixLinkSummary[];
  open: string;
  onOpen: (linkId: string) => void;
}) {
  if (!links.length)
    return (
      <Empty
        title="No fix links"
        detail="Fix links are declared when a session is created."
      />
    );
  return (
    <ul className="source-review-links">
      {links.map((link) => (
        <li key={link.link_id} id={`fix-link-${link.link_id}`}>
          <div>
            <strong>
              {link.link_id} · {link.label}
            </strong>
            {link.advisory_id && <small>{link.advisory_id}</small>}
            {link.counts_complete === false && (
              <span className="status status-warning">
                <i aria-hidden="true" />
                Counts incomplete
              </span>
            )}
          </div>
          <button
            type="button"
            className="button button-outline"
            aria-expanded={open === link.link_id}
            onClick={() => onOpen(open === link.link_id ? "" : link.link_id)}
          >
            {open === link.link_id ? "Hide patch facts" : "Show patch facts"}
          </button>
          {open === link.link_id && (
            <FixLinkDetail sessionId={sessionId} linkId={link.link_id} />
          )}
        </li>
      ))}
    </ul>
  );
}

function Header({ value }: { value: SourceReviewSummary }) {
  return (
    <dl className="source-review-facts source-review-identity">
      <div>
        <dt>Repository</dt>
        <dd>
          {value.repo_label || "Unlabelled checkout"}
          <code title="Repository identity">{value.repo_id}</code>
        </dd>
      </div>
      <div>
        <dt>Commit</dt>
        <dd>
          <code>{value.commit_sha}</code>
          {value.requested_ref !== value.commit_sha && (
            <small>requested as {value.requested_ref}</small>
          )}
        </dd>
      </div>
      <div>
        <dt>Path scope</dt>
        <dd>
          {value.path_scope.map((path) => (
            <code key={path}>{path}</code>
          ))}
        </dd>
      </div>
      <div>
        <dt>Snapshot digest</dt>
        <dd>
          {value.snapshot_digest ? (
            <code>{value.snapshot_digest}</code>
          ) : (
            "No snapshot"
          )}
        </dd>
      </div>
      <div>
        <dt>Created</dt>
        <dd>
          {formatObserved(value.created_at)} · {value.actor}
        </dd>
      </div>
    </dl>
  );
}

export function SourceReviewSession({ id }: { id: string }) {
  const sessionId = encodeURIComponent(id);
  const { value, error, loading, refresh } =
    useWorkspaceData<SourceReviewSummary>(`${REVIEW_API}/${sessionId}`);
  const [query, setQuery] = useState<Query>(queryFromUrl);
  const [link, setLink] = useState("");
  const capturing = value?.capture_state === "capturing";
  useEffect(() => {
    if (!capturing) return;
    const timer = window.setTimeout(refresh, 3000);
    return () => window.clearTimeout(timer);
  });
  const selected =
    value?.patterns.find((item) => item.pattern === query.pattern) ||
    value?.patterns[0];
  function update(next: Query) {
    setQuery(next);
    const url = new URL(window.location.href);
    url.search = queryString(next);
    window.history.replaceState(null, "", url);
  }
  function showLink(linkId: string) {
    setLink(linkId);
    if (linkId)
      window.setTimeout(
        () =>
          document
            .getElementById(`fix-link-${linkId}`)
            ?.querySelector("button")
            ?.focus(),
        0,
      );
  }
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (loading && !value) return <Loading />;
  if (!value) return null;
  return (
    <>
      <PageHead
        overline="WORKSPACE / RESEARCH / SOURCE REVIEW"
        title={value.name}
        subtitle="A frozen inventory of syntactic candidates at one commit."
        action={
          <a className="button button-outline" href="/console/research/review">
            All sessions
          </a>
        }
      />
      <Panel
        eyebrow="01 / TARGET"
        title="Session"
        aside={
          <CaptureBadge state={value.capture_state} complete={value.complete} />
        }
      >
        <Header value={value} />
        {/* No close control: an incomplete inventory must stay visible. */}
        <div
          className={`source-review-banner${value.complete ? "" : " incomplete"}`}
          role="note"
          aria-label={
            value.complete ? "Limits of this inventory" : "Incomplete inventory"
          }
        >
          <strong>
            {value.complete
              ? "Limits of this inventory"
              : value.capture_state === "capturing"
                ? "Capture in progress"
                : value.capture_state === "failed"
                  ? "Capture failed"
                  : "This inventory is incomplete"}
          </strong>
          <ul>
            {value.unresolved.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      </Panel>
      <Panel eyebrow="02 / PATTERNS" title="Patterns">
        <PatternTable
          patterns={value.patterns}
          selected={selected?.pattern || ""}
          onSelect={(pattern) =>
            update({
              pattern,
              offset: 0,
              status: "",
              classification: "",
              review_state: "",
              file_prefix: "",
            })
          }
        />
      </Panel>
      <Panel
        eyebrow="03 / SITES"
        title={selected ? `Sites · ${selected.pattern}` : "Sites"}
      >
        {value.capture_state === "complete" && selected ? (
          <SiteTable
            key={selected.pattern}
            sessionId={sessionId}
            summary={selected}
            query={{ ...query, pattern: selected.pattern }}
            onQuery={update}
            onChanged={refresh}
            onFixLink={showLink}
          />
        ) : (
          <Empty
            title="No sites to show"
            detail={
              capturing
                ? "The inventory is still being captured. This page checks again every few seconds."
                : "This session has no inventory."
            }
          />
        )}
      </Panel>
      <Panel eyebrow="04 / FIX LINKS" title="Fix links">
        <FixLinks
          sessionId={sessionId}
          links={value.fix_links}
          open={link}
          onOpen={showLink}
        />
      </Panel>
    </>
  );
}
