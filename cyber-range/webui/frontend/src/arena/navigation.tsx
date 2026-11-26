import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { ArenaData } from "../types";
import { Status } from "../ui";
import { Icon, type IconName } from "../shell/icons";
import { RailLink } from "../shell/Shell";
import "./navigation.css";

type ArenaTab = {
  tab: string;
  label: string;
  icon: IconName;
  /** Capability operation reported by the provider for this tool. */
  op?: string;
};

// UX-16 (ADR-0019): inside an arena the sidebar becomes the arena's menu.
// UX-03 still holds: every tool is a visible link in a persistent, grouped
// list — one click and plain Tab order, no hover flyouts or hidden menus.
export const categories: {
  id: string;
  label: string;
  items: ArenaTab[];
}[] = [
  {
    id: "investigate",
    label: "Tools",
    items: [
      { tab: "http", label: "HTTP", icon: "swap", op: "http" },
      { tab: "terminal", label: "Shell & logs", icon: "term", op: "exec" },
      { tab: "browser", label: "Browser", icon: "globe", op: "browser" },
      { tab: "poc", label: "Confined PoC", icon: "bolt", op: "poc" },
      { tab: "transfer", label: "File transfer", icon: "upload", op: "files" },
      {
        tab: "forwards",
        label: "Service forwards",
        icon: "link",
        op: "forward",
      },
    ],
  },
  {
    id: "record",
    label: "Record",
    items: [
      { tab: "findings", label: "Findings", icon: "flag" },
      { tab: "evidence", label: "Evidence", icon: "file" },
      { tab: "score", label: "Score & trace", icon: "chart" },
    ],
  },
  {
    id: "prepare",
    label: "Configure",
    items: [
      { tab: "setup", label: "Target setup", icon: "wrench", op: "setup" },
      { tab: "access", label: "Agent access", icon: "key" },
      { tab: "infrastructure", label: "Infrastructure", icon: "server" },
    ],
  },
];

const REASONS: Record<string, string> = {
  provider_not_implemented: "not available on this provider",
};

/** Ready dot for a tool, from the provider's capability report. */
function readiness(arena: ArenaData, op?: string) {
  if (!op) return null;
  if (arena.state === "destroyed")
    return { ok: false, text: "Archived record: read-only" };
  const capability = arena.capabilities?.[op];
  if (!capability) return null;
  if (capability.state === "ready") return { ok: true, text: "Ready" };
  const reason =
    REASONS[capability.reason] ||
    capability.reason.replaceAll("_", " ") ||
    capability.state;
  return { ok: false, text: `Unavailable: ${reason}` };
}

export function ArenaRail({ arena, tab }: { arena: ArenaData; tab: string }) {
  // The shell renders the slot; it exists once the shell has mounted.
  const [slot, setSlot] = useState<HTMLElement | null>(() =>
    document.getElementById("rail-arena"),
  );
  useEffect(() => {
    if (!slot) setSlot(document.getElementById("rail-arena"));
  }, [slot]);
  if (!slot) return null;
  const href = (item: string) =>
    `/console/arena/${encodeURIComponent(arena.id)}?tab=${item}`;
  const gate = (arena.budget.gate || "").toLowerCase();
  const findings = arena.findings.length;
  return createPortal(
    <>
      <div className="rail-ctx">
        <a className="rail-back" href="/console/arenas">
          <Icon name="back" size={13} /> All arenas
        </a>
        <strong title={arena.name}>{arena.name}</strong>
        <div className="rail-ctx-row">
          <Status value={arena.state} />
          {gate && gate !== "open" && <Status value={`gate ${gate}`} />}
        </div>
        <div className="rail-ctx-meta">
          {arena.scenario} ·{" "}
          {arena.simulation_mode ? "simulated" : arena.provider}
        </div>
      </div>
      <nav aria-label="Arena">
        <div className="rail-group">
          <RailLink
            item={{ label: "Overview", href: href("forge"), icon: "home" }}
            current={tab === "forge"}
          />
          <RailLink
            item={{ label: "Live", href: href("live"), icon: "pulse" }}
            current={tab === "live"}
          />
          <RailLink
            item={{ label: "Timeline", href: href("timeline"), icon: "tree" }}
            current={tab === "timeline"}
          />
        </div>
        {categories.map((category) => (
          <div
            key={category.id}
            className="rail-group"
            role="group"
            aria-labelledby={`arena-rail-${category.id}`}
          >
            <div className="rail-cap" id={`arena-rail-${category.id}`}>
              {category.label}
            </div>
            {category.items.map((item) => {
              const ready = readiness(arena, item.op);
              return (
                <RailLink
                  key={item.tab}
                  item={{
                    label: item.label,
                    href: href(item.tab),
                    icon: item.icon,
                  }}
                  current={tab === item.tab}
                  end={
                    ready ? (
                      <span
                        className={`dot ${ready.ok ? "ok" : "idle"}`}
                        title={ready.text}
                        role="img"
                        aria-label={ready.text}
                      />
                    ) : item.tab === "findings" && findings ? (
                      <span aria-label={`${findings} findings`}>
                        {findings}
                      </span>
                    ) : undefined
                  }
                />
              );
            })}
          </div>
        ))}
      </nav>
    </>,
    slot,
  );
}
