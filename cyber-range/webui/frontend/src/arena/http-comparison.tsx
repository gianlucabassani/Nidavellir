import { useState } from "react";
import type React from "react";
import { postJson } from "../api";
import type { HttpComparison, HttpRequestGroup } from "../types";
import { Empty, ErrorState, Loading, Panel, useWorkspaceData } from "../ui";

type Pair = { left: string; right: string };

function ComparedResponses({ arenaId, pair }: { arenaId: string; pair: Pair }) {
  const id = encodeURIComponent(arenaId);
  const { value, error, loading, refresh } = useWorkspaceData<HttpComparison>(
    `/api/console/arenas/${id}/http/comparison?${new URLSearchParams(pair)}`,
  );
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (loading || !value) return <Loading />;
  return (
    <div className="http-compared-responses">
      <p>{value.interpretation}</p>
      {!!value.unresolved.length && (
        <div className="review-unresolved" role="note">
          <strong>Incomplete comparison</strong>
          <ul>
            {value.unresolved.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="http-detail-columns">
        {[value.left, value.right].map((item, index) => (
          <section key={index} aria-label={`Response ${index ? "B" : "A"}`}>
            <h3>
              {index ? "B" : "A"} · {item.request.method} {item.request.path}
            </h3>
            <p>
              Status {item.response.status} ·{" "}
              {item.response.body_bytes ?? "unknown"} response bytes
            </p>
            <code>
              {item.response.body_sha256 || "Original body digest unavailable"}
            </code>
            <details>
              <summary>Request</summary>
              <pre>{JSON.stringify(item.request, null, 2)}</pre>
            </details>
            <details>
              <summary>Response headers (projected)</summary>
              <pre>{JSON.stringify(item.response.headers || {}, null, 2)}</pre>
            </details>
            <pre>{item.response.body ?? "Body unavailable"}</pre>
            <a
              href={`/api/arenas/${id}/http/transactions/${encodeURIComponent(item.digest)}`}
            >
              Stored transaction {item.digest}
            </a>
          </section>
        ))}
      </div>
      <h3>Response body differences</h3>
      <p>
        {value.captured_body_equal === null
          ? "Body equality unknown"
          : value.captured_body_equal
            ? "Captured bodies match"
            : "Captured bodies differ"}
        .{" "}
        {value.complete
          ? "Complete captured body comparison."
          : "Review the capture and preview limits above."}
      </p>
      <pre aria-label="Response body diff">
        {value.body_diff || "No differences visible in these previews."}
      </pre>
      <h3>Response header differences</h3>
      <p>
        Cookie values, redirect query values and unrecognized headers are
        withheld.
      </p>
      <pre aria-label="Response header diff">
        {value.response_headers_diff ||
          "No differences in projected response headers."}
      </pre>
      <a
        className="inline-action"
        href={`/console/arena/${id}?tab=findings&transaction=${encodeURIComponent(pair.left + "," + pair.right)}`}
      >
        Use both transactions in a finding ↗
      </a>
    </div>
  );
}

export function HttpComparisonWorkbench({
  arenaId,
  pair,
  onSelect,
}: {
  arenaId: string;
  pair: Pair;
  onSelect: (pair: Pair) => void;
}) {
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [leftLabel, setLeftLabel] = useState("A");
  const [rightLabel, setRightLabel] = useState("B");
  const [before, setBefore] = useState<number | null>(null);
  const id = encodeURIComponent(arenaId);
  const { value, error, loading, refresh } = useWorkspaceData<{
    groups: HttpRequestGroup[];
    next_before: number | null;
  }>(
    `/api/console/arenas/${id}/http/request-groups${before ? "?before=" + before : ""}`,
  );
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const ready = Boolean(pair.left && pair.right && pair.left !== pair.right);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!ready || pending) return;
    setPending(true);
    setMessage("");
    try {
      await postJson(`/api/console/arenas/${id}/http/request-groups`, {
        name,
        notes,
        left: { digest: pair.left, label: leftLabel },
        right: { digest: pair.right, label: rightLabel },
      });
      setMessage(
        "Named comparison saved. Both immutable transactions remain linked.",
      );
      setBefore(null);
      refresh();
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "Comparison could not be saved",
      );
    } finally {
      setPending(false);
    }
  }
  function reopen(group: HttpRequestGroup) {
    onSelect({ left: group.left.digest, right: group.right.digest });
    setName(group.name);
    setNotes(group.notes);
    setLeftLabel(group.left.label);
    setRightLabel(group.right.label);
  }
  return (
    <Panel
      title="Compare requests"
      className="http-comparison-panel"
      eyebrow="A / B"
    >
      <p>
        Choose Set A and Set B from the transaction ledger. Comparing and saving
        evidence sends no requests.
      </p>
      <div className="http-comparison-select">
        <label>
          Transaction A
          <input
            value={pair.left}
            onChange={(event) =>
              onSelect({ ...pair, left: event.target.value })
            }
            maxLength={71}
            placeholder="sha256:…"
          />
        </label>
        <label>
          Transaction B
          <input
            value={pair.right}
            onChange={(event) =>
              onSelect({ ...pair, right: event.target.value })
            }
            maxLength={71}
            placeholder="sha256:…"
          />
        </label>
      </div>
      {ready ? (
        <ComparedResponses
          key={`${arenaId}:${pair.left}:${pair.right}`}
          arenaId={arenaId}
          pair={pair}
        />
      ) : (
        <Empty
          title="Select two distinct captures"
          detail="Compare an owned request with its edited replay or another recorded account's request."
        />
      )}
      {ready && (
        <form onSubmit={save} className="http-group-form">
          <label>
            Group name
            <input
              required
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Owned versus foreign object"
            />
          </label>
          <div className="http-comparison-select">
            <label>
              A label
              <input
                required
                maxLength={80}
                value={leftLabel}
                onChange={(event) => setLeftLabel(event.target.value)}
              />
            </label>
            <label>
              B label
              <input
                required
                maxLength={80}
                value={rightLabel}
                onChange={(event) => setRightLabel(event.target.value)}
              />
            </label>
          </div>
          <label>
            Research notes
            <textarea
              aria-label="Research notes"
              maxLength={2000}
              rows={3}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="What changed, and which controls still need checking"
            />
          </label>
          <button className="button button-gold" disabled={pending}>
            {pending ? "Saving…" : "Save named comparison"}
          </button>
          <p>
            Saved groups keep labels, notes and evidence references. Saving
            again creates a new snapshot.
          </p>
        </form>
      )}
      {message && <p role="status">{message}</p>}
      <h3>Saved request groups</h3>
      {error ? (
        <ErrorState message={error} refresh={refresh} />
      ) : loading ? (
        <Loading />
      ) : value?.groups.length ? (
        <div className="http-saved-groups">
          {value.groups.map((group) => (
            <button
              type="button"
              className="button button-outline"
              key={group.group_id}
              onClick={() => reopen(group)}
            >
              {group.name} · {group.left.label} / {group.right.label}
            </button>
          ))}
        </div>
      ) : (
        <p>No saved request groups.</p>
      )}
      <div className="http-pagination">
        {before && (
          <button type="button" onClick={() => setBefore(null)}>
            Newest groups
          </button>
        )}
        {value?.next_before && (
          <button type="button" onClick={() => setBefore(value.next_before)}>
            Older groups →
          </button>
        )}
      </div>
    </Panel>
  );
}
