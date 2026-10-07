import { useRef, useState } from "react";
import { postJson } from "../api";
import type { ArenaData } from "../types";
import {
  Empty,
  ErrorState,
  formatObserved,
  Loading,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

type Score = {
  mode: string | null;
  value: number | boolean | string | null;
  tier: string | null;
  progress_rate: number | null;
  milestones: { id: string; reached: boolean; detail: string | null }[];
  signals: {
    distinct_fault_sites: number | null;
    counts: Record<string, number>;
  };
  confirmed_findings: number | null;
  findings_submitted: number | null;
  total_vulnerabilities: number | null;
  found: string[];
  points_earned: number | null;
  points_total: number | null;
  manifest: {
    id: string;
    title: string | null;
    cwe: string | null;
    node: string | null;
    severity: string | null;
    found: boolean;
  }[];
};
type Trace = {
  model: string | null;
  provider: string | null;
  scaffold: string | null;
  stance: string | null;
  trace_id: string | null;
  export: string;
};
type Forwards = {
  state: string;
  reason: string;
  footholds: string[];
  services: { target: string; service: string }[];
  forwards: {
    id: string;
    target: string;
    service_id: string;
    state: string;
    expires_at: string | null;
  }[];
};

function percent(value: number | null) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

export function ScoreWorkbench({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const { value, error, loading, refresh } = useWorkspaceData<{
    score: Score | null;
  }>(`/api/console/arenas/${id}/score`);
  const [reveal, setReveal] = useState(false);
  const trace = useWorkspaceData<{ trace: Trace | null }>(
    `/api/console/arenas/${id}/trace`,
  );
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  const score = value?.score;
  const found = score?.found.length ?? 0;
  const total = score?.total_vulnerabilities ?? 0;
  return (
    <div className="record-grid">
      <Panel
        eyebrow="01 / ASSESSMENT"
        title="Score"
        className="record-score"
        aside={score?.tier && <span className="tiny-tag">{score.tier}</span>}
      >
        {score ? (
          <>
            <div className="score-strip">
              <div>
                <small>MODE</small>
                <strong>{score.mode || "unknown"}</strong>
              </div>
              <div>
                <small>PROGRESS</small>
                <strong>{percent(score.progress_rate)}</strong>
              </div>
              <div>
                <small>CONFIRMED</small>
                <strong>
                  {score.confirmed_findings ?? 0}
                  <span> of {score.findings_submitted ?? 0} submitted</span>
                </strong>
              </div>
              <div>
                <small>FAULT SITES</small>
                <strong>{score.signals.distinct_fault_sites ?? 0}</strong>
              </div>
            </div>
            <div
              className="score-meter"
              role="meter"
              aria-label="Progress rate"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round((score.progress_rate ?? 0) * 100)}
            >
              <svg
                viewBox="0 0 100 4"
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <rect className="score-meter-track" width="100" height="4" />
                <rect
                  className="score-meter-fill"
                  width={Math.round((score.progress_rate ?? 0) * 100)}
                  height="4"
                />
              </svg>
            </div>
            {score.milestones.length > 0 && (
              <ol className="score-milestones" aria-label="Milestones">
                {score.milestones.map((item) => (
                  <li
                    key={item.id}
                    className={item.reached ? "reached" : ""}
                    title={item.detail || undefined}
                  >
                    <i aria-hidden="true">{item.reached ? "✓" : "○"}</i>
                    {item.id.replaceAll("_", " ")}
                  </li>
                ))}
              </ol>
            )}
            {Object.keys(score.signals.counts).length > 0 && (
              <p className="score-signals">
                Monitor signals:{" "}
                {Object.entries(score.signals.counts)
                  .map(
                    ([kind, count]) => `${kind.replaceAll("_", " ")} ${count}`,
                  )
                  .join(" · ")}
              </p>
            )}
          </>
        ) : (
          <Empty
            title="No score yet"
            detail="The service scores an arena once it has findings, signals or a scenario manifest."
          />
        )}
      </Panel>
      <Panel
        eyebrow="02 / GROUND TRUTH"
        title="Challenges"
        className="record-challenges"
        aside={
          score && score.manifest.length > 0 ? (
            <label className="reveal-toggle">
              <input
                type="checkbox"
                checked={reveal}
                onChange={(event) => setReveal(event.target.checked)}
              />{" "}
              Reveal
            </label>
          ) : null
        }
      >
        {!score || score.manifest.length === 0 ? (
          <Empty
            title="No known vulnerabilities"
            detail="Discovery arenas have no manifest; findings are scored from confirmed proof and signals."
          />
        ) : !reveal ? (
          <Empty
            title="Hidden by default"
            detail={`${score.manifest.length} known vulnerabilities. Revealing shows the operator baseline; it is never shown to the agent.`}
          />
        ) : (
          <>
            <p className="score-signals">
              {found} of {total} found · {score.points_earned ?? 0} of{" "}
              {score.points_total ?? 0} points
            </p>
            <div className="challenge-list">
              {score.manifest.map((item) => (
                <div
                  key={item.id}
                  className={`challenge-row${item.found ? " found" : ""}`}
                >
                  <Status value={item.found ? "found" : "open"} />
                  <span>
                    <strong>{item.title || item.id}</strong>
                    <small>
                      {item.id} · {item.cwe || "no CWE"} ·{" "}
                      {item.node || "any node"}
                    </small>
                  </span>
                  <b>{item.severity || "—"}</b>
                </div>
              ))}
            </div>
          </>
        )}
      </Panel>
      <Panel
        eyebrow="03 / ATTRIBUTION"
        title="Run trace"
        className="record-trace"
      >
        {trace.value?.trace ? (
          <>
            <dl className="record-facts">
              <div>
                <dt>Model</dt>
                <dd>{trace.value.trace.model || "not declared"}</dd>
              </div>
              <div>
                <dt>Provider</dt>
                <dd>{trace.value.trace.provider || "not declared"}</dd>
              </div>
              <div>
                <dt>Scaffold</dt>
                <dd>{trace.value.trace.scaffold || "bring-your-own"}</dd>
              </div>
              <div>
                <dt>Stance</dt>
                <dd>{trace.value.trace.stance || "—"}</dd>
              </div>
              <div>
                <dt>Trace</dt>
                <dd>{trace.value.trace.trace_id || "—"}</dd>
              </div>
            </dl>
            <div className="panel-foot">
              <span>
                Attribution is self-declared by the agent; the arena identity
                and verdicts are not.
              </span>
              <a className="inline-action" href={trace.value.trace.export}>
                Export eval row ↗
              </a>
            </div>
          </>
        ) : (
          <Empty
            title="No agent run"
            detail="Attribution appears once a connected agent has worked this arena."
          />
        )}
      </Panel>
    </div>
  );
}

export function ForwardsWorkbench({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const { value, error, loading, refresh } = useWorkspaceData<Forwards>(
    `/api/console/arenas/${id}/forwards`,
  );
  const [foothold, setFoothold] = useState("");
  const [service, setService] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const forwardAction = useRef<{ destination: string; key: string } | null>(
    null,
  );
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const ready = value.state === "ready" && arena.state === "active";
  const chosenFoothold = foothold || value.footholds[0] || "";
  const chosenService =
    service ||
    (value.services[0]
      ? `${value.services[0].target}:${value.services[0].service}`
      : "");
  async function run(
    path: string,
    body: unknown,
    done: string,
    onSuccess?: () => void,
  ) {
    if (pending) return;
    setPending(true);
    setMessage("");
    try {
      await postJson(path, body);
      onSuccess?.();
      setMessage(done);
      refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Request failed");
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="record-grid">
      <Panel
        eyebrow="01 / LEASE"
        title="Open a service forward"
        aside={<Status value={ready ? "ready" : value.state} />}
      >
        <p className="scenario-description">
          A forward relays one declared target service through an attacker
          foothold for 120 seconds. The service checks policy on every lease.
        </p>
        {ready && value.footholds.length && value.services.length ? (
          <form
            className="registry-form forward-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (pending) return;
              const [target, service_id] = chosenService.split(":");
              const destination = JSON.stringify([
                arena.id,
                chosenFoothold,
                target,
                service_id,
              ]);
              if (forwardAction.current?.destination !== destination) {
                const bytes = crypto.getRandomValues(new Uint8Array(16));
                forwardAction.current = {
                  destination,
                  key: Array.from(bytes, (byte) =>
                    byte.toString(16).padStart(2, "0"),
                  ).join(""),
                };
              }
              void run(
                `/api/console/arenas/${id}/forwards`,
                {
                  foothold: chosenFoothold,
                  target,
                  service_id,
                  idempotency_key: forwardAction.current.key,
                },
                "Forward lease opened.",
                () => {
                  forwardAction.current = null;
                },
              );
            }}
          >
            <label>
              Foothold
              <select
                value={chosenFoothold}
                disabled={pending}
                onChange={(event) => setFoothold(event.target.value)}
              >
                {value.footholds.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Service
              <select
                value={chosenService}
                disabled={pending}
                onChange={(event) => setService(event.target.value)}
              >
                {value.services.map((item) => (
                  <option
                    key={`${item.target}:${item.service}`}
                    value={`${item.target}:${item.service}`}
                  >
                    {item.target} / {item.service}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button button-gold"
              type="submit"
              disabled={pending}
            >
              {pending ? "Opening…" : "Open 120-second forward"}
            </button>
          </form>
        ) : (
          <Empty
            title="Forwarding unavailable"
            detail={
              arena.state !== "active"
                ? `Unavailable while the arena is ${arena.state}.`
                : value.reason
                  ? `Unavailable: ${value.reason.replaceAll("_", " ")}.`
                  : "This arena declares no forwardable services."
            }
          />
        )}
        {message && (
          <p className="gate-message" role="status">
            {message}
          </p>
        )}
      </Panel>
      <Panel
        eyebrow="02 / LEASES"
        title="Forward leases"
        aside={<span className="tiny-tag">{value.forwards.length} LEASES</span>}
      >
        {value.forwards.length ? (
          <>
            <div className="challenge-list">
              {value.forwards.map((item) => (
                <div className="challenge-row" key={item.id}>
                  <Status value={item.state} />
                  <span>
                    <strong>
                      {item.target} / {item.service_id}
                    </strong>
                    <small>
                      {item.id} · expires{" "}
                      {item.expires_at
                        ? formatObserved(item.expires_at)
                        : "unknown"}
                    </small>
                  </span>
                  {["open", "connecting"].includes(item.state) && (
                    <button
                      type="button"
                      className="button button-outline"
                      disabled={pending}
                      onClick={() =>
                        void run(
                          `/api/console/arenas/${id}/forwards/${encodeURIComponent(item.id)}/revoke`,
                          {},
                          "Forward lease revoked.",
                        )
                      }
                    >
                      Revoke
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="panel-foot">
              <span>
                Connect locally with{" "}
                <code>
                  python3 scripts/nv-forward-client.py --arena {arena.id}{" "}
                  --forward FORWARD_ID --listen-port 18080
                </code>
              </span>
            </div>
          </>
        ) : (
          <Empty
            title="No leases"
            detail="Opened forwards and their expiry appear here."
          />
        )}
      </Panel>
    </div>
  );
}
