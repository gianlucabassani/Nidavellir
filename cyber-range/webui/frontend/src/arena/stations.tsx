// UX-17: the stations as built. One tile per station (role, image and whether
// it is pinned, address, declared ports, readiness, what it is for) with the
// tools that can reach it, wired down to the networks it sits on.
import type { ArenaData } from "../types";
import { Status } from "../ui";
import { Icon, type IconName } from "../shell/icons";

export type Station = ArenaData["nodes"][number];

const REASONS: Record<string, string> = {
  provider_not_implemented: "this provider does not support it",
  arena_not_active: "the arena is not active",
  gate_stopped: "research is stopped",
};

export function reasonText(code: string) {
  return REASONS[code] || code.replaceAll("_", " ") || "not reported";
}

export function portList(ports?: number[]) {
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

export function roleLabel(station: Station) {
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

const TOOLS: {
  op: string;
  label: string;
  icon: IconName;
  eligible: (station: Station) => boolean;
  missing: string;
}[] = [
  {
    op: "http",
    label: "HTTP",
    icon: "swap",
    eligible: (s) => s.web_capable,
    missing: "No declared web service",
  },
  {
    op: "browser",
    label: "Browser",
    icon: "globe",
    eligible: (s) => s.web_capable,
    missing: "No declared web service",
  },
  {
    op: "poc",
    label: "PoC",
    icon: "bolt",
    eligible: (s) => !s.foothold && s.service_count > 0,
    missing: "No published service",
  },
];

export function toolStatus(
  tool: (typeof TOOLS)[number],
  station: Station,
  arena: ArenaData,
) {
  if (arena.state === "destroyed")
    return { ok: false, text: "Archived record: tools are read-only" };
  if (station.foothold)
    return { ok: false, text: "Attacker station, not a target" };
  if (!tool.eligible(station)) return { ok: false, text: tool.missing };
  const capability = arena.capabilities?.[tool.op];
  if (capability && capability.state !== "ready")
    return {
      ok: false,
      text: `Unavailable here: ${reasonText(capability.reason)}`,
    };
  return {
    ok: true,
    text: capability ? "Ready for this station" : "Eligible target",
  };
}

function purpose(station: Station) {
  if (station.foothold) return "Foothold · agents start here";
  if (!station.role || station.role === "victim")
    return "In scope · agents may attack it";
  return `${roleLabel(station)} service`;
}

export function Stations({ arena }: { arena: ArenaData }) {
  const base = `/console/arena/${encodeURIComponent(arena.id)}`;
  const archived = arena.state === "destroyed";
  if (!arena.nodes.length)
    return (
      <p className="stn-empty">
        {archived
          ? "This arena was destroyed. Its findings, evidence and timeline remain."
          : "No stations reported yet."}
      </p>
    );
  const segments = arena.topology?.segments || [];
  return (
    <>
      <ul className="stn-grid">
        {arena.nodes.map((station) => {
          const kind = station.foothold
            ? "atk"
            : !station.role || station.role === "victim"
              ? "tgt"
              : "aux";
          const ready = archived
            ? "archived"
            : station.ready === true
              ? "ready"
              : station.ready === false
                ? "not ready"
                : station.state;
          return (
            <li key={station.name} className={`stn stn-${kind}`}>
              <div className="stn-head">
                <span className="stn-ico" aria-hidden="true">
                  <Icon
                    name={
                      kind === "atk"
                        ? "term"
                        : kind === "tgt"
                          ? "target"
                          : "server"
                    }
                    size={16}
                  />
                </span>
                <span className="stn-name">
                  <b>{station.name}</b>
                  <small>{roleLabel(station)}</small>
                </span>
                <Status value={ready} />
              </div>
              <dl className="stn-facts">
                <div>
                  <dt>Image</dt>
                  <dd title={station.image || ""}>
                    {station.image || "Not reported"}
                    {station.image && !station.image_pinned && (
                      <em> · not pinned</em>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Address</dt>
                  <dd>{station.private_ip || "Not reported"}</dd>
                </div>
                <div>
                  <dt>Ports</dt>
                  <dd>{portList(station.declared_ports) || "None declared"}</dd>
                </div>
                {station.url && (
                  <div>
                    <dt>Published</dt>
                    <dd title={station.url}>{station.url}</dd>
                  </div>
                )}
              </dl>
              <p className="stn-purpose">{purpose(station)}</p>
              {!station.foothold && (
                <div
                  className="stn-tools"
                  aria-label={`Tools for ${station.name}`}
                >
                  {TOOLS.map((tool) => {
                    const status = toolStatus(tool, station, arena);
                    return status.ok ? (
                      <a
                        key={tool.op}
                        href={`${base}?tab=${tool.op}&target=${encodeURIComponent(station.name)}`}
                        title={status.text}
                      >
                        <Icon name={tool.icon} size={13} />
                        {tool.label}
                      </a>
                    ) : (
                      <span
                        key={tool.op}
                        className="off"
                        title={status.text}
                        aria-disabled="true"
                      >
                        <Icon name={tool.icon} size={13} />
                        {tool.label}
                        <span className="visually-hidden">: {status.text}</span>
                      </span>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="stn-nets">
        {segments.length ? (
          segments.map((segment) => (
            <div key={segment.name} className="stn-net">
              <b>{segment.name}</b>
              <span>{segment.nodes.join(" · ")}</span>
            </div>
          ))
        ) : (
          <div className="stn-net">
            <b>{arena.topology ? "Default network" : "Network not declared"}</b>
            <span>
              {arena.topology
                ? arena.topology.unsegmented.join(" · ")
                : "This record has no topology recipe; station links cannot be verified."}
            </span>
          </div>
        )}
      </div>
    </>
  );
}
