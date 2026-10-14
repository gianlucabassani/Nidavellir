import { useState } from "react";
import type { RangeData, TopologyData } from "../types";
import { paths } from "../types";
import {
  useWorkspaceData,
  Panel,
  Empty,
  PageHead,
  Loading,
  ErrorState,
} from "../ui";
import { TopologyPreview } from "./topology";

export function ScenarioTopology({ id }: { id: string }) {
  const { value, error, loading, refresh } = useWorkspaceData<TopologyData>(
    `/api/scenarios/${encodeURIComponent(id)}/topology`,
  );
  if (loading && !value)
    return (
      <div className="topology-preview topology-message">Loading topology…</div>
    );
  if (error || !value?.topology)
    return (
      <div className="topology-preview topology-message">
        Topology unavailable.{" "}
        <button type="button" onClick={refresh}>
          Retry
        </button>
      </div>
    );
  return <TopologyPreview topology={value.topology} />;
}

export function Range() {
  const { value, error, loading, refresh } = useWorkspaceData<RangeData>(
    paths.range,
  );
  const [selected, setSelected] = useState("");
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const compatible = value.scenarios.filter(
    (item) =>
      item.provider_class === "container" || item.provider_class === "any",
  );
  const scenario =
    value.scenarios.find((item) => item.id === selected) ||
    compatible[0] ||
    value.scenarios[0];
  const launchable = Boolean(scenario);
  const live = value.arenas.filter(
    (item) =>
      !["destroyed", "failed", "error_destroying"].includes(item.status),
  );
  return (
    <>
      <PageHead
        overline="WORKSPACE / CYBER RANGE"
        title="Cyber Range"
        subtitle="Inspect a topology, launch a controlled arena and follow its lifecycle."
        observed={value.observed_at}
        action={
          launchable ? (
            <a
              className="button button-gold"
              href={`/console/arenas/new?scenario=${encodeURIComponent(scenario.id)}`}
            >
              Launch scenario ↗
            </a>
          ) : (
            <a className="button button-outline" href="/console/scenarios">
              Browse scenarios ↗
            </a>
          )
        }
        refresh={refresh}
      />
      <div className="scope-note">
        <strong>
          {value.simulation_mode ? "Simulation mode" : "Provider support"}
        </strong>
        <span>
          {value.simulation_mode
            ? "This development stack simulates arena operations. Launches here do not prove Docker-local infrastructure."
            : "Docker-local is the live-verified path. Other drivers are not presented as supported launch options."}
        </span>
        <b>{value.simulation_mode ? "MOCK" : "DOCKER-LOCAL"}</b>
      </div>
      <div className="range-grid">
        <Panel
          eyebrow="01 / SCENARIOS"
          title="Catalog"
          className="catalog-panel"
          aside={
            <a className="subtle-link" href="/console/scenarios">
              Full library
            </a>
          }
        >
          {value.scenarios.length ? (
            <div className="catalog-list">
              {value.scenarios.slice(0, 7).map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`catalog-item ${scenario?.id === item.id ? "selected" : ""}`}
                  onClick={() => setSelected(item.id)}
                  aria-pressed={scenario?.id === item.id}
                >
                  <strong>{item.name}</strong>
                  <small>
                    {item.nodes} nodes · {item.provider_class}
                  </small>
                </button>
              ))}
            </div>
          ) : (
            <Empty
              title="No scenarios available"
              detail="Import a scenario or inspect the service connection."
              action={
                <a className="inline-action" href="/console/scenarios">
                  Open library ↗
                </a>
              }
            />
          )}
        </Panel>
        <Panel
          eyebrow="02 / PREVIEW"
          title={scenario?.name || "Select a scenario"}
          className="topology-panel"
          aside={
            scenario && <span className="tiny-tag">{scenario.source}</span>
          }
        >
          {scenario ? (
            <>
              <ScenarioTopology key={scenario.id} id={scenario.id} />
              <p className="scenario-description">
                {scenario.description ||
                  "No description supplied for this scenario."}
              </p>
              <div className="panel-foot">
                <span>
                  {launchable
                    ? "Topology details are reviewed before launch."
                    : "This provider has no verified local launch path."}
                </span>
                {launchable && (
                  <a
                    className="inline-action"
                    href={`/console/arenas/new?scenario=${encodeURIComponent(scenario.id)}`}
                  >
                    Review launch ↗
                  </a>
                )}
              </div>
            </>
          ) : (
            <Empty
              title="Catalog empty"
              detail="Scenario topologies will appear here when registered."
            />
          )}
        </Panel>
        <Panel
          eyebrow="03 / LIVE ARENAS"
          title="In operation"
          className="live-panel"
          aside={<span className="count">{live.length}</span>}
        >
          {live.length ? (
            <div className="compact-list">
              {live.slice(0, 4).map((item) => (
                <a
                  className="compact-row"
                  href={`/console/arena/${encodeURIComponent(item.id)}`}
                  key={item.id}
                >
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      {item.scenario} · {item.status}
                    </small>
                  </span>
                  <b>↗</b>
                </a>
              ))}
            </div>
          ) : (
            <Empty
              title="No arenas running"
              detail="Launch a Docker-local scenario to inspect nodes and events."
            />
          )}
          <div className="panel-foot">
            <a className="inline-action" href="/console/arenas">
              View all arena records ↗
            </a>
          </div>
        </Panel>
      </div>
    </>
  );
}
