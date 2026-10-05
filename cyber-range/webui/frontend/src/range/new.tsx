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

export function NewArena() {
  const { value, error, loading, refresh } = useWorkspaceData<RangeData>(
    paths.range,
  );
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
  if (!value) return null;
  const options = value.scenarios.filter(
    (item) =>
      item.provider_class === "container" || item.provider_class === "any",
  );
  const selected = options.find((item) => item.id === scenarioId) || options[0];
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || pending) return;
    setPending(true);
    setSubmitError("");
    try {
      const response = await fetch("/api/console/arenas", {
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
          scenario: selected.id,
          instance_id: name.trim(),
          engagement_purpose: purpose,
          participant_mode: participant,
          engagement_time_box_seconds: timeBox,
        }),
      });
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
        action={null}
        refresh={refresh}
      />
      <div className="scope-note">
        <strong>
          {value.simulation_mode ? "Simulation mode" : "Provider"}
        </strong>
        <span>
          {value.simulation_mode
            ? "The orchestrator validates this request, then simulates the arena. Use a Docker-local stack for infrastructure verification."
            : "Docker-local is selected explicitly. The orchestrator validates images, policy and deployment eligibility."}
        </span>
        <b>{value.simulation_mode ? "MOCK" : "DOCKER-LOCAL"}</b>
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
                <option value="discovery">Discovery</option>
                <option value="research">Research</option>
                <option value="calibration">Calibration</option>
                <option value="benchmark">Benchmark</option>
              </select>
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
              disabled={!selected || pending}
            >
              {pending ? "Launching…" : "Launch arena ↗"}
            </button>
          </div>
        </form>
        <Panel
          eyebrow="02 / TOPOLOGY"
          title={selected?.name || "Select a scenario"}
          className="topology-panel"
        >
          {selected ? (
            <>
              <ScenarioTopology key={selected.id} id={selected.id} />
              <p className="scenario-description">
                {selected.description ||
                  "No description supplied for this scenario."}
              </p>
            </>
          ) : (
            <Empty
              title="No Docker-local scenarios"
              detail="Register a container scenario before launching an arena."
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
