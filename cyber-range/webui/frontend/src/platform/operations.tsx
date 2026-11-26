// UX-14 (FR-19): the operations page. One read-only snapshot of the platform:
// dependencies, the worker heartbeat, queue depth, running helpers, labelled
// Docker resources against this installation's arenas, store sizes, the
// migration revision and the last backup. It refreshes every 15 seconds. The
// only action is reclaiming the leftovers of an arena this installation
// destroyed (or that failed); resources of arenas it does not know are listed
// but never reclaimed here, since they may belong to another installation.
import { useEffect, useState } from "react";
import { postJson } from "../api";
import { ErrorState, Loading, PageHead, useWorkspaceData } from "../ui";
import "./operations.css";

type Arena = {
  lab_id: string;
  containers: {
    name: string;
    status: string;
    role: string | null;
    node: string | null;
  }[];
  networks: number;
  volumes: number;
  images: number;
  state: "live" | "leftover" | "failed" | "unknown";
  reclaim: string | null;
  arena_name: string | null;
  arena_status: string | null;
};
type Snapshot = {
  observed_at: string;
  ready: boolean;
  dependencies: Record<string, string>;
  queues: Record<string, number>;
  worker: {
    alive: boolean;
    age_seconds?: number;
    max_age_seconds?: number;
    reason?: string;
  };
  helpers: {
    id: string;
    arena_id: string | null;
    state: string;
    created_at: string | null;
    deadline: string | null;
  }[];
  arenas: { live: number; known: number };
  docker: {
    available: boolean;
    reason?: string;
    arenas: Arena[];
    orphans?: number;
    unknown?: number;
  };
  stores: {
    name: string;
    bytes: number | null;
    files?: number;
    present: boolean;
    truncated?: boolean;
  }[];
  migration: {
    current: string | null;
    head: string | null;
    up_to_date?: boolean;
    error?: string;
  };
  backup: {
    configured: boolean;
    latest?: string | null;
    age_seconds?: number;
    count?: number;
    error?: string;
  };
  mock_mode?: boolean;
};

const STATE_TEXT: Record<Arena["state"], string> = {
  live: "Live arena",
  leftover: "Left after teardown",
  failed: "Failed arena",
  unknown: "Not known here",
};
const DEP_LABEL: Record<string, string> = {
  database: "Database",
  redis: "Redis (task broker)",
  worker: "Worker",
  docker: "Docker",
};

function bytes(value: number | null | undefined) {
  if (value == null) return "Unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}
function ago(seconds: number | undefined) {
  if (seconds == null) return "";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

function Tile({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "ok" | "bad" | "warn" | "idle";
}) {
  return (
    <div className={`op-tile ${tone}`}>
      <span className="label">{label}</span>
      <b>{value}</b>
      <small>{detail}</small>
    </div>
  );
}

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return (
    <i
      className={`op-dot ${ok ? "ok" : warn ? "warn" : "bad"}`}
      aria-hidden="true"
    />
  );
}

export function OperationsPage() {
  const { value, error, loading, refresh } = useWorkspaceData<Snapshot>(
    "/api/console/operations",
  );
  const [confirming, setConfirming] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 15000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (loading && !value) return <Loading />;
  if (error && !value) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const snap = value;
  const queue = snap.queues.celery;
  const reclaim = async (arena: Arena) => {
    setConfirming(null);
    try {
      await postJson(
        `/api/console/operations/reclaim/${encodeURIComponent(arena.lab_id)}`,
        {},
      );
      setNotice(
        `Reclaim of ${arena.arena_name || arena.lab_id} queued. It disappears from this list once the worker has removed it.`,
      );
      window.setTimeout(refresh, 3000);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Reclaim refused");
    }
  };
  const orphans = snap.docker.arenas.filter((arena) => arena.reclaim);
  return (
    <div className="op">
      <PageHead
        overline="Platform"
        title="Operations"
        subtitle="Service health, queues, Docker resources and storage. Refreshes every 15 seconds. Read-only, except reclaiming what a destroyed arena left behind."
        observed={snap.observed_at}
        action={null}
        refresh={refresh}
      />
      <div className="op-tiles" role="group" aria-label="Summary">
        <Tile
          label="Platform"
          value={snap.ready ? "Ready" : "Not ready"}
          detail={
            snap.ready
              ? "Every required dependency answers"
              : "A required dependency is down"
          }
          tone={snap.ready ? "ok" : "bad"}
        />
        <Tile
          label="Worker"
          value={snap.worker.alive ? "Alive" : "No heartbeat"}
          detail={
            snap.worker.alive
              ? `Last beat ${ago(snap.worker.age_seconds)}`
              : snap.worker.reason ||
                `Stale: last beat ${ago(snap.worker.age_seconds)}`
          }
          tone={snap.worker.alive ? "ok" : "bad"}
        />
        <Tile
          label="Task queue"
          value={queue == null ? "Unknown" : String(queue)}
          detail={queue ? "tasks waiting for a worker" : "nothing waiting"}
          tone={queue == null ? "idle" : queue > 20 ? "warn" : "ok"}
        />
        <Tile
          label="Helpers running"
          value={String(snap.helpers.length)}
          detail="confined PoC jobs queued or running"
          tone="idle"
        />
        <Tile
          label="Docker orphans"
          value={snap.docker.available ? String(orphans.length) : "Unknown"}
          detail={
            snap.docker.available
              ? `${snap.docker.unknown || 0} not known to this installation`
              : snap.docker.reason || "Docker unavailable"
          }
          tone={
            !snap.docker.available ? "idle" : orphans.length ? "warn" : "ok"
          }
        />
      </div>

      <div className="op-grid">
        <section className="panel op-panel" aria-labelledby="op-deps">
          <h2 id="op-deps" className="label">
            Dependencies
          </h2>
          <ul className="op-deps">
            {Object.entries(snap.dependencies).map(([name, state]) => (
              <li key={name}>
                <Dot ok={state === "ok"} />
                <span>{DEP_LABEL[name] || name}</span>
                <span className={state === "ok" ? "muted" : "op-bad"}>
                  {state === "ok" ? "OK" : state}
                </span>
              </li>
            ))}
          </ul>
          {snap.mock_mode && (
            <p className="muted op-note">
              Mock mode: arenas are simulated, so a worker heartbeat is not
              required for readiness.
            </p>
          )}
        </section>

        <section className="panel op-panel" aria-labelledby="op-db">
          <h2 id="op-db" className="label">
            Database and backups
          </h2>
          <dl className="fl-kv">
            <div>
              <dt>Migration</dt>
              <dd>
                <Dot
                  ok={!!snap.migration.up_to_date}
                  warn={!snap.migration.error}
                />{" "}
                {snap.migration.current || "Unversioned"}
                {snap.migration.up_to_date
                  ? " (latest)"
                  : snap.migration.head
                    ? ` (latest is ${snap.migration.head})`
                    : ""}
              </dd>
            </div>
            <div>
              <dt>Last backup</dt>
              <dd>
                {!snap.backup.configured
                  ? "Not visible here"
                  : snap.backup.error
                    ? `Unreadable (${snap.backup.error})`
                    : snap.backup.latest
                      ? `${snap.backup.latest} · ${ago(snap.backup.age_seconds)}`
                      : "None yet"}
              </dd>
            </div>
            <div>
              <dt>Arenas</dt>
              <dd>
                {snap.arenas.live} live of {snap.arenas.known} on record
              </dd>
            </div>
          </dl>
          {!snap.backup.configured && (
            <p className="muted op-note">
              Backups are taken on the host by <code>scripts/backup.sh</code>.
              Mount their directory read-only and set{" "}
              <code>NIDAVELLIR_BACKUP_DIR</code> to show the latest here.
            </p>
          )}
        </section>

        <section className="panel op-panel op-wide" aria-labelledby="op-stores">
          <h2 id="op-stores" className="label">
            Storage
          </h2>
          <table className="op-table">
            <thead>
              <tr>
                <th scope="col">Store</th>
                <th scope="col">Size</th>
                <th scope="col">Files</th>
              </tr>
            </thead>
            <tbody>
              {snap.stores.map((store) => (
                <tr key={store.name}>
                  <td>{store.name}</td>
                  <td>{store.present ? bytes(store.bytes) : "Empty"}</td>
                  <td>
                    {store.files == null
                      ? "·"
                      : `${store.files}${store.truncated ? "+" : ""}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel op-panel op-wide" aria-labelledby="op-docker">
          <h2 id="op-docker" className="label">
            Docker resources by arena
          </h2>
          {notice && (
            <p className="op-notice" role="status">
              {notice}
            </p>
          )}
          {!snap.docker.available ? (
            <p className="muted">
              Docker is not reachable: {snap.docker.reason}.
            </p>
          ) : !snap.docker.arenas.length ? (
            <p className="muted">No labelled Docker resources.</p>
          ) : (
            <table className="op-table">
              <thead>
                <tr>
                  <th scope="col">Arena</th>
                  <th scope="col">State</th>
                  <th scope="col">Containers</th>
                  <th scope="col">Networks · volumes · images</th>
                  <th scope="col">
                    <span className="visually-hidden">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {snap.docker.arenas.map((arena) => (
                  <tr key={arena.lab_id} className={`op-${arena.state}`}>
                    <td>
                      {arena.arena_name && arena.state !== "unknown" ? (
                        <a
                          href={`/console/arena/${encodeURIComponent(arena.lab_id)}`}
                        >
                          {arena.arena_name}
                        </a>
                      ) : (
                        <span>{arena.arena_name || "Unknown arena"}</span>
                      )}
                      <small>{arena.lab_id}</small>
                    </td>
                    <td>
                      <span className={`op-state ${arena.state}`}>
                        {STATE_TEXT[arena.state]}
                      </span>
                    </td>
                    <td>
                      {arena.containers.length}
                      {arena.containers.length > 0 && (
                        <small>
                          {arena.containers
                            .slice(0, 3)
                            .map(
                              (c) =>
                                `${c.node || c.role || c.name} (${c.status})`,
                            )
                            .join(", ")}
                          {arena.containers.length > 3 ? "…" : ""}
                        </small>
                      )}
                    </td>
                    <td>
                      {arena.networks} · {arena.volumes} · {arena.images}
                    </td>
                    <td className="op-act">
                      {arena.reclaim ? (
                        confirming === arena.lab_id ? (
                          <>
                            <button
                              type="button"
                              className="button button-danger"
                              onClick={() => void reclaim(arena)}
                            >
                              Remove resources
                            </button>
                            <button
                              type="button"
                              className="button button-outline"
                              onClick={() => setConfirming(null)}
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            className="button button-outline"
                            onClick={() => setConfirming(arena.lab_id)}
                          >
                            Reclaim
                          </button>
                        )
                      ) : arena.state === "unknown" ? (
                        <span
                          className="muted"
                          title="This installation has no record of this arena. It may be another installation's on the same Docker host, so it is never reclaimed from here."
                        >
                          Not reclaimable here
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section
          className="panel op-panel op-wide"
          aria-labelledby="op-helpers"
        >
          <h2 id="op-helpers" className="label">
            Running helpers
          </h2>
          {snap.helpers.length ? (
            <table className="op-table">
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Arena</th>
                  <th scope="col">State</th>
                  <th scope="col">Deadline</th>
                </tr>
              </thead>
              <tbody>
                {snap.helpers.map((job) => (
                  <tr key={job.id}>
                    <td>{job.id}</td>
                    <td>{job.arena_id}</td>
                    <td>{job.state}</td>
                    <td>{job.deadline || "·"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No confined PoC jobs queued or running.</p>
          )}
        </section>
      </div>
    </div>
  );
}
