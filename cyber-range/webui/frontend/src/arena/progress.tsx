import type { ArenaData, DeployPhase } from "../types";

// UX-05: launch progress from the worker's deploy_phase events. The page never
// waits on the launch request; this reads the arena record, so leaving and
// coming back shows the same progress.
const PHASES: { id: DeployPhase["phase"]; label: string }[] = [
  { id: "network", label: "Network" },
  { id: "pull", label: "Image pull" },
  { id: "nodes", label: "Nodes" },
  { id: "readiness", label: "Readiness" },
];

const LAUNCHING = ["pending", "deploying"];

export function isLaunching(state: string) {
  return LAUNCHING.includes(state.toLowerCase());
}

function phaseState(
  id: DeployPhase["phase"],
  phases: DeployPhase[],
  launching: boolean,
): { state: string; text: string } {
  const entry = phases.find((item) => item.phase === id);
  const nodesDone = phases.some(
    (item) => item.phase === "nodes" && item.state === "done",
  );
  if (!entry) {
    if (id === "pull" && nodesDone)
      return { state: "skipped", text: "Images already local" };
    return { state: "waiting", text: launching ? "Waiting" : "Not reported" };
  }
  if (entry.state === "started")
    return {
      state: "running",
      text:
        id === "pull" && entry.image
          ? `Pulling ${entry.image}`
          : id === "nodes" && entry.total
            ? `Starting ${entry.total} ${entry.total === 1 ? "node" : "nodes"}`
            : "In progress",
    };
  if (entry.state === "failed")
    return { state: "failed", text: entry.error || entry.status || "Failed" };
  if (entry.state === "skipped")
    return { state: "skipped", text: entry.reason || "Not needed" };
  return { state: "done", text: "Done" };
}

export function LaunchProgress({ arena }: { arena: ArenaData }) {
  const phases = arena.deploy_phases || [];
  const launching = isLaunching(arena.state);
  const failed = phases.some((item) => item.state === "failed");
  if (!launching && !failed) return null;
  return (
    <section
      className="launch-progress"
      aria-labelledby="launch-progress-title"
    >
      <h2 id="launch-progress-title">
        {launching ? "Launching arena" : "Launch failed"}
      </h2>
      <p>
        {launching
          ? "The service is provisioning this arena. You can leave this page; progress continues and is shown here when you return."
          : "Provisioning stopped at the phase marked below. The arena record keeps the error."}
      </p>
      <ol>
        {PHASES.map((phase) => {
          const status = phaseState(phase.id, phases, launching);
          return (
            <li
              key={phase.id}
              className={`launch-phase launch-phase-${status.state}`}
              aria-current={status.state === "running" ? "step" : undefined}
            >
              <strong>{phase.label}</strong>
              <span>{status.text}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
