import { useState } from "react";
import { postJson } from "../api";
import type { BenchmarkData, ResearchData } from "../types";
import { paths } from "../types";
import {
  ConfirmDialog,
  Empty,
  ErrorState,
  formatObserved,
  Loading,
  PageHead,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

const TERMINAL = ["destroyed", "failed", "error_destroying"];
type ArenaFilter = "all" | "live" | "archived";
type Pending =
  | { kind: "destroy" | "delete"; id: string; name: string }
  | { kind: "clear"; count: number }
  | null;

export function AllArenas() {
  const { value, error, loading, refresh } = useWorkspaceData<ResearchData>(
    paths.research,
  );
  const [filter, setFilter] = useState<ArenaFilter>("all");
  const [query, setQuery] = useState("");
  const [confirm, setConfirm] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const archived = value.sessions.filter((item) =>
    TERMINAL.includes(item.status),
  );
  const rows = value.sessions
    .filter((item) =>
      filter === "all"
        ? true
        : filter === "archived"
          ? TERMINAL.includes(item.status)
          : !TERMINAL.includes(item.status),
    )
    .filter((item) =>
      `${item.name} ${item.id} ${item.scenario} ${item.provider}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
    );
  async function perform(action: NonNullable<Pending>) {
    setConfirm(null);
    setBusy(true);
    setMessage("");
    try {
      if (action.kind === "destroy") {
        await postJson(
          `/api/console/arenas/${encodeURIComponent(action.id)}/lifecycle`,
          { action: "destroy" },
        );
        setMessage(
          `Destroy accepted for ${action.name}. Its record is retained.`,
        );
      } else if (action.kind === "delete") {
        await postJson(
          `/api/console/archive/${encodeURIComponent(action.id)}/delete`,
          {},
        );
        setMessage(`Removed ${action.name} from the archive.`);
      } else {
        const result = await postJson<{ deleted: number }>(
          "/api/console/archive/clear",
          {},
        );
        setMessage(`Archive cleared: ${result.deleted} records removed.`);
      }
      refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=research">← Research</a>
        <span>/</span>
        <span>All arenas</span>
      </div>
      <PageHead
        overline="RESEARCH / RECORDS"
        title="All arenas"
        subtitle="Every live arena and retained record, with its lifecycle actions."
        observed={value.observed_at}
        action={
          <a className="button button-gold" href="/console/research/new">
            New research ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="activity-toolbar">
        <nav className="registry-tabs" aria-label="Filter arenas">
          {(["all", "live", "archived"] as const).map((item) => (
            <button
              key={item}
              type="button"
              aria-current={filter === item ? "page" : undefined}
              onClick={() => setFilter(item)}
            >
              {item === "all" ? "All" : item === "live" ? "Live" : "Archived"}
              <b>
                {item === "all"
                  ? value.sessions.length
                  : item === "archived"
                    ? archived.length
                    : value.sessions.length - archived.length}
              </b>
            </button>
          ))}
        </nav>
        <label className="activity-search">
          Filter arenas
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Name, ID, scenario or provider"
          />
        </label>
      </div>
      {message && (
        <p className="gate-message" role="status">
          {message}
        </p>
      )}
      <Panel
        eyebrow="01 / ARENAS"
        title={`${rows.length} ${rows.length === 1 ? "arena" : "arenas"}`}
        aside={
          archived.length > 0 && (
            <button
              type="button"
              className="button button-outline"
              disabled={busy}
              onClick={() =>
                setConfirm({ kind: "clear", count: archived.length })
              }
            >
              Clear archive
            </button>
          )
        }
      >
        {rows.length ? (
          <div className="arena-list">
            <div className="arena-list-labels" aria-hidden="true">
              <span>ARENA</span>
              <span>STATUS</span>
              <span>SCENARIO</span>
              <span>PROVIDER</span>
              <span>EXPIRES</span>
              <span />
            </div>
            {rows.map((item) => {
              const terminal = TERMINAL.includes(item.status);
              return (
                <div className="arena-list-row" key={item.id}>
                  <a
                    className="session-name"
                    href={`/console/arena/${encodeURIComponent(item.id)}`}
                  >
                    <strong>{item.name}</strong>
                    <small>{item.id.slice(0, 8)}</small>
                  </a>
                  <Status value={item.status} />
                  <span className="row-scenario">{item.scenario}</span>
                  <span className="row-provider">{item.provider}</span>
                  <span className="row-expires">
                    {item.expires_at && !terminal
                      ? formatObserved(item.expires_at)
                      : "—"}
                  </span>
                  <span className="arena-list-actions">
                    <a
                      className="inline-action"
                      href={`/console/arena/${encodeURIComponent(item.id)}`}
                    >
                      Open ↗
                    </a>
                    {item.status === "active" && (
                      <button
                        type="button"
                        className="subtle-link danger-link"
                        disabled={busy}
                        onClick={() =>
                          setConfirm({
                            kind: "destroy",
                            id: item.id,
                            name: item.name,
                          })
                        }
                      >
                        Destroy
                      </button>
                    )}
                    {terminal && (
                      <button
                        type="button"
                        className="subtle-link danger-link"
                        disabled={busy}
                        onClick={() =>
                          setConfirm({
                            kind: "delete",
                            id: item.id,
                            name: item.name,
                          })
                        }
                      >
                        Remove
                      </button>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <Empty
            title={query ? "No matching arenas" : "No arenas"}
            detail={
              query
                ? "Change the filter or search text."
                : "Arenas you launch from Research or Cyber Range appear here."
            }
          />
        )}
      </Panel>
      {confirm && (
        <ConfirmDialog
          title={
            confirm.kind === "clear"
              ? `Clear ${confirm.count} archived records?`
              : confirm.kind === "destroy"
                ? `Destroy arena ${confirm.name}?`
                : `Remove ${confirm.name} from the archive?`
          }
          body={
            confirm.kind === "destroy"
              ? "The service tears down the arena and cancels active helpers. Its record and evidence stay available."
              : "This removes the retained record from the console history. The service only removes destroyed or failed records. This cannot be undone from the console."
          }
          confirmLabel={
            confirm.kind === "clear"
              ? "Clear archive"
              : confirm.kind === "destroy"
                ? "Destroy arena"
                : "Remove record"
          }
          danger
          onCancel={() => setConfirm(null)}
          onConfirm={() => void perform(confirm)}
        />
      )}
    </>
  );
}

export function AllEvaluations() {
  const { value, error, loading, refresh } = useWorkspaceData<BenchmarkData>(
    paths.benchmark,
  );
  const [state, setState] = useState("all");
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const build = (id: string) => {
    const item = value.builds.find((entry) => entry.id === id);
    return item ? `${item.name} · ${item.version}` : id.slice(0, 8);
  };
  const suite = (id: string) => {
    const item = value.suites.find((entry) => entry.id === id);
    return item
      ? `${item.name} · ${item.version}`
      : id?.slice(0, 8) || "unknown";
  };
  const states = [...new Set(value.evaluations.map((item) => item.state))];
  const rows = value.evaluations.filter(
    (item) => state === "all" || item.state === state,
  );
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=benchmark">← Benchmark</a>
        <span>/</span>
        <span>All evaluations</span>
      </div>
      <PageHead
        overline="BENCHMARK / RECORDS"
        title="All evaluations"
        subtitle="Every paired comparison, its suite and the two builds it measured."
        observed={value.observed_at}
        action={
          <a className="button button-gold" href="/console/evaluations/new">
            New comparison ↗
          </a>
        }
        refresh={refresh}
      />
      <nav className="registry-tabs" aria-label="Filter evaluations by state">
        {["all", ...states].map((item) => (
          <button
            key={item}
            type="button"
            aria-current={state === item ? "page" : undefined}
            onClick={() => setState(item)}
          >
            {item === "all" ? "All" : item.replaceAll("_", " ")}
            <b>
              {item === "all"
                ? value.evaluations.length
                : value.evaluations.filter((entry) => entry.state === item)
                    .length}
            </b>
          </button>
        ))}
      </nav>
      <Panel
        eyebrow="01 / COMPARISONS"
        title={`${rows.length} ${rows.length === 1 ? "evaluation" : "evaluations"}`}
      >
        {rows.length ? (
          <div className="compact-list">
            {rows.map((item) => (
              <a
                className="compact-row evaluation-row"
                key={item.id}
                href={`/console/evaluations/${encodeURIComponent(item.id)}`}
              >
                <span>
                  <strong>Evaluation {item.id.slice(0, 8)}</strong>
                  <small>
                    {build(item.baseline_id)} → {build(item.candidate_id)} ·
                    suite {suite(item.suite_id)}
                  </small>
                </span>
                <Status value={item.state} />
                <b aria-hidden="true">↗</b>
              </a>
            ))}
          </div>
        ) : (
          <Empty
            title="No evaluation records"
            detail="Completed and interrupted comparisons are retained here."
          />
        )}
      </Panel>
    </>
  );
}
