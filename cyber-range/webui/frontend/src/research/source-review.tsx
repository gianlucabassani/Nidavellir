import { useState } from "react";
import type React from "react";
import { postJson } from "../api";
import type { SourceReviewListItem, SourceReviewSummary } from "../types";
import {
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  formatObserved,
  useWorkspaceData,
} from "../ui";
import "./source-review.css";

export const REVIEW_API = "/api/console/research/review-sessions";

export const PATTERNS = [
  "unscoped-queryset",
  "bare-auth-view",
  "bulk-permission",
  "half-composed-check",
  "unguarded-verb",
  "field-validation",
  "privilege-flags",
  "template-context",
  "mutation-order",
] as const;

// A session is "complete" only when every count is exact and every match was
// retained. Anything else is shown as incomplete, never as a quieter state.
export function CaptureBadge({
  state,
  complete,
}: {
  state: SourceReviewListItem["capture_state"];
  complete: boolean;
}) {
  const [tone, label] =
    state === "capturing"
      ? ["warning", "Capturing"]
      : state === "failed"
        ? ["danger", "Capture failed"]
        : complete
          ? ["success", "Complete"]
          : ["warning", "Incomplete"];
  return (
    <span className={`status status-${tone}`}>
      <i aria-hidden="true" />
      {label}
    </span>
  );
}

function progressText(item: SourceReviewListItem) {
  if (!item.review_progress) return "No inventory";
  const { total_sites, by_review_state } = item.review_progress;
  return `${total_sites - by_review_state.unreviewed} of ${total_sites} sites reviewed`;
}

type LinkDraft = {
  label: string;
  fix_ref: string;
  affected_ref: string;
  fixed_ref: string;
  advisory_id: string;
};
const EMPTY_LINK: LinkDraft = {
  label: "",
  fix_ref: "",
  affected_ref: "",
  fixed_ref: "",
  advisory_id: "",
};

function NewSession() {
  const [name, setName] = useState("");
  const [ref, setRef] = useState("");
  const [patterns, setPatterns] = useState<string[]>([...PATTERNS]);
  const [scope, setScope] = useState("");
  const [links, setLinks] = useState<LinkDraft[]>([]);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  function setLink(index: number, field: keyof LinkDraft, value: string) {
    setLinks(
      links.map((link, position) =>
        position === index ? { ...link, [field]: value } : link,
      ),
    );
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    if (!patterns.length) {
      setMessage("Choose at least one pattern.");
      return;
    }
    setPending(true);
    setMessage("");
    const paths = scope
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    try {
      const created = await postJson<SourceReviewSummary>(REVIEW_API, {
        name: name.trim(),
        ref: ref.trim(),
        patterns,
        ...(paths.length ? { path_scope: paths } : {}),
        ...(links.length
          ? {
              fix_links: links.map((link) => ({
                label: link.label.trim(),
                fix_ref: link.fix_ref.trim(),
                affected_ref: link.affected_ref.trim(),
                fixed_ref: link.fixed_ref.trim(),
                ...(link.advisory_id.trim()
                  ? { advisory_id: link.advisory_id.trim() }
                  : {}),
              })),
            }
          : {}),
      });
      window.location.assign(
        `/console/research/review/${encodeURIComponent(created.session_id)}`,
      );
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "The session could not be created",
      );
      setPending(false);
    }
  }
  return (
    <form className="source-review-form" onSubmit={submit}>
      <p>
        A session freezes one inventory of the research checkout at one commit.
        The name, commit and scope cannot be changed afterwards.
      </p>
      <label>
        Session name
        <input
          required
          maxLength={120}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        Commit, tag or branch
        <input
          required
          maxLength={64}
          value={ref}
          onChange={(event) => setRef(event.target.value)}
          placeholder="A full commit SHA is recorded either way"
          autoCapitalize="none"
          spellCheck={false}
        />
      </label>
      <fieldset>
        <legend>Patterns</legend>
        <div className="source-review-checks">
          {PATTERNS.map((pattern) => (
            <label key={pattern}>
              <input
                type="checkbox"
                checked={patterns.includes(pattern)}
                onChange={(event) =>
                  setPatterns(
                    event.target.checked
                      ? PATTERNS.filter(
                          (item) => item === pattern || patterns.includes(item),
                        )
                      : patterns.filter((item) => item !== pattern),
                  )
                }
              />
              {pattern}
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        Path scope (optional, one path per line, at most 8)
        <textarea
          rows={3}
          value={scope}
          onChange={(event) => setScope(event.target.value)}
          placeholder="Leave empty for the default source directories"
          spellCheck={false}
        />
      </label>
      <fieldset>
        <legend>Fix links (optional)</legend>
        {links.map((link, index) => (
          <div className="source-review-link-draft" key={index}>
            <label>
              Label
              <input
                required
                maxLength={32}
                value={link.label}
                onChange={(event) =>
                  setLink(index, "label", event.target.value)
                }
              />
            </label>
            <label>
              Fix commit
              <input
                required
                maxLength={64}
                value={link.fix_ref}
                onChange={(event) =>
                  setLink(index, "fix_ref", event.target.value)
                }
                spellCheck={false}
              />
            </label>
            <label>
              Affected ref
              <input
                required
                maxLength={64}
                value={link.affected_ref}
                onChange={(event) =>
                  setLink(index, "affected_ref", event.target.value)
                }
                spellCheck={false}
              />
            </label>
            <label>
              Fixed ref
              <input
                required
                maxLength={64}
                value={link.fixed_ref}
                onChange={(event) =>
                  setLink(index, "fixed_ref", event.target.value)
                }
                spellCheck={false}
              />
            </label>
            <label>
              Advisory id (optional)
              <input
                maxLength={32}
                value={link.advisory_id}
                onChange={(event) =>
                  setLink(index, "advisory_id", event.target.value)
                }
              />
            </label>
            <button
              type="button"
              className="button button-outline"
              onClick={() =>
                setLinks(links.filter((_, position) => position !== index))
              }
            >
              Remove fix link {index + 1}
            </button>
          </div>
        ))}
        {links.length < 16 && (
          <button
            type="button"
            className="button button-outline"
            onClick={() => setLinks([...links, { ...EMPTY_LINK }])}
          >
            Add a fix link
          </button>
        )}
      </fieldset>
      <button className="button button-gold" disabled={pending}>
        {pending ? "Creating…" : "Create session and capture"}
      </button>
      {message && (
        <p className="source-review-error" role="alert">
          {message}
        </p>
      )}
    </form>
  );
}

export function SourceReviewSessions() {
  const [before, setBefore] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const { value, error, loading, refresh } = useWorkspaceData<{
    sessions: SourceReviewListItem[];
    next_before: number | null;
  }>(`${REVIEW_API}${before ? `?before=${before}` : ""}`);
  return (
    <>
      <PageHead
        overline="WORKSPACE / RESEARCH / SOURCE REVIEW"
        title="Source review"
        subtitle="Frozen inventories of syntactic candidates, reviewed site by site."
        action={
          <button
            type="button"
            className="button button-gold"
            aria-expanded={creating}
            onClick={() => setCreating(!creating)}
          >
            {creating ? "Close form" : "New session"}
          </button>
        }
      />
      <p className="source-review-caption">
        Candidates are syntactic matches, not findings. No review state shows
        that a site is safe or that a pattern has been exhausted.
      </p>
      {creating && (
        <Panel eyebrow="NEW" title="New review session">
          <NewSession />
        </Panel>
      )}
      <Panel
        eyebrow="SESSIONS"
        title="Review sessions"
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
        ) : value?.sessions.length ? (
          <ul className="source-review-sessions">
            {value.sessions.map((item) => (
              <li key={item.session_id}>
                <a
                  href={`/console/research/review/${encodeURIComponent(item.session_id)}`}
                >
                  <span className="source-review-session-name">
                    <strong>{item.name}</strong>
                    <small>
                      {item.repo_label || "Unlabelled checkout"} ·{" "}
                      <code title={item.commit_sha}>
                        {item.commit_sha.slice(0, 12)}
                      </code>
                    </small>
                  </span>
                  <CaptureBadge
                    state={item.capture_state}
                    complete={item.complete}
                  />
                  <span>{progressText(item)}</span>
                  <span>
                    {formatObserved(item.created_at)} · {item.actor}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            title="No review sessions"
            detail="Create a session to freeze an inventory of the research checkout."
          />
        )}
        <div className="http-pagination">
          {before ? (
            <button type="button" onClick={() => setBefore(null)}>
              ← Newest sessions
            </button>
          ) : (
            <span />
          )}
          {value?.next_before && (
            <button type="button" onClick={() => setBefore(value.next_before)}>
              Older sessions →
            </button>
          )}
        </div>
      </Panel>
    </>
  );
}
