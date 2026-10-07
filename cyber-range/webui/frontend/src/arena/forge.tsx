import { useState } from "react";
import type { ArenaData } from "../types";
import { formatObserved, Status, useWorkspaceData } from "../ui";
import { SegmentMap } from "../topology/SegmentMap";
import "./forge.css";

type Action = "stop" | "resume" | "reset" | "destroy";
type Station = ArenaData["nodes"][number];
type Signal = {
  kind: string | null;
  node: string | null;
  severity: string | null;
  summary: string | null;
  ts: string | null;
};

const REASONS: Record<string, string> = {
  provider_not_implemented: "this provider does not support it",
  arena_not_active: "the arena is not active",
  gate_stopped: "research is stopped",
};

function reasonText(code: string) {
  return REASONS[code] || code.replaceAll("_", " ") || "not reported";
}

function portList(ports?: number[]) {
  return ports && ports.length ? ports.map((port) => `:${port}`).join(" ") : "";
}

const ACRONYMS = new Set([
  "api",
  "dns",
  "ftp",
  "ldap",
  "smb",
  "smtp",
  "ssh",
  "sso",
  "vpn",
]);

function roleLabel(station: Station) {
  if (station.foothold) return "Attacker";
  if (!station.role || station.role === "victim") return "Target";
  if (ACRONYMS.has(station.role.toLowerCase()))
    return station.role.toUpperCase();
  return station.role[0].toUpperCase() + station.role.slice(1);
}

export function stationDetail(station: Station) {
  if (station.foothold) return "Attacker foothold";
  const ports = portList(station.declared_ports);
  return `${roleLabel(station)} · ${ports || "no declared ports"}`;
}

const TOOLS = [
  {
    op: "http",
    mark: "⇄",
    description: "Capture and replay transactions",
    label: "HTTP",
    eligible: (station: Station) => station.web_capable,
    missing: "No declared web service",
    missingShort: "No web service",
  },
  {
    op: "browser",
    mark: "▣",
    description: "Observe browser execution",
    label: "Browser",
    eligible: (station: Station) => station.web_capable,
    missing: "No declared web service",
    missingShort: "No web service",
  },
  {
    op: "poc",
    mark: ">_",
    description: "Run confined proof of concept jobs",
    label: "PoC",
    eligible: (station: Station) =>
      !station.foothold && station.service_count > 0,
    missing: "No published service",
    missingShort: "No published service",
  },
];

function toolStatus(
  tool: (typeof TOOLS)[number],
  station: Station,
  arena: ArenaData,
) {
  // `text` is the full explanation (tooltip and accessible name); `short`
  // is what fits on the tool button.
  if (arena.state === "destroyed")
    return {
      ok: false,
      text: "Archived record: tools are read-only",
      short: "Archived record",
    };
  if (station.foothold)
    return {
      ok: false,
      text: "Attacker station, not a target",
      short: "Attacker station",
    };
  if (!tool.eligible(station))
    return { ok: false, text: tool.missing, short: tool.missingShort };
  const capability = arena.capabilities?.[tool.op];
  if (capability && capability.state !== "ready")
    return {
      ok: false,
      text: `Unavailable here: ${reasonText(capability.reason)}`,
      short: "Unavailable here",
    };
  return {
    ok: true,
    text: capability ? "Ready for this station" : "Eligible target",
    short: `Use ${station.name}`,
  };
}

export function ForgeOverview({
  arena,
  onAction,
}: {
  arena: ArenaData;
  onAction: (action: Action) => void;
}) {
  const [selected, setSelected] = useState(
    arena.nodes.find((node) => !node.foothold)?.name ||
      arena.nodes[0]?.name ||
      "",
  );
  const node =
    arena.nodes.find((item) => item.name === selected) || arena.nodes[0];
  const base = `/console/arena/${encodeURIComponent(arena.id)}`;
  const evidence = useWorkspaceData<{ signals: Signal[] }>(
    `/api/console/arenas/${encodeURIComponent(arena.id)}/evidence`,
  );
  const signals = [...(evidence.value?.signals || [])].sort((first, second) =>
    (second.ts || "").localeCompare(first.ts || ""),
  );
  const resetAllowed =
    arena.reset.status === "eligible" &&
    ["active", "destroyed"].includes(arena.state);
  const resetReason =
    arena.reset.status === "eligible"
      ? `Unavailable while the arena is ${arena.state}`
      : `Unavailable: ${
          arena.reset.reason
            ? arena.reset.reason.replaceAll("_", " ")
            : "the current recipe cannot be reset"
        }`;
  const archived = arena.state === "destroyed";
  const networks =
    arena.topology?.segments.filter((segment) =>
      segment.nodes.includes(node?.name || ""),
    ) || [];
  return (
    <section className="forge-workbench" aria-label="Forge Arena preview">
      <div className="forge-surface">
        <div className="forge-canvas">
          <header className="forge-canvas-head">
            <img src="/static/anvil_logo.png" alt="" />
            <h2>Environment</h2>
            <span>
              {arena.nodes.length}{" "}
              {arena.nodes.length === 1 ? "station" : "stations"} ·{" "}
              {arena.topology?.segments.length ?? 0}{" "}
              {arena.topology?.segments.length === 1 ? "network" : "networks"}
            </span>
          </header>
          <SegmentMap
            compact
            nodes={arena.nodes.map((item) => ({
              name: item.name,
              kind: item.foothold ? "foothold" : "target",
              detail: stationDetail(item),
              state: item.state,
            }))}
            segments={arena.topology?.segments || []}
            unsegmented={arena.topology?.unsegmented || []}
            unavailable={!arena.topology}
            selected={node?.name}
            onSelect={setSelected}
          />
          <div className="forge-station-switcher" aria-label="Select a station">
            {arena.nodes.map((item) => (
              <button
                key={item.name}
                type="button"
                onClick={() => setSelected(item.name)}
                aria-pressed={item.name === node?.name}
              >
                <span aria-hidden="true">{item.foothold ? "↗" : "◇"}</span>
                {item.name}
                <small>{item.foothold ? "ATTACKER" : "TARGET"}</small>
              </button>
            ))}
          </div>
          <nav className="forge-toolbelt" aria-label="Research workbenches">
            {TOOLS.map((tool) => {
              const status = node
                ? toolStatus(tool, node, arena)
                : { ok: false, text: "", short: "" };
              return (
                <a
                  key={tool.op}
                  className={status.ok ? "ready" : ""}
                  href={
                    status.ok && node
                      ? `${base}?tab=${tool.op}&target=${encodeURIComponent(node.name)}`
                      : `${base}?tab=${tool.op}`
                  }
                  aria-label={
                    status.ok && node
                      ? `Use ${node.name} in ${tool.label}`
                      : `Open ${tool.label}${status.text ? `: ${status.text}` : ""}`
                  }
                  title={
                    status.text
                      ? `${tool.label}: ${status.text}`
                      : tool.description
                  }
                >
                  <span className="forge-tool-mark" aria-hidden="true">
                    {tool.mark}
                  </span>
                  <span className="forge-tool-text">
                    <strong>{tool.label}</strong>
                    {status.short && <small>{status.short}</small>}
                  </span>
                  {status.ok && <b aria-hidden="true">↗</b>}
                </a>
              );
            })}
          </nav>
        </div>
        <aside className="forge-inspector" aria-label="Station inspector">
          <div className="forge-inspector-label">SELECTED STATION</div>
          {node ? (
            <div key={node.name} className="forge-inspector-content">
              <div className="forge-selected-heading">
                <h2>{node.name}</h2>
                <Status value={node.state} />
              </div>
              <p>
                {node.foothold
                  ? "Attacker foothold: your entry point"
                  : `${roleLabel(node)} station`}
              </p>
              <dl>
                <div>
                  <dt>Networks</dt>
                  <dd>
                    {(node.segments?.length
                      ? node.segments
                      : networks.map((network) => network.name)
                    ).join(", ") || "Not declared"}
                  </dd>
                </div>
                <div>
                  <dt>Declared ports</dt>
                  <dd>{portList(node.declared_ports) || "None"}</dd>
                </div>
                <div>
                  <dt>Private IP</dt>
                  <dd className="mono">{node.private_ip || "Not reported"}</dd>
                </div>
                <div>
                  <dt>Readiness</dt>
                  <dd>
                    {archived
                      ? "Archived"
                      : node.ready === true
                        ? "Ready"
                        : node.ready === false
                          ? "Not ready"
                          : "Not reported"}
                  </dd>
                </div>
                {node.url && (
                  <div>
                    <dt>Published at</dt>
                    <dd className="mono">{node.url}</dd>
                  </div>
                )}
              </dl>
              <a
                className="forge-inspect-link"
                href={`${base}?tab=infrastructure`}
              >
                Inspect infrastructure <span>↗</span>
              </a>
              <details className="forge-station-details">
                <summary>Station details</summary>
                <dl>
                  <div>
                    <dt>Image</dt>
                    <dd className="mono">
                      {node.image || "Not reported"}
                      {node.image
                        ? node.image_pinned
                          ? " (pinned)"
                          : " (not pinned)"
                        : ""}
                    </dd>
                  </div>
                  <div>
                    <dt>Provider</dt>
                    <dd>{arena.provider}</dd>
                  </div>
                </dl>
                <p>Tools confirm their own target and access scope.</p>
              </details>
              {archived && (
                <p className="forge-inspector-note">
                  Archived station · infrastructure removed.
                </p>
              )}
            </div>
          ) : (
            <p>No stations reported.</p>
          )}
        </aside>
      </div>
      <div className="forge-footer-row">
        <nav className="forge-proof" aria-label="Research record">
          <strong>Research record</strong>
          <a href={`${base}?tab=findings`}>
            Findings <span>{arena.findings.length}</span>
          </a>
          <a href={`${base}?tab=poc`}>
            PoC jobs <span>{arena.poc_jobs.length}</span>
          </a>
          <a href={`${base}?tab=evidence`}>Evidence ↗</a>
          {arena.findings.length > 0 && (
            <ul className="forge-recent-findings">
              {arena.findings.slice(0, 3).map((finding, index) => (
                <li key={finding.id || index}>
                  <a href={`${base}?tab=findings`}>
                    {finding.title || "Untitled finding"}
                  </a>
                  <Status value={finding.verdict} />
                </li>
              ))}
            </ul>
          )}
        </nav>
        <div className="forge-lifecycle" aria-label="Lifecycle actions">
          {arena.state === "active" && (
            <button
              type="button"
              onClick={() =>
                onAction(arena.budget.gate === "stopped" ? "resume" : "stop")
              }
            >
              {arena.budget.gate === "stopped"
                ? "Resume research"
                : "Stop research"}
            </button>
          )}
          {arena.state !== "destroying" && (
            <details className="forge-lifecycle-menu">
              <summary>Arena actions ⌄</summary>
              <div>
                {resetAllowed ? (
                  <button
                    type="button"
                    onClick={(event) => {
                      event.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      onAction("reset");
                    }}
                  >
                    Reset arena
                  </button>
                ) : (
                  <div className="forge-menu-unavailable">
                    <span>Reset arena</span>
                    <small>{resetReason}</small>
                  </div>
                )}
                {!["destroyed", "destroying"].includes(arena.state) && (
                  <button
                    type="button"
                    className="forge-danger"
                    onClick={(event) => {
                      event.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      onAction("destroy");
                    }}
                  >
                    Destroy arena
                  </button>
                )}
              </div>
            </details>
          )}
          {archived && <span>Retained record</span>}
        </div>
      </div>
      <details className="forge-trace forge-monitor">
        <summary>
          <span>
            Monitor signals{" "}
            <small>
              {evidence.error
                ? "Signals unavailable"
                : signals.length
                  ? `${signals.length} ${signals.length === 1 ? "signal" : "signals"} · latest: ${signals[0].summary || signals[0].kind || "signal"}`
                  : evidence.loading
                    ? "Loading"
                    : "No monitor signals recorded"}
            </small>
          </span>
          <span className="forge-trace-chevron" aria-hidden="true">
            ⌄
          </span>
        </summary>
        <div>
          {signals.length ? (
            signals.slice(0, 8).map((signal, index) => (
              <div
                className="forge-event forge-signal"
                key={`${signal.ts}-${index}`}
              >
                <time>
                  {signal.ts ? formatObserved(signal.ts) : "Unknown time"}
                </time>
                <strong>
                  <span
                    className={`forge-severity severity-${(signal.severity || "unknown").toLowerCase()}`}
                  >
                    {signal.severity || "unrated"}
                  </span>{" "}
                  {signal.summary || signal.kind || "Signal"}
                </strong>
                <span>{signal.node || "arena"}</span>
              </div>
            ))
          ) : (
            <p>
              {evidence.error
                ? "Monitor signals could not be loaded."
                : "The service has not recorded monitor signals for this arena."}
            </p>
          )}
        </div>
      </details>
      <details className="forge-trace">
        <summary>
          <span>
            Event trace <small>{arena.events.length} observed events</small>
          </span>
          <span className="forge-trace-chevron" aria-hidden="true">
            ⌄
          </span>
        </summary>
        <div>
          {arena.events.length ? (
            arena.events.slice(0, 8).map((event, index) => (
              <div className="forge-event" key={`${event.ts}-${index}`}>
                <time>
                  {event.ts ? formatObserved(event.ts) : "Unknown time"}
                </time>
                <strong>{event.type.replaceAll("_", " ")}</strong>
                <span>{event.actor}</span>
              </div>
            ))
          ) : (
            <p>No events recorded.</p>
          )}
        </div>
      </details>
    </section>
  );
}
