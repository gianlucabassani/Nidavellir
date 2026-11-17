import { useEffect, useRef, useState } from "react";
import type React from "react";
import { MapTargetNotice, useMapTarget } from "./target";
import type { ArenaData, PocJob } from "../types";
import {
  useWorkspaceData,
  Status,
  formatObserved,
  Panel,
  Empty,
  Loading,
  ErrorState,
} from "../ui";

export function PocWorkbench({ arena }: { arena: ArenaData }) {
  const path = `/api/arenas/${encodeURIComponent(arena.id)}/poc-jobs`;
  const { value, error, loading, refresh } = useWorkspaceData<{
    jobs: PocJob[];
  }>(path);
  const [source, setSource] = useState(
    'import nidavellir\n\nresponse = nidavellir.request("/")\nprint(response["status"])',
  );
  const pocTargets = arena.nodes.filter(
    (node) => !node.foothold && node.service_count > 0,
  );
  const mapTarget = useMapTarget(pocTargets.map((node) => node.name));
  const [target, setTarget] = useState(mapTarget.accepted || "");
  const [files, setFiles] = useState(
    new URLSearchParams(window.location.search).get("file") || "",
  );
  const [timeout, setTimeoutSeconds] = useState(30);
  const [memory, setMemory] = useState(128);
  const [pids, setPids] = useState(32);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<PocJob | null>(null);
  const retryKey = useRef("");
  const jobs = value?.jobs || [];
  const active = jobs.some((job) => ["queued", "running"].includes(job.state));
  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(refresh, 2000);
    return () => window.clearTimeout(timer);
  }, [active, value]);
  async function post(url: string, body: Record<string, unknown>) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken":
          document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
            ?.content || "",
      },
      body: JSON.stringify(body),
    });
    if (response.redirected && new URL(response.url).pathname === "/login") {
      window.location.assign(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
      );
      throw new Error("Session expired");
    }
    const payload = await response.json();
    if (!response.ok)
      throw new Error(payload.error || `Action rejected (${response.status})`);
    return payload;
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || !source.trim()) return;
    setPending(true);
    setMessage("");
    if (!retryKey.current) retryKey.current = `console-${crypto.randomUUID()}`;
    try {
      await post(path, {
        source,
        target_node: target || null,
        transfer_files: files
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        timeout_seconds: timeout,
        memory_mb: memory,
        pids,
        idempotency_key: retryKey.current,
      });
      retryKey.current = "";
      setMessage(
        "Confined job accepted. Its result and cleanup state will appear below.",
      );
      refresh();
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Submission failed",
      );
    } finally {
      setPending(false);
    }
  }
  async function inspect(job: PocJob) {
    setMessage("");
    try {
      const response = await fetch(`${path}/${encodeURIComponent(job.id)}`, {
        credentials: "same-origin",
      });
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
        );
        return;
      }
      const payload: { job?: PocJob; error?: string } = await response.json();
      if (!response.ok || !payload.job)
        throw new Error(payload.error || "Job unavailable");
      setSelected(payload.job);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Job unavailable");
    }
  }
  async function cancel(job: PocJob) {
    if (pending) return;
    setPending(true);
    setMessage("");
    try {
      await post(`${path}/${encodeURIComponent(job.id)}/cancel`, {});
      setMessage(`Cancellation requested for job ${job.id.slice(0, 8)}.`);
      refresh();
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Cancellation failed",
      );
    } finally {
      setPending(false);
    }
  }
  const runnable =
    arena.state === "active" && arena.provider === "docker-local";
  return (
    <div className="poc-grid">
      <Panel eyebrow="01 / CONFINED EXECUTION" title="Python PoC">
        {runnable ? (
          <form className="poc-form" onSubmit={submit}>
            <MapTargetNotice
              requested={mapTarget.requested}
              accepted={mapTarget.accepted}
              tool="PoC"
            />
            <p>
              Runs in a disposable networkless worker. Select one declared HTTP
              target to use the fixed relay.
            </p>
            <label>
              Python source
              <textarea
                required
                rows={14}
                spellCheck={false}
                value={source}
                onChange={(event) => {
                  setSource(event.target.value);
                  retryKey.current = "";
                }}
              />
            </label>
            <div className="poc-limits">
              <label>
                HTTP target
                <select
                  value={target}
                  onChange={(event) => {
                    mapTarget.clear();
                    setTarget(event.target.value);
                    retryKey.current = "";
                  }}
                >
                  <option value="">No network access</option>
                  {pocTargets.map((node) => (
                    <option key={node.name} value={node.name}>
                      {node.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Timeout (s)
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={timeout}
                  onChange={(event) => {
                    setTimeoutSeconds(Number(event.target.value));
                    retryKey.current = "";
                  }}
                />
              </label>
              <label>
                Memory (MiB)
                <input
                  type="number"
                  min={32}
                  max={256}
                  value={memory}
                  onChange={(event) => {
                    setMemory(Number(event.target.value));
                    retryKey.current = "";
                  }}
                />
              </label>
              <label>
                PID limit
                <input
                  type="number"
                  min={8}
                  max={128}
                  value={pids}
                  onChange={(event) => {
                    setPids(Number(event.target.value));
                    retryKey.current = "";
                  }}
                />
              </label>
            </div>
            <label>
              Foothold transfer files (optional)
              <input
                value={files}
                onChange={(event) => {
                  setFiles(event.target.value);
                  retryKey.current = "";
                }}
                placeholder="payload.bin, corpus/request.txt"
              />
            </label>
            <div className="poc-submit">
              <span>
                The service enforces the arena gate, budget, target and resource
                limits.
              </span>
              <button
                className="button button-gold"
                type="submit"
                disabled={pending}
              >
                {pending ? "Submitting…" : "Run confined PoC ↗"}
              </button>
            </div>
          </form>
        ) : (
          <Empty
            title="Execution unavailable"
            detail={
              arena.state === "destroyed"
                ? "This is a retained read-only arena record."
                : "Confined execution requires an active Docker-local arena."
            }
          />
        )}
      </Panel>
      <Panel
        eyebrow="02 / JOBS & OUTPUT"
        title="Execution record"
        aside={
          <button className="subtle-link" type="button" onClick={refresh}>
            Refresh ↻
          </button>
        }
      >
        {message && (
          <p className="poc-message" role="status">
            {message}
          </p>
        )}
        {loading && !value ? (
          <Loading />
        ) : error ? (
          <ErrorState message={error} refresh={refresh} />
        ) : jobs.length ? (
          <div className="poc-jobs">
            {jobs.map((job) => (
              <div className="poc-job" key={job.id}>
                <div>
                  <strong>{job.id.slice(0, 8)}</strong>
                  <Status value={job.state} />
                  <small>
                    {job.target_node || "networkless"} ·{" "}
                    {job.created_at
                      ? formatObserved(job.created_at)
                      : "time unknown"}
                  </small>
                  <small>Cleanup: {job.cleanup_state || "pending"}</small>
                </div>
                <div>
                  <button
                    type="button"
                    className="button button-outline"
                    onClick={() => inspect(job)}
                  >
                    Inspect
                  </button>
                  {runnable && ["queued", "running"].includes(job.state) && (
                    <button
                      type="button"
                      className="button button-danger"
                      disabled={pending}
                      onClick={() => cancel(job)}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="No PoC jobs"
            detail="Submitted jobs and their cleanup state will appear here."
          />
        )}
        {selected && (
          <div className="poc-result">
            <div>
              <strong>
                Job {selected.id.slice(0, 8)} · {selected.state}
              </strong>
              <button type="button" onClick={() => setSelected(null)}>
                Close
              </button>
            </div>
            <small>Input digest: {selected.input_digest}</small>
            <small>Cleanup: {selected.cleanup_state || "pending"}</small>
            <h3>Stdout</h3>
            <pre>{selected.result?.stdout || "No stdout recorded"}</pre>
            {selected.result?.stdout_sha256 && (
              <small>SHA-256: {selected.result.stdout_sha256}</small>
            )}
            <h3>Stderr</h3>
            <pre>{selected.result?.stderr || "No stderr recorded"}</pre>
            {selected.result?.stderr_sha256 && (
              <small>SHA-256: {selected.result.stderr_sha256}</small>
            )}
            {selected.result?.error && (
              <p className="form-error">{selected.result.error}</p>
            )}
            {selected.cleanup_error && (
              <p className="form-error">Cleanup: {selected.cleanup_error}</p>
            )}
            {selected.result?.artifacts?.length ? (
              <div className="poc-artifacts">
                <h3>Artifacts</h3>
                {selected.result.artifacts.map((artifact) => (
                  <p key={`${artifact.sha256}-${artifact.path}`}>
                    {artifact.path} · {artifact.bytes} bytes · {artifact.sha256}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </Panel>
    </div>
  );
}
