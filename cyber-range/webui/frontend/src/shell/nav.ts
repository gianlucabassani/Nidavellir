// UX-16 (ADR-0019): the navigation model. The top bar picks a workspace; the
// left sidebar is the only menu inside it. Every console page belongs to one
// workspace and at most one sidebar item, decided here from the URL alone.
import type { Workspace } from "../types";
import type { IconName } from "./icons";

export type NavItem = {
  label: string;
  href: string;
  icon: IconName;
  /** True when this item is the current page. */
  match: (path: string, params: URLSearchParams) => boolean;
  /** Visible but not usable yet (ADR-0019): shown with its reason. */
  planned?: string;
};
export type NavGroup = { caption?: string; items: NavItem[] };

const exact = (target: string) => (path: string) => path === target;
const prefix = (target: string) => (path: string) =>
  path === target || path.startsWith(`${target}/`);
const overview =
  (space: Workspace) => (path: string, params: URLSearchParams) =>
    path === "/console" && (params.get("workspace") || "research") === space;
const activitySection =
  (section: string) => (path: string, params: URLSearchParams) =>
    path === "/console/activity" &&
    (params.get("section") || "findings") === section;

export const NAV: Record<Workspace, NavGroup[]> = {
  research: [
    {
      items: [
        {
          label: "Overview",
          href: "/console?workspace=research",
          icon: "home",
          match: overview("research"),
        },
        {
          label: "New research",
          href: "/console/research/new",
          icon: "plus",
          match: exact("/console/research/new"),
        },
        {
          label: "Arenas",
          href: "/console/arenas",
          icon: "box",
          match: exact("/console/arenas"),
        },
        {
          label: "Agents board",
          href: "/console/board",
          icon: "agent",
          match: exact("/console/board"),
        },
      ],
    },
    {
      caption: "Record",
      items: [
        {
          label: "Findings",
          href: "/console/activity?section=findings",
          icon: "flag",
          match: activitySection("findings"),
        },
        {
          label: "Evidence",
          href: "/console/activity?section=evidence",
          icon: "file",
          match: activitySection("evidence"),
        },
        {
          label: "Campaigns",
          href: "/console/research/campaigns",
          icon: "layers",
          match: prefix("/console/research/campaigns"),
        },
        {
          label: "Source review",
          href: "/console/research/review",
          icon: "book",
          match: prefix("/console/research/review"),
        },
      ],
    },
  ],
  benchmark: [
    {
      items: [
        {
          label: "Overview",
          href: "/console?workspace=benchmark",
          icon: "home",
          match: overview("benchmark"),
        },
        {
          label: "New comparison",
          href: "/console/evaluations/new",
          icon: "plus",
          match: exact("/console/evaluations/new"),
        },
        {
          label: "Evaluations",
          href: "/console/evaluations",
          icon: "scale",
          match: (path) =>
            path !== "/console/evaluations/new" &&
            (prefix("/console/evaluations")(path) ||
              path.startsWith("/console/suites/")),
        },
      ],
    },
    {
      caption: "Registry",
      items: [
        {
          label: "Builds & challenges",
          href: "/console/benchmark/registry",
          icon: "chart",
          match: exact("/console/benchmark/registry"),
        },
        {
          label: "Agents",
          href: "/console/library/agents",
          icon: "agent",
          match: exact("/console/library/agents"),
        },
      ],
    },
  ],
  range: [
    {
      items: [
        {
          label: "Overview",
          href: "/console?workspace=range",
          icon: "home",
          match: overview("range"),
        },
        {
          label: "New arena",
          href: "/console/arenas/new",
          icon: "plus",
          match: (path) =>
            path === "/console/arenas/new" || path === "/console/arenas/custom",
        },
      ],
    },
    {
      caption: "Catalogue",
      items: [
        {
          label: "Targets",
          href: "/console/library/targets",
          icon: "target",
          match: exact("/console/library/targets"),
        },
        {
          label: "Scenarios",
          href: "/console/scenarios",
          icon: "layers",
          match: prefix("/console/scenarios"),
        },
      ],
    },
    {
      caption: "Platform",
      items: [
        {
          label: "Operations",
          href: "/console/operations",
          icon: "server",
          match: exact("/console/operations"),
          planned: "Planned (UX-14): service health, queues and retention.",
        },
      ],
    },
  ],
};

export const WORKSPACES: { id: Workspace; label: string; title: string }[] = [
  {
    id: "research",
    label: "Research",
    title: "Investigate targets and retain proof",
  },
  {
    id: "benchmark",
    label: "Benchmark",
    title: "Compare pinned agent builds",
  },
  {
    id: "range",
    label: "Cyber Range",
    title: "Launch and observe isolated arenas",
  },
];

/** The workspace a console URL belongs to. Account pages keep Research. */
export function workspaceOf(path: string, params: URLSearchParams): Workspace {
  if (path === "/console") {
    const value = params.get("workspace");
    return value === "benchmark" || value === "range" ? value : "research";
  }
  for (const space of ["benchmark", "range"] as const)
    if (
      NAV[space].some((group) =>
        group.items.some((item) => item.match(path, params)),
      )
    )
      return space;
  return "research";
}

/** The arena id when the URL is an arena workspace, else null. */
export function arenaIdOf(path: string): string | null {
  return path.startsWith("/console/arena/")
    ? decodeURIComponent(path.slice("/console/arena/".length))
    : null;
}
