import { useState } from "react";
import type React from "react";
import type { RangeData } from "../types";
import { paths } from "../types";
import {
  useWorkspaceData,
  Panel,
  Empty,
  PageHead,
  Loading,
  ErrorState,
} from "../ui";
import { ScenarioTopology } from "./index";
import { TopologyPreview } from "./topology";
type LaunchOptions = {
  default: string;
  providers: { name: string; infra_class: string; verification: string }[];
  catalog: {
    id: string;
    name: string;
    kind: string;
    available: boolean;
    description: string;
    note: string;
  }[];
};

// Labels and meanings match the service's engagement purposes. "Manual
// research" keeps the purpose distinct from the Research workspace.
const PURPOSES = [
  {
    id: "discovery",
    label: "Discovery",
    meaning: "Find unknown weaknesses or regressions in a target.",
  },
  {
    id: "research",
    label: "Manual research",
    meaning: "Operator-led investigation without comparison scoring.",
  },
  {
    id: "calibration",
    label: "Calibration",
    meaning: "Validate tools, policies, containment and scoring behaviour.",
  },
  {
    id: "benchmark",
    label: "Benchmark",
    meaning: "Measure an agent or workflow against known objectives.",
  },
];

export function NewArena() {
  const { value, error, loading, refresh } = useWorkspaceData<RangeData>(
    paths.range,
  );
  const launch = useWorkspaceData<LaunchOptions>("/api/console/launch-options");
  const custom = window.location.pathname.endsWith("/custom");
  const [providerName, setProviderName] = useState("");
  const [attackers, setAttackers] = useState<string[]>([]);
  const [victims, setVictims] = useState<string[]>([]);
  const initialScenario =
    new URLSearchParams(window.location.search).get("scenario") || "";
  const [scenarioId, setScenarioId] = useState(initialScenario);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("discovery");
  const [participant, setParticipant] = useState("operator");
  const [timeBox, setTimeBox] = useState(3600);
  const [pending, setPending] = useState(false);
  const [submitError, setSubmitError] = useState("");
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (launch.loading && !launch.value) return <Loading />;
  if (launch.error)
    return <ErrorState message={launch.error} refresh={launch.refresh} />;
  if (!value || !launch.value) return null;
  const providers = launch.value.providers.filter(
    (item) => !custom || ["docker-local", "mock"].includes(item.name),
  );
  const provider =
    providers.find((item) => item.name === providerName) ||
    providers.find((item) => item.name === "docker-local") ||
    providers[0];
  if (!provider)
    return (
      <Empty
        title="No eligible provider"
        detail="Configure a provider on the server before launching."
      />
    );
  const options = value.scenarios.filter(
    (item) =>
      item.provider_class === "any" ||
      provider.infra_class === "any" ||
      item.provider_class === provider.infra_class,
  );
  const canLaunch = Boolean(
    custom ? attackers.length && victims.length : options.length,
  );
  const customNodes = [...attackers, ...victims].map((id) => ({
    name: id,
    kind: attackers.includes(id) ? "foothold" : "target",
    role: attackers.includes(id) ? "attacker" : "victim",
  }));
  const selected = options.find((item) => item.id === scenarioId) || options[0];
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canLaunch || pending) return;
    setPending(true);
    setSubmitError("");
    try {
      const response = await fetch(
        custom ? "/api/console/arenas/custom" : "/api/console/arenas",
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-CSRFToken":
              document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
                ?.content || "",
          },
          body: JSON.stringify({
            ...(custom ? { attackers, victims } : { scenario: selected?.id }),
            provider: provider.name,
            instance_id: name.trim(),
            engagement_purpose: purpose,
            participant_mode: participant,
            engagement_time_box_seconds: timeBox,
          }),
        },
      );
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
        );
        return;
      }
      const payload: {
        instance_id?: string;
        error?: string;
        detail?: unknown;
      } = await response.json();
      if (!response.ok || !payload.instance_id)
        throw new Error(
          payload.error || `Arena could not launch (${response.status})`,
        );
      window.location.assign(
        `/console/arena/${encodeURIComponent(payload.instance_id)}`,
      );
    } catch (reason) {
      setSubmitError(
        reason instanceof Error ? reason.message : "Arena could not launch",
      );
      setPending(false);
    }
  }
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=range">← Cyber Range</a>
        <span>/</span>
        <span>New arena</span>
      </div>
      <PageHead
        overline="CYBER RANGE / LAUNCH REVIEW"
        title="Launch a controlled arena"
        subtitle="Review the registered topology and set an operating time box."
        observed={value.observed_at}
        action={
          <a
            className="button button-outline"
            href={custom ? "/console/arenas/new" : "/console/arenas/custom"}
          >
            {custom ? "Registered scenario" : "Build custom topology"} ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="scope-note">
        <strong>
          {value.simulation_mode || provider.name === "mock"
            ? "Simulation mode"
            : "Provider"}
        </strong>
        <span>
          {value.simulation_mode || provider.name === "mock"
            ? "The orchestrator validates this request, then simulates the arena. Use a Docker-local stack for infrastructure verification."
            : provider.name === "docker-local"
              ? "Docker-local is the live-verified provider. The service validates deployment eligibility."
              : "This provider has not been live-verified. Configure it on the server; the service validates eligibility and reports failures."}
        </span>
        <b>
          {value.simulation_mode || provider.name === "mock"
            ? "MOCK"
            : provider.name.toUpperCase()}
        </b>
      </div>
      <div className="comparison-form-grid">
        <form className="panel comparison-form" onSubmit={submit}>
          <div className="panel-head">
            <div>
              <span className="eyebrow">01 / CONFIGURE</span>
              <h2>Engagement details</h2>
            </div>
          </div>
          <div className="comparison-fields">
            <label>
              Provider
              <select
                value={provider.name}
                onChange={(event) => setProviderName(event.target.value)}
                disabled={pending}
              >
                {providers.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name} · {item.verification}
                  </option>
                ))}
              </select>
            </label>
            {custom ? (
              [
                {
                  kind: "attacker",
                  label: "Attacker stations",
                  selected: attackers,
                  set: setAttackers,
                },
                {
                  kind: "victim",
                  label: "Target stations",
                  selected: victims,
                  set: setVictims,
                },
              ].map((group) => (
                <fieldset className="catalog-picks" key={group.kind}>
                  <legend>{group.label}</legend>
                  {launch
                    .value!.catalog.filter((item) => item.kind === group.kind)
                    .map((item) => (
                      <label className="catalog-pick" key={item.id}>
                        <input
                          type="checkbox"
                          disabled={
                            !item.available ||
                            pending ||
                            (!group.selected.includes(item.id) &&
                              group.selected.length >= 8)
                          }
                          checked={group.selected.includes(item.id)}
                          onChange={(event) =>
                            group.set(
                              event.target.checked
                                ? [...group.selected, item.id]
                                : group.selected.filter((id) => id !== item.id),
                            )
                          }
                        />
                        <span>
                          <strong>{item.name}</strong>
                          <small>
                            {item.available
                              ? item.description
                              : item.note || "Unavailable on this provider"}
                          </small>
                        </span>
                      </label>
                    ))}
                </fieldset>
              ))
            ) : (
              <label>
                Registered scenario
                <select
                  required
                  value={selected?.id || ""}
                  onChange={(event) => setScenarioId(event.target.value)}
                >
                  {options.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.name} · {item.nodes} nodes
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Arena name
              <input
                required
                pattern="[a-z0-9][a-z0-9-]{0,39}"
                maxLength={40}
                placeholder="my-arena"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              Purpose
              <select
                value={purpose}
                onChange={(event) => setPurpose(event.target.value)}
              >
                {PURPOSES.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              <small className="field-hint">
                {PURPOSES.find((item) => item.id === purpose)?.meaning} Recorded
                with the arena for the audit trail; it does not change scoring,
                containment or limits.
              </small>
            </label>
            <label>
              Participant
              <select
                value={participant}
                onChange={(event) => setParticipant(event.target.value)}
              >
                <option value="operator">Operator-led</option>
                <option value="mixed">Mixed</option>
                <option value="agent">Agent-led</option>
              </select>
            </label>
            <label>
              Time box
              <select
                value={timeBox}
                onChange={(event) => setTimeBox(Number(event.target.value))}
              >
                <option value={1800}>30 minutes</option>
                <option value={3600}>1 hour</option>
                <option value={7200}>2 hours</option>
                <option value={14400}>4 hours</option>
              </select>
            </label>
          </div>
          {submitError && (
            <div className="form-error" role="alert">
              {submitError}
            </div>
          )}
          <div className="comparison-form-foot">
            <span>
              Launch creates an isolated arena and starts its TTL. The service
              remains authoritative for access and containment.
            </span>
            <button
              className="button button-gold"
              type="submit"
              disabled={!canLaunch || pending}
            >
              {pending ? "Launching…" : "Launch arena ↗"}
            </button>
          </div>
        </form>
        <Panel
          eyebrow="02 / TOPOLOGY"
          title={
            custom ? "Your topology" : selected?.name || "Select a scenario"
          }
          className="topology-panel"
        >
          {custom ? (
            customNodes.length ? (
              <TopologyPreview
                topology={{
                  nodes: customNodes,
                  segments: [
                    {
                      name: "lab",
                      nodes: customNodes.map((node) => node.name),
                    },
                  ],
                  egress: "blocked",
                }}
              />
            ) : (
              <Empty
                title="Choose stations"
                detail="Select at least one attacker and one target from the curated catalog. The service compiles and validates the topology."
              />
            )
          ) : selected ? (
            <>
              <ScenarioTopology key={selected.id} id={selected.id} />
              <p className="scenario-description">
                {selected.description ||
                  "No description supplied for this scenario."}
              </p>
            </>
          ) : (
            <Empty
              title="No compatible scenarios"
              detail="Choose another provider or register a compatible scenario before launching."
              action={
                <a className="inline-action" href="/console/scenarios">
                  Open scenario library ↗
                </a>
              }
            />
          )}
        </Panel>
      </div>
    </>
  );
}
