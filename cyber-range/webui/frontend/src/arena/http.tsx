import { useEffect, useRef, useState } from "react";
import type React from "react";
import { MapTargetNotice, useMapTarget } from "./target";
import type {
  ArenaData,
  HttpTransaction,
  HttpTransactionManifest,
} from "../types";
import {
  useWorkspaceData,
  Status,
  formatObserved,
  Panel,
  Empty,
  Loading,
  ErrorState,
} from "../ui";

export function HttpWorkbench({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const [offset, setOffset] = useState(0);
  const { value, error, loading, refresh } = useWorkspaceData<{
    total: number;
    transactions: HttpTransactionManifest[];
  }>(`/api/arenas/${id}/http/transactions?limit=25&offset=${offset}`);
  const targets = arena.nodes.filter((node) => node.web_capable);
  const editable = arena.state === "active";
  const mapTarget = useMapTarget(targets.map((target) => target.name));
  const [node, setNode] = useState(
    mapTarget.accepted || targets[0]?.name || "",
  );
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState("/");
  const [params, setParams] = useState("");
  const [headers, setHeaders] = useState("");
  const [body, setBody] = useState("");
  const [replayOf, setReplayOf] = useState<string | null>(null);
  const [detail, setDetail] = useState<HttpTransaction | null>(null);
  const [detailError, setDetailError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [formOpen, setFormOpen] = useState(editable && targets.length > 0);
  const formRef = useRef<HTMLFormElement>(null);

  async function inspect(digest: string, prepareReplay = false) {
    setDetailError("");
    try {
      const response = await fetch(
        `/api/arenas/${id}/http/transactions/${encodeURIComponent(digest)}`,
        { credentials: "same-origin", headers: { Accept: "application/json" } },
      );
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
        );
        return;
      }
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          data.error || data.detail || `Inspection failed (${response.status})`,
        );
      const transaction = { ...data.transaction, digest } as HttpTransaction;
      setDetail(transaction);
      if (prepareReplay) {
        const request = transaction.request;
        mapTarget.clear();
        setNode(request.node || targets[0]?.name || "");
        setMethod(request.method || "GET");
        setPath(request.path || "/");
        setParams(new URLSearchParams(request.params || {}).toString());
        setHeaders(
          Object.entries(request.headers || {})
            .map(([key, value]) => `${key}: ${value}`)
            .join("\n"),
        );
        setBody(request.body || "");
        setReplayOf(digest);
        setFormOpen(true);
        window.setTimeout(
          () =>
            formRef.current?.scrollIntoView({
              behavior: "smooth",
              block: "start",
            }),
          0,
        );
      }
    } catch (reason) {
      setDetailError(
        reason instanceof Error ? reason.message : "Transaction unavailable",
      );
    }
  }

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("digest");
    if (requested) void inspect(requested);
    // The URL selects the first inspection; later selections stay local to this tab.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setMessage("");
    if (!node) {
      setMessage("Choose a web-capable target node.");
      return;
    }
    if (!path.startsWith("/") || path.startsWith("//") || /[?#]/.test(path)) {
      setMessage(
        "Use an arena-relative path without a query or fragment. Put query values in Params.",
      );
      return;
    }
    const parsedHeaders: Record<string, string> = {};
    for (const line of headers.split("\n")) {
      if (!line.trim()) continue;
      const separator = line.indexOf(":");
      if (separator < 1) {
        setMessage(`Invalid header: ${line}`);
        return;
      }
      parsedHeaders[line.slice(0, separator).trim()] = line
        .slice(separator + 1)
        .trim();
    }
    setPending(true);
    try {
      const payload = {
        node,
        method,
        path,
        params: Object.fromEntries(new URLSearchParams(params)),
        headers: parsedHeaders,
        body: body || null,
      };
      const endpoint = replayOf
        ? `/api/arenas/${id}/http/transactions/${encodeURIComponent(replayOf)}/replay`
        : `/api/arenas/${id}/http/request`;
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-CSRFToken":
            document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
              ?.content || "",
        },
        body: JSON.stringify(payload),
      });
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
        );
        return;
      }
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : result.error || `Request rejected (${response.status})`,
        );
      setReplayOf(null);
      setFormOpen(false);
      setMessage(`${method} ${path} → ${result.status}. Transaction recorded.`);
      setOffset(0);
      refresh();
      if (result.transaction_digest) await inspect(result.transaction_digest);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Request failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="http-work-grid">
      <Panel
        eyebrow="01 / DRIVE"
        title="Arena HTTP request"
        className="http-drive-panel"
      >
        <p className="http-intro">
          Send to a target node inside this arena. The service scopes access,
          records the response, and assigns an immutable digest.
        </p>
        {!editable ? (
          <Empty
            title="Archived transaction record"
            detail="Requests and replays are unavailable after teardown. Stored transactions remain reviewable."
          />
        ) : !targets.length ? (
          <Empty
            title="No web-capable target"
            detail="This arena has no declared target service for HTTP requests."
          />
        ) : (
          <>
            {!formOpen && (
              <button
                type="button"
                className="button button-gold http-open"
                onClick={() => setFormOpen(true)}
              >
                Send request ↗
              </button>
            )}
            {formOpen && (
              <form className="http-form" ref={formRef} onSubmit={submit}>
                <MapTargetNotice
                  requested={mapTarget.requested}
                  accepted={mapTarget.accepted}
                  tool="HTTP"
                />
                {replayOf && (
                  <p className="http-replay-note">
                    Replaying {replayOf}. Edits create a linked copy; the
                    original stays intact.
                  </p>
                )}
                <div className="http-request-line">
                  <label>
                    Method
                    <select
                      value={method}
                      onChange={(event) => setMethod(event.target.value)}
                    >
                      {[
                        "GET",
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                        "HEAD",
                        "OPTIONS",
                      ].map((item) => (
                        <option key={item}>{item}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Path
                    <input
                      value={path}
                      onChange={(event) => setPath(event.target.value)}
                      required
                      maxLength={2048}
                      spellCheck={false}
                      placeholder="/records/42"
                    />
                  </label>
                </div>
                <label>
                  Target node
                  <select
                    value={node}
                    onChange={(event) => {
                      mapTarget.clear();
                      setNode(event.target.value);
                    }}
                  >
                    {targets.map((target) => (
                      <option key={target.name} value={target.name}>
                        {target.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Params
                  <input
                    value={params}
                    onChange={(event) => setParams(event.target.value)}
                    spellCheck={false}
                    placeholder="key=value&amp;page=2"
                  />
                </label>
                <label>
                  Headers
                  <textarea
                    value={headers}
                    onChange={(event) => setHeaders(event.target.value)}
                    rows={3}
                    spellCheck={false}
                    placeholder="X-Research-Token: value (one per line)"
                  />
                </label>
                <label>
                  Body
                  <textarea
                    value={body}
                    onChange={(event) => setBody(event.target.value)}
                    rows={5}
                    spellCheck={false}
                    placeholder="Optional text body"
                  />
                </label>
                <div className="http-form-actions">
                  <button
                    type="button"
                    className="button button-outline"
                    disabled={pending}
                    onClick={() => {
                      setFormOpen(false);
                      setReplayOf(null);
                    }}
                  >
                    Cancel
                  </button>
                  <button className="button button-gold" disabled={pending}>
                    {pending
                      ? "Sending…"
                      : replayOf
                        ? "Replay with edits ↗"
                        : "Send and record ↗"}
                  </button>
                </div>
              </form>
            )}
          </>
        )}
        {message && (
          <p className="poc-message" role="status">
            {message}
          </p>
        )}
      </Panel>
      <Panel
        eyebrow="02 / LEDGER"
        title="Recorded transactions"
        className="http-ledger-panel"
        aside={
          <button type="button" className="subtle-link" onClick={refresh}>
            Refresh ↻
          </button>
        }
      >
        {loading && !value ? (
          <Loading />
        ) : error ? (
          <ErrorState message={error} refresh={refresh} />
        ) : value?.transactions.length ? (
          <>
            <div className="http-transaction-list">
              {value.transactions.map((item) => (
                <article key={item.digest} className="http-transaction">
                  <div>
                    <span className="tiny-tag">HTTP</span>
                    <strong>
                      {detail?.digest === item.digest
                        ? `${detail.request.method} ${detail.request.path}`
                        : "Recorded transaction"}
                    </strong>
                    {detail?.digest === item.digest && (
                      <Status value={String(detail.response.status)} />
                    )}
                  </div>
                  <small>
                    {item.created_at
                      ? formatObserved(item.created_at)
                      : "Time unknown"}{" "}
                    · {item.bytes ?? "?"} stored bytes
                    {item.elapsed_ms != null ? ` · ${item.elapsed_ms} ms` : ""}
                  </small>
                  <code>{item.digest}</code>
                  {item.replay_of && <small>Replay of {item.replay_of}</small>}
                  <div className="http-row-actions">
                    <button
                      type="button"
                      className="button button-outline"
                      onClick={() => void inspect(item.digest)}
                    >
                      Inspect
                    </button>
                    {editable && (
                      <button
                        type="button"
                        className="button button-outline"
                        onClick={() => void inspect(item.digest, true)}
                      >
                        Replay
                      </button>
                    )}
                    <a
                      className="inline-action"
                      href={`/console/arena/${id}?tab=findings&transaction=${encodeURIComponent(item.digest)}`}
                    >
                      Use in finding ↗
                    </a>
                  </div>
                </article>
              ))}
            </div>
            <div className="http-pagination">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 25))}
              >
                ← Previous
              </button>
              <span>
                {offset + 1}–{offset + value.transactions.length} of{" "}
                {value.total}
              </span>
              <button
                type="button"
                disabled={offset + value.transactions.length >= value.total}
                onClick={() => setOffset(offset + 25)}
              >
                Next →
              </button>
            </div>
          </>
        ) : (
          <Empty
            title="No HTTP transactions"
            detail="Recorded requests and replays will appear here with their immutable digests."
          />
        )}
      </Panel>
      <Panel
        eyebrow="03 / INSPECT"
        title="Transaction detail"
        className="http-detail-panel"
      >
        {detailError && (
          <p className="form-error" role="alert">
            {detailError}
          </p>
        )}
        {detail ? (
          <div className="http-detail">
            <div className="http-detail-head">
              <strong>
                {detail.request.method} {detail.request.path}
              </strong>
              <code>{detail.digest}</code>
            </div>
            <div className="http-detail-columns">
              <section>
                <h3>Request</h3>
                <pre>{JSON.stringify(detail.request, null, 2)}</pre>
              </section>
              <section>
                <h3>Response · {detail.response.status}</h3>
                <pre>{JSON.stringify(detail.response, null, 2)}</pre>
              </section>
            </div>
            <div className="panel-foot">
              <span>
                {detail.replay_of
                  ? `Linked replay of ${detail.replay_of}`
                  : "Original transaction"}
              </span>
              <a
                className="inline-action"
                href={`/console/arena/${id}?tab=findings&transaction=${encodeURIComponent(detail.digest)}`}
              >
                Use in finding ↗
              </a>
            </div>
          </div>
        ) : (
          <Empty
            title="Choose a transaction"
            detail="Inspect the bounded request and response, or replay a stored request with edits."
          />
        )}
      </Panel>
    </div>
  );
}
