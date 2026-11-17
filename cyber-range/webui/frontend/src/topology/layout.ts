// Layered layout for declared arena topology. Columns alternate stations and
// networks by hop from the attacker foothold, so pivots and hosts on several
// networks read left to right. Shapes keep a fixed pixel size; only the gaps
// between columns follow the available width.

export const NODE_WIDTH = 184;
export const HUB_WIDTH = 104;
export const NODE_GAP = 94;
const SIDE = 12;
const MIN_GAP = 40;
const MAX_GAP = 200;

export type LayoutNode = { name: string; kind: "foothold" | "target" | "host" };
export type LayoutSegment = { name: string; nodes: string[] };
export type Placed = { x: number; y: number; column: number };
export type LayoutColumn = {
  kind: "stations" | "networks";
  x: number;
  width: number;
  label: string;
};
export type TopologyLayout = {
  width: number;
  height: number;
  gap: number;
  columns: LayoutColumn[];
  stations: Map<string, Placed>;
  hubs: Map<string, Placed>;
};

/** Smallest width that still fits attacker, one network and one target. */
export const MIN_LAYOUT_WIDTH =
  2 * NODE_WIDTH + HUB_WIDTH + 2 * MIN_GAP + 2 * SIDE;

export function layoutTopology(
  nodes: LayoutNode[],
  segments: LayoutSegment[],
  available: number,
  compact = false,
): TopologyLayout | null {
  if (available < MIN_LAYOUT_WIDTH) return null;
  const known = new Set(nodes.map((node) => node.name));
  const memberships = new Map<string, string[]>();
  for (const segment of segments)
    for (const name of segment.nodes)
      if (known.has(name))
        memberships.set(name, [...(memberships.get(name) || []), segment.name]);
  const membersOf = new Map(
    segments.map((segment) => [
      segment.name,
      segment.nodes.filter((name) => known.has(name)),
    ]),
  );

  const nodeColumn = new Map<string, number>();
  const segmentColumn = new Map<string, number>();
  const walk = (start: string[], column: number) => {
    const queue = start.filter((name) => !nodeColumn.has(name));
    queue.forEach((name) => nodeColumn.set(name, column));
    while (queue.length) {
      const name = queue.shift() as string;
      const here = nodeColumn.get(name) as number;
      for (const segment of memberships.get(name) || []) {
        if (segmentColumn.has(segment)) continue;
        segmentColumn.set(segment, here + 1);
        for (const member of membersOf.get(segment) || []) {
          if (nodeColumn.has(member)) continue;
          nodeColumn.set(member, here + 2);
          queue.push(member);
        }
      }
    }
  };
  const footholds = nodes.filter((node) => node.kind === "foothold");
  walk(
    footholds.length
      ? footholds.map((node) => node.name)
      : (segments[0]?.nodes || [])
          .filter((name) => known.has(name))
          .slice(0, 1),
    0,
  );
  // Stations not reachable from the foothold still appear, on the target side.
  for (const node of nodes)
    if (!nodeColumn.has(node.name) && memberships.has(node.name))
      walk([node.name], 2);
  for (const segment of segments)
    if (!segmentColumn.has(segment.name)) segmentColumn.set(segment.name, 1);

  const lastColumn = Math.max(
    2,
    ...nodeColumn.values(),
    ...[...segmentColumn.values()].map((column) => column + 1),
  );
  const columnCount = lastColumn + 1;
  const stationColumns = new Map<number, string[]>();
  const hubColumns = new Map<number, string[]>();
  for (const node of nodes) {
    const column = nodeColumn.get(node.name);
    if (column === undefined) continue;
    stationColumns.set(column, [
      ...(stationColumns.get(column) || []),
      node.name,
    ]);
  }
  for (const segment of segments) {
    const column = segmentColumn.get(segment.name) as number;
    hubColumns.set(column, [...(hubColumns.get(column) || []), segment.name]);
  }

  const widths = Array.from({ length: columnCount }, (_, index) =>
    index % 2 === 0 ? NODE_WIDTH : HUB_WIDTH,
  );
  const fixed = widths.reduce((sum, value) => sum + value, 0) + 2 * SIDE;
  const gap = Math.max(
    MIN_GAP,
    Math.min(MAX_GAP, (available - fixed) / (columnCount - 1)),
  );
  const width = Math.round(fixed + gap * (columnCount - 1));
  const tallest = Math.max(
    1,
    ...[...stationColumns.values(), ...hubColumns.values()].map(
      (items) => items.length,
    ),
  );
  // Sized to its stations: room for column labels plus one station row per item.
  const height = 170 + (tallest - 1) * NODE_GAP + (compact ? 0 : 24);
  const spread = (index: number, count: number) =>
    height / 2 + (index - (count - 1) / 2) * NODE_GAP;

  const networkColumns = [...hubColumns.keys()].length;
  const columns: LayoutColumn[] = [];
  let x = SIDE;
  for (let index = 0; index < columnCount; index++) {
    const stations = index % 2 === 0;
    columns.push({
      kind: stations ? "stations" : "networks",
      x,
      width: widths[index],
      label: stations
        ? index === 0
          ? footholds.length
            ? "ATTACK / ENTRY"
            : "ENTRY"
          : hubColumns.has(index + 1)
            ? "PIVOT / HOST"
            : "TARGET / HOST"
        : networkColumns > 1
          ? "NETWORK"
          : "NETWORK SEGMENTS",
    });
    x += widths[index] + gap;
  }

  const stations = new Map<string, Placed>();
  stationColumns.forEach((names, column) =>
    names.forEach((name, index) =>
      stations.set(name, {
        x: columns[column].x,
        y: spread(index, names.length),
        column,
      }),
    ),
  );
  const hubs = new Map<string, Placed>();
  hubColumns.forEach((names, column) =>
    names.forEach((name, index) =>
      hubs.set(name, {
        x: columns[column].x,
        y: spread(index, names.length),
        column,
      }),
    ),
  );
  return { width, height, gap, columns, stations, hubs };
}
