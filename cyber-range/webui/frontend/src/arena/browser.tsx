import { useState } from "react";
import { postJson } from "../api";
import type { ArenaData } from "../types";
import { Empty, Panel } from "../ui";
import { MapTargetNotice, useMapTarget } from "./target";

type Visit = {
  node: string;
  success: boolean;
  title: string;
  rendered_dom: string;
  dom_bytes: number;
  dom_sha256: string;
  truncated: boolean;
  executed?: boolean | null;
};

export function BrowserWorkbench({ arena }: { arena: ArenaData }) {
  const targets = arena.nodes.filter((node) => node.web_capable);
  const mapTarget = useMapTarget(targets.map((target) => target.name));
  const [node, setNode] = useState(
    mapTarget.accepted || targets[0]?.name || "",
  );
  const [path, setPath] = useState("/");
  const [parameters, setParameters] = useState("");
  const [waitMs, setWaitMs] = useState(1500);
  const [result, setResult] = useState<Visit | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function visit() {
    if (!node || pending) return;
    const params: Record<string, string> = {};
    for (const line of parameters
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean)) {
      const index = line.indexOf("=");
      if (index <= 0) {
        setError("Use one name=value parameter per line.");
        return;
      }
      params[line.slice(0, index).trim()] = line.slice(index + 1).trim();
    }
    setPending(true);
    setError("");
    setResult(null);
    try {
      const response = await postJson<Visit>(
        `/api/console/arenas/${encodeURIComponent(arena.id)}/browser/visit`,
        { node, path: path.trim(), params, wait_ms: waitMs },
      );
      setResult(response);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Browser visit failed",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="browser-grid">
      <Panel eyebrow="01 / BROWSER ORACLE" title="Visit target page">
        <p className="scenario-description">
          Render one declared web target in an isolated browser helper. Enter
          only an arena-relative path; the service selects the host and records
          the visit.
        </p>
        {arena.state === "active" && targets.length ? (
          <form
            className="setup-form browser-form"
            onSubmit={(event) => {
              event.preventDefault();
              void visit();
            }}
          >
            <MapTargetNotice
              requested={mapTarget.requested}
              accepted={mapTarget.accepted}
              tool="Browser"
            />
            <label>
              Target node
              <select
                value={node}
                onChange={(event) => {
                  mapTarget.clear();
                  setNode(event.target.value);
                }}
              >
                {targets.map((target) => (
                  <option key={target.name} value={target.name}>
                    {target.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Relative path
              <input
                value={path}
                required
                maxLength={2048}
                onChange={(event) => setPath(event.target.value)}
                placeholder="/"
              />
            </label>
            <label>
              Query parameters · one name=value per line
              <textarea
                value={parameters}
                rows={4}
                spellCheck={false}
                onChange={(event) => setParameters(event.target.value)}
                placeholder="account=test"
              />
            </label>
            <label>
              Wait after navigation (ms)
              <input
                type="number"
                min={0}
                max={5000}
                value={waitMs}
                onChange={(event) => setWaitMs(Number(event.target.value))}
                required
              />
            </label>
            <button className="button button-gold" disabled={pending}>
              {pending ? "Rendering…" : "Visit page ↗"}
            </button>
          </form>
        ) : (
          <Empty
            title={
              arena.state !== "active" ? "Browser closed" : "No web target"
            }
            detail={
              arena.state !== "active"
                ? "Browser actions stop with the arena. Review retained findings and evidence instead."
                : "This arena has no declared browser-capable target node."
            }
          />
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </Panel>
      <Panel
        eyebrow="02 / OBSERVATION"
        title={result?.title || "Rendered DOM"}
        aside={
          result && (
            <span className="tiny-tag">
              {result.truncated ? "TRUNCATED" : "CAPTURED"}
            </span>
          )
        }
      >
        {result ? (
          <div className="browser-observation">
            <div className="browser-facts">
              <span>
                <small>NODE</small>
                <strong>{result.node}</strong>
              </span>
              <span>
                <small>DOM BYTES</small>
                <strong>{result.dom_bytes}</strong>
              </span>
            </div>
            <div className="target-pin">
              <small>DOM SHA-256</small>
              <code>{result.dom_sha256}</code>
            </div>
            {result.truncated && (
              <p className="state-note">
                The displayed DOM was truncated by the service. The digest
                covers the complete captured output.
              </p>
            )}
            <pre aria-label="Escaped rendered DOM">
              {result.rendered_dom || "The page returned an empty DOM."}
            </pre>
          </div>
        ) : (
          <Empty
            title="No browser observation"
            detail="Visit a target path to inspect its escaped DOM, title, byte count and digest."
          />
        )}
      </Panel>
    </div>
  );
}
