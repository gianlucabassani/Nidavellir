import { useEffect, useRef, useState } from "react";
import "./http-panes.css";
import type React from "react";
import { MapTargetNotice, useMapTarget } from "./target";
import { HttpComparisonWorkbench } from "./http-comparison";
import type {
  ArenaData,
  HttpTransaction,
  HttpTransactionManifest,
} from "../types";
import {
  useWorkspaceData,
  formatObserved,
  Panel,
  Empty,
  Loading,
  ErrorState,
} from "../ui";

type Pane = "request" | "compare" | "detail";
const PANES: { id: Pane; label: string }[] = [
  { id: "request", label: "Request" },
  { id: "compare", label: "Compare" },
  { id: "detail", label: "Detail" },
];

function formatBytes(value: number) {
  return value < 1024
    ? `${value} B`
    : value < 1024 * 1024
      ? `${(value / 1024).toFixed(1)} KB`
      : `${(value / 1024 / 1024).toFixed(1)} MB`;
}

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
  const [pair, setPairState] = useState<{ left: string; right: string }>(() => {
    const params = new URLSearchParams(window.location.search);
    return { left: params.get("a") || "", right: params.get("b") || "" };
  });
  // The A/B selection lives in the URL with the pane, so reload and back
  // restore the comparison, not just the tab.
  const setPair = (next: { left: string; right: string }) => {
    setPairState(next);
    const url = new URL(window.location.href);
    for (const [key, value] of [
      ["a", next.left],
      ["b", next.right],
    ] as const)
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    history.replaceState(history.state, "", url);
  };
  const [credentialSource, setCredentialSource] = useState("");
  const [credentialHeaders, setCredentialHeaders] = useState("Authorization");
  const [inheritedHeaders, setInheritedHeaders] = useState<string[]>([]);
  const [replayOf, setReplayOf] = useState<string | null>(null);
  const [detail, setDetail] = useState<HttpTransaction | null>(null);
  const [detailError, setDetailError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [formOpen, setFormOpen] = useState(editable && targets.length > 0);
  const [pane, setPaneState] = useState<Pane>(() => {
    const requested = new URLSearchParams(window.location.search).get("pane");
    return PANES.some((item) => item.id === requested)
      ? (requested as Pane)
      : new URLSearchParams(window.location.search).get("digest")
        ? "detail"
        : "request";
  });
  const setPane = (next: Pane) => {
    setPaneState(next);
    const url = new URL(window.location.href);
    url.searchParams.set("pane", next);
    history.replaceState(history.state, "", url);
  };
  const formRef = useRef<HTMLFormElement>(null);

  async function inspect(
    digest: string,
    prepareReplay = false,
    keepPane = false,
  ) {
    setDetailError("");
    if (prepareReplay) {
      setPane("request");
      setFormOpen(false);
      setMessage("Preparing stored request…");
    }
    try {
      const response = await fetch(
        `/api/console/arenas/${id}/http/transactions/${encodeURIComponent(digest)}/preview`,
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
      const transaction = { ...data, digest } as HttpTransaction;
      setDetail(transaction);
      if (!prepareReplay && !keepPane) setPane("detail");
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
        setInheritedHeaders(request.withheld_headers || []);
        setCredentialSource("");
        setReplayOf(digest);
        setFormOpen(true);
        setMessage("Stored request ready. Review edits before sending.");
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
    // In-console navigation (search, palette, back/forward) to this same tab
    // with another ?digest= or ?pane= applies it without remounting.
    let lastDigest = requested;
    const onNavigate = () => {
      const params = new URLSearchParams(window.location.search);
      const digest = params.get("digest");
      const nextPane = params.get("pane");
      if (PANES.some((item) => item.id === nextPane))
        setPaneState(nextPane as Pane);
      if (digest && digest !== lastDigest) {
        lastDigest = digest;
        void inspect(digest, false, Boolean(nextPane));
      }
    };
    window.addEventListener("popstate", onNavigate);
    return () => window.removeEventListener("popstate", onNavigate);
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
        body: replayOf ? body : body || null,
        ...(replayOf ? { replace_params: true } : {}),
        ...(replayOf && credentialSource.trim()
          ? {
              credential_source_digest: credentialSource.trim(),
              credential_header_names: credentialHeaders
                .split(",")
                .map((name) => name.trim())
                .filter(Boolean),
            }
          : {}),
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
      const compared = Boolean(replayOf && result.transaction_digest);
      if (compared) {
        setPair({ left: replayOf!, right: result.transaction_digest });
        setPane("compare");
      }
      setReplayOf(null);
      setFormOpen(false);
      setMessage(`${method} ${path} → ${result.status}. Transaction recorded.`);
      setOffset(0);
      refresh();
      if (result.transaction_digest)
        await inspect(result.transaction_digest, false, compared);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Request failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="http-work-grid http-panes">
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
        ) : error && !value ? (
          <ErrorState message={error} refresh={refresh} />
        ) : value?.transactions.length ? (
          <>
            <div className="http-transaction-list">
              {value.transactions.map((item) => (
                <article key={item.digest} className="http-transaction">
                  <div>
                    <span className="tiny-tag">HTTP</span>
                    <strong className="http-row-line">
                      {item.summary?.method && item.summary.path
                        ? `${item.summary.method} ${item.summary.path}`
                        : "Transaction (summary unavailable)"}
                    </strong>
                    {item.summary?.status != null && (
                      <span
                        className={`http-status http-status-${String(item.summary.status)[0]}xx`}
                      >
                        {item.summary.status}
                      </span>
                    )}
                  </div>
                  <small>
                    {item.summary?.node ? `${item.summary.node} · ` : ""}
                    {item.summary?.response_bytes != null
                      ? `${formatBytes(item.summary.response_bytes)} response`
                      : `${item.bytes ?? "?"} stored bytes`}
                    {item.elapsed_ms != null ? ` · ${item.elapsed_ms} ms` : ""}
                    {" · "}
                    {item.created_at
                      ? formatObserved(item.created_at)
                      : "Time unknown"}
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
                        Duplicate and edit
                      </button>
                    )}
                    <button
                      type="button"
                      className="button button-outline"
                      onClick={() => {
                        if (pair.right) setPane("compare");
                        setPair({ ...pair, left: item.digest });
                      }}
                    >
                      Set A
                    </button>
                    <button
                      type="button"
                      className="button button-outline"
                      onClick={() => {
                        if (pair.left) setPane("compare");
                        setPair({ ...pair, right: item.digest });
                      }}
                    >
                      Set B
                    </button>
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
                aria-describedby="http-page-why"
                onClick={() => setOffset(Math.max(0, offset - 25))}
              >
                ← Previous
              </button>
              <span id="http-page-why">
                {offset + 1}–{offset + value.transactions.length} of{" "}
                {value.total}
                {offset === 0 ? " · first page" : ""}
                {offset + value.transactions.length >= value.total
                  ? " · last page"
                  : ""}
              </span>
              <button
                type="button"
                disabled={offset + value.transactions.length >= value.total}
                aria-describedby="http-page-why"
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
      <div className="http-pane-area">
        <div
          className="http-pane-tabs"
          role="tablist"
          aria-label="HTTP tool panes"
        >
          {PANES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`http-tab-${item.id}`}
              aria-selected={pane === item.id}
              aria-controls={`http-pane-${item.id}`}
              className={pane === item.id ? "active" : ""}
              onClick={() => setPane(item.id)}
            >
              {item.label}
              {item.id === "compare" && pair.left && pair.right
                ? " · A/B set"
                : ""}
            </button>
          ))}
        </div>
        <div
          role="tabpanel"
          id="http-pane-request"
          aria-labelledby="http-tab-request"
          hidden={pane !== "request"}
        >
          <Panel
            eyebrow="01 / DRIVE"
            title="Arena HTTP request"
            className="http-drive-panel"
          >
            <p className="http-intro">
              Send to a target node inside this arena. The service scopes
              access, records the response, and assigns an immutable digest.
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
                    onClick={() => {
                      setFormOpen(true);
                      setPane("request");
                    }}
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
                        aria-label="Request headers"
                        value={headers}
                        onChange={(event) => setHeaders(event.target.value)}
                        rows={3}
                        spellCheck={false}
                        placeholder="X-Research-Token: value (one per line)"
                      />
                    </label>
                    {replayOf && (
                      <fieldset className="http-identity">
                        <legend>Account for this replay</legend>
                        <p>
                          Stored headers are inherited server-side:{" "}
                          {inheritedHeaders.join(", ") || "none withheld"}.
                          Values stay out of this editor.
                        </p>
                        <label>
                          Credential source transaction (optional)
                          <input
                            value={credentialSource}
                            onChange={(event) =>
                              setCredentialSource(event.target.value)
                            }
                            placeholder="sha256:… from this arena"
                            maxLength={71}
                          />
                        </label>
                        <label>
                          Credential header names
                          <input
                            value={credentialHeaders}
                            onChange={(event) =>
                              setCredentialHeaders(event.target.value)
                            }
                            placeholder="Authorization, Cookie"
                          />
                        </label>
                        <p>
                          Leave the source empty to keep the original account.
                          Override request IDs in Headers when the target
                          requires unique IDs.
                        </p>
                      </fieldset>
                    )}
                    <label>
                      Body
                      <textarea
                        aria-label="Request body"
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
        </div>
        <div
          role="tabpanel"
          id="http-pane-compare"
          aria-labelledby="http-tab-compare"
          hidden={pane !== "compare"}
        >
          <HttpComparisonWorkbench
            arenaId={arena.id}
            pair={pair}
            onSelect={setPair}
          />
        </div>
        <div
          role="tabpanel"
          id="http-pane-detail"
          aria-labelledby="http-tab-detail"
          hidden={pane !== "detail"}
        >
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
                <p>
                  Authentication header values are withheld.{" "}
                  {detail.preview_clipped
                    ? "Response preview clipped; use the retained transaction for full captured content."
                    : ""}
                </p>
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
      </div>
    </div>
  );
}
