import { useEffect, useRef, useState } from "react";
import { jsonRequest } from "../api";
import type { RangeData, Scenario } from "../types";
import {
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  useWorkspaceData,
} from "../ui";
import { ScenarioTopology } from "./index";

type Filter = "all" | "builtin" | "imported" | "container" | "vm";
const filters: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "builtin", label: "Built-in" },
  { id: "imported", label: "Imported" },
  { id: "container", label: "Container" },
  { id: "vm", label: "VM" },
];

export function ScenarioLibrary() {
  const { value, error, loading, refresh } =
    useWorkspaceData<RangeData>("/api/console/range");
  const params = new URLSearchParams(window.location.search);
  const [query, setQuery] = useState(params.get("q") || "");
  const [filter, setFilter] = useState<Filter>(() => {
    const initial = params.get("filter");
    return filters.some((item) => item.id === initial)
      ? (initial as Filter)
      : "all";
  });
  const [selectedId, setSelectedId] = useState(params.get("id") || "");
  const [deleting, setDeleting] = useState<Scenario | null>(null);
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (deleting && dialog.current && !dialog.current.open)
      dialog.current.showModal();
    if (!deleting && dialog.current?.open) dialog.current.close();
  }, [deleting]);
  function updateUrl(name: string, content: string) {
    const url = new URL(window.location.href);
    if (content) url.searchParams.set(name, content);
    else url.searchParams.delete(name);
    window.history.replaceState(null, "", url);
  }
  async function remove() {
    if (!deleting || pending) return;
    setPending(true);
    setActionError("");
    try {
      await jsonRequest(
        "DELETE",
        `/api/scenarios/${encodeURIComponent(deleting.id)}`,
      );
      if (selectedId === deleting.id) {
        setSelectedId("");
        updateUrl("id", "");
      }
      setDeleting(null);
      refresh();
    } catch (reason) {
      setActionError(
        reason instanceof Error ? reason.message : "Delete failed",
      );
    } finally {
      setPending(false);
    }
  }
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const normalized = query.trim().toLowerCase();
  const listed = value.scenarios.filter((item) => {
    const matchesFilter =
      filter === "all" ||
      (filter === "builtin" && item.source !== "imported") ||
      (filter === "imported" && item.source === "imported") ||
      item.provider_class === filter;
    const matchesSearch =
      !normalized ||
      `${item.name} ${item.id} ${item.description || ""} ${(item.tags || []).join(" ")}`
        .toLowerCase()
        .includes(normalized);
    return matchesFilter && matchesSearch;
  });
  const selected =
    listed.find((item) => item.id === selectedId) ||
    listed.find((item) => ["container", "any"].includes(item.provider_class)) ||
    listed[0] ||
    null;
  const launchable =
    selected && ["container", "any"].includes(selected.provider_class);
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=range">← Cyber Range</a>
        <span>/</span>
        <span>Scenarios</span>
      </div>
      <PageHead
        overline="CYBER RANGE / LIBRARY"
        title="Scenario library"
        subtitle="Find a registered topology, review its nodes, or import a new pack."
        observed={value.observed_at}
        action={
          <a className="button button-gold" href="/console/scenarios/import">
            Import scenario ↗
          </a>
        }
        refresh={refresh}
      />
      {actionError && (
        <p className="form-error" role="alert">
          {actionError}
        </p>
      )}
      <div className="scenario-library-grid">
        <Panel
          eyebrow="01 / REGISTRY"
          title="Registered scenarios"
          aside={<span className="tiny-tag">{listed.length} SHOWN</span>}
        >
          <div className="scenario-library-controls">
            <label>
              Search scenarios
              <input
                type="search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  updateUrl("q", event.target.value);
                }}
                placeholder="Name, id or tag"
              />
            </label>
            <div className="scenario-filters" aria-label="Filter scenarios">
              {filters.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={filter === item.id ? "selected" : ""}
                  aria-pressed={filter === item.id}
                  onClick={() => {
                    setFilter(item.id);
                    updateUrl("filter", item.id === "all" ? "" : item.id);
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          {listed.length ? (
            <div className="scenario-library-list">
              {listed.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`scenario-library-item ${selected?.id === item.id ? "selected" : ""}`}
                  aria-pressed={selected?.id === item.id}
                  onClick={() => {
                    setSelectedId(item.id);
                    updateUrl("id", item.id);
                  }}
                >
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      {item.description || "No description supplied."}
                    </small>
                    <em>
                      {item.nodes} nodes · {item.provider_class} · {item.source}
                    </em>
                  </span>
                  <b aria-hidden="true">↗</b>
                </button>
              ))}
            </div>
          ) : (
            <Empty
              title="No scenarios match"
              detail="Change the search or filter, or import a new scenario pack."
            />
          )}
        </Panel>
        <Panel
          eyebrow="02 / TOPOLOGY"
          title={selected?.name || "Select a scenario"}
          aside={
            selected && <span className="tiny-tag">{selected.source}</span>
          }
        >
          {selected ? (
            <div className="scenario-library-detail">
              <ScenarioTopology key={selected.id} id={selected.id} />
              <p className="scenario-description">
                {selected.description || "No description supplied."}
              </p>
              {(selected.tags || []).length > 0 && (
                <p className="scenario-tags">{selected.tags.join(" · ")}</p>
              )}
              <div className="panel-foot">
                <span>
                  {launchable
                    ? "Review the operating time box before launch."
                    : "This provider has no verified local launch path."}
                </span>
                {launchable && (
                  <a
                    className="inline-action"
                    href={`/console/arenas/new?scenario=${encodeURIComponent(selected.id)}`}
                  >
                    Review launch ↗
                  </a>
                )}
              </div>
              {selected.source === "imported" && (
                <button
                  type="button"
                  className="button button-danger"
                  onClick={() => {
                    setActionError("");
                    setDeleting(selected);
                  }}
                >
                  Delete imported pack
                </button>
              )}
            </div>
          ) : (
            <Empty
              title="No scenario selected"
              detail="Select a registered scenario to inspect its topology."
            />
          )}
        </Panel>
      </div>
      <dialog
        ref={dialog}
        className="confirm-dialog"
        onClose={() => setDeleting(null)}
      >
        <h2>Delete imported pack {deleting?.name}?</h2>
        <p>
          The pack {deleting?.id} will leave the registry. Existing arena
          records remain available.
        </p>
        {actionError && (
          <p className="form-error" role="alert">
            {actionError}
          </p>
        )}
        <div>
          <button
            type="button"
            className="button button-outline"
            disabled={pending}
            onClick={() => setDeleting(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="button button-danger"
            disabled={pending}
            onClick={() => void remove()}
          >
            {pending ? "Deleting…" : "Confirm delete"}
          </button>
        </div>
      </dialog>
    </>
  );
}
