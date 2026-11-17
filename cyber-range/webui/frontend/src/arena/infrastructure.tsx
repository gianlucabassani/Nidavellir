import { useEffect, useState } from "react";
import { ApiError, getJson, postJson } from "../api";
import type { ArenaData } from "../types";
import { Empty, Panel, Status } from "../ui";

type Preflight = {
  status: string;
  phase?: string;
  target?: {
    kind?: string;
    source?: string;
    platform?: string;
    identity?: { digest?: string; platform?: string };
  };
  reset_contract?: { strategy?: string };
  checks?: { id: string; ok: boolean; required?: boolean; detail?: string }[];
};
type Workspace = { node: string; kind?: string; writable?: boolean };
type DiffPage = {
  diff: string;
  changed_files: { path: string; untracked?: boolean }[];
  changed_file_count: number;
  baseline?: string;
  start_line: number;
  returned_lines: number;
  total_lines: number;
  next_start_line?: number | null;
  note?: string;
  workspace?: Workspace;
};

export function Infrastructure({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [preflightError, setPreflightError] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceError, setWorkspaceError] = useState("");
  const [node, setNode] = useState("");
  const [base, setBase] = useState("HEAD");
  const [path, setPath] = useState("");
  const [files, setFiles] = useState<DiffPage["changed_files"]>([]);
  const [includeUntracked, setIncludeUntracked] = useState(false);
  const [diff, setDiff] = useState<DiffPage | null>(null);
  const [diffError, setDiffError] = useState("");
  const [busy, setBusy] = useState(false);
  const [artifact, setArtifact] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getJson<Preflight>(`/api/arenas/${id}/preflight`, controller.signal)
      .then(setPreflight)
      .catch((reason: unknown) => {
        if (
          !controller.signal.aborted &&
          !(reason instanceof ApiError && reason.status === 404)
        )
          setPreflightError(
            reason instanceof Error ? reason.message : "Preflight unavailable",
          );
      });
    if (arena.state === "active")
      getJson<{ workspaces: Workspace[] }>(
        `/api/arenas/${id}/workspaces`,
        controller.signal,
      )
        .then((result) => {
          setWorkspaces(result.workspaces || []);
          setNode(result.workspaces?.[0]?.node || "");
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted)
            setWorkspaceError(
              reason instanceof Error
                ? reason.message
                : "Workspaces unavailable",
            );
        });
    return () => controller.abort();
  }, [id, arena.state]);
  async function loadDiff(startLine = 0) {
    if (!node || busy) return;
    setBusy(true);
    setDiffError("");
    try {
      const query = new URLSearchParams({
        base: base.trim() || "HEAD",
        context_lines: "3",
        start_line: String(startLine),
        max_lines: "300",
      });
      if (path) query.set("path", path);
      const result = await getJson<DiffPage>(
        `/api/arenas/${id}/workspaces/${encodeURIComponent(node)}/diff?${query}`,
      );
      setFiles(result.changed_files || []);
      setDiff(
        startLine && diff
          ? { ...result, diff: diff.diff + result.diff }
          : result,
      );
    } catch (reason) {
      setDiffError(
        reason instanceof Error ? reason.message : "Diff unavailable",
      );
    } finally {
      setBusy(false);
    }
  }
  async function exportPatch() {
    if (!node || busy) return;
    setBusy(true);
    setDiffError("");
    try {
      const result = await postJson<{
        patch?: string;
        artifact?: { digest?: string };
      }>(
        `/api/arenas/${id}/workspaces/${encodeURIComponent(node)}/patch-artifacts`,
        {
          base: base.trim() || "HEAD",
          path: path || null,
          context_lines: 3,
          include_untracked_paths:
            includeUntracked &&
            path &&
            files.find((item) => item.path === path)?.untracked
              ? [path]
              : [],
        },
      );
      const digest = result.artifact?.digest || "";
      setArtifact(digest);
      if (result.patch) {
        const url = URL.createObjectURL(
          new Blob([result.patch], { type: "text/x-diff" }),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = `${node}-${digest.slice(-12) || "changes"}.patch`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (reason) {
      setDiffError(
        reason instanceof Error ? reason.message : "Patch export failed",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="infrastructure-grid">
      <Panel
        eyebrow="01 / TARGET IDENTITY"
        title="Preflight & reset"
        aside={preflight && <Status value={preflight.status || "pending"} />}
      >
        {preflight ? (
          <>
            <div className="arena-detail-list">
              <div>
                <span>Source</span>
                <strong>{preflight.target?.source || "—"}</strong>
              </div>
              <div>
                <span>Identity</span>
                <code>{preflight.target?.identity?.digest || "Resolving"}</code>
              </div>
              <div>
                <span>Platform</span>
                <strong>
                  {preflight.target?.platform ||
                    preflight.target?.identity?.platform ||
                    "Provider native"}
                </strong>
              </div>
              <div>
                <span>Reset strategy</span>
                <strong>
                  {preflight.reset_contract?.strategy || "Unknown"}
                </strong>
              </div>
            </div>
            <div className="preflight-checks">
              {(preflight.checks || []).map((check) => (
                <div key={check.id}>
                  <Status value={check.ok ? "passed" : "failed"} />
                  <span>
                    <strong>{check.id.replaceAll("_", " ")}</strong>
                    <small>
                      {check.detail ||
                        (check.required ? "Required check" : "Optional check")}
                    </small>
                  </span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <Empty
            title="No target preflight"
            detail={
              preflightError ||
              "This arena has no research target manifest or its preflight has not been recorded."
            }
          />
        )}
      </Panel>
      <Panel eyebrow="02 / SOURCE CHANGES" title="Workspace diff">
        {arena.state !== "active" ? (
          <Empty
            title="Workspace closed"
            detail="Retained evidence remains available in the Evidence tab. Source workspaces close with the arena."
          />
        ) : workspaceError ? (
          <p className="form-error" role="alert">
            {workspaceError}
          </p>
        ) : workspaces.length ? (
          <>
            <form
              className="setup-form infrastructure-form"
              onSubmit={(event) => {
                event.preventDefault();
                void loadDiff();
              }}
            >
              <label>
                Workspace node
                <select
                  value={node}
                  onChange={(event) => {
                    setNode(event.target.value);
                    setPath("");
                    setIncludeUntracked(false);
                    setDiff(null);
                    setFiles([]);
                    setArtifact("");
                  }}
                >
                  {workspaces.map((item) => (
                    <option key={item.node} value={item.node}>
                      {item.node} · {item.writable ? "writable" : "read only"}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Baseline
                <input
                  value={base}
                  maxLength={80}
                  onChange={(event) => {
                    setBase(event.target.value);
                    setDiff(null);
                    setArtifact("");
                  }}
                />
              </label>
              <label>
                Path
                <select
                  value={path}
                  onChange={(event) => {
                    setPath(event.target.value);
                    setIncludeUntracked(false);
                    setDiff(null);
                    setArtifact("");
                  }}
                >
                  <option value="">All tracked changes</option>
                  {files.map((file) => (
                    <option key={file.path} value={file.path}>
                      {file.untracked ? "? " : ""}
                      {file.path}
                    </option>
                  ))}
                </select>
              </label>
              {path && files.find((item) => item.path === path)?.untracked && (
                <label className="form-check">
                  <input
                    type="checkbox"
                    checked={includeUntracked}
                    onChange={(event) =>
                      setIncludeUntracked(event.target.checked)
                    }
                  />{" "}
                  Include this untracked file in patch export
                </label>
              )}
              <div className="settings-model-actions">
                <button className="button button-outline" disabled={busy}>
                  Inspect changes ↗
                </button>
                <button
                  type="button"
                  className="button button-gold"
                  disabled={busy}
                  onClick={() => void exportPatch()}
                >
                  Export patch ↗
                </button>
              </div>
            </form>
            {diff && (
              <div className="infrastructure-diff">
                <div>
                  <strong>{diff.changed_file_count} changed files</strong>
                  <small>
                    {diff.baseline || base} · {diff.total_lines} lines
                  </small>
                </div>
                <pre>
                  {diff.diff || "No tracked changes against this baseline."}
                </pre>
                {diff.note && <p>{diff.note}</p>}
                {diff.next_start_line != null && (
                  <button
                    className="button button-outline"
                    disabled={busy}
                    onClick={() => void loadDiff(diff.next_start_line!)}
                  >
                    Load more ↗
                  </button>
                )}
              </div>
            )}
            {artifact && (
              <p className="gate-message" role="status">
                Patch artifact <code>{artifact}</code> ·{" "}
                <a
                  href={`/console/arena/${id}?tab=findings&artifact=${encodeURIComponent(artifact)}`}
                >
                  Attach to finding ↗
                </a>
              </p>
            )}
            {diffError && (
              <p className="form-error" role="alert">
                {diffError}
              </p>
            )}
          </>
        ) : (
          <Empty
            title="No source workspace"
            detail="This arena does not expose an operator-inspectable source checkout."
          />
        )}
      </Panel>
    </div>
  );
}
