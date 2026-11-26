// UX-27: the run tree's data (aggregated by the orchestrator) and its layout.
// The tree grows upward: the roots are the start, the crown is now. Time is
// folded into 30-second buckets; idle stretches collapse, quiet ones shrink
// and buckets where something happens get room.

export type TreeError = {
  t: number;
  id: number;
  tool: string;
  status: string;
  error: string | null;
  target: string;
};
export type Episode = {
  a: number;
  b: number;
  steps: number;
  last: boolean;
  errors: TreeError[];
};
export type RouteState = "finding" | "refuted" | "done" | "open";
export type TreeRoute = {
  key: string;
  name: string;
  kind: "hypothesis" | "path";
  actor: string;
  claim: string | null;
  state: RouteState;
  outcome: string | null;
  a: number;
  b: number;
  steps: number;
  tools: Record<string, number>;
  errors: number;
  findings: string[];
  episodes: Episode[];
  background?: boolean;
};
export type TreeCycle = {
  i: number;
  a: number;
  b: number;
  steps: number;
  errors: number;
};
export type TreeFinding = {
  id: string;
  title: string;
  severity: string | null;
  t: number;
  route: string | null;
};
export type RunTree = {
  schema: string;
  started_at: string | null;
  duration: number;
  live: boolean;
  truncated: boolean;
  actors: string[];
  cycles: TreeCycle[];
  routes: TreeRoute[];
  findings: TreeFinding[];
  trunk: { steps: number; errors: TreeError[] };
  totals: { steps: number; spans: number; errors: number; refused: number };
  search?: { query: string; hits: Record<string, number>; total: number };
};
export type Branch = {
  id: string;
  route: TreeRoute;
  ep: Episode;
  index: number;
  side: -1 | 1;
  lane: number;
};

export const STATE_TEXT: Record<RouteState, string> = {
  finding: "Finding",
  refuted: "Refuted",
  done: "Tested",
  open: "Open",
};

/** Branches (one per episode); a route keeps its side, lanes are reused. */
export function branchesOf(tree: RunTree) {
  const branches: Branch[] = [];
  tree.routes.forEach((route, order) => {
    const side: -1 | 1 = order % 2 === 0 ? -1 : 1;
    route.episodes.forEach((ep, index) =>
      branches.push({
        id: `${route.key}#${index}`,
        route,
        ep,
        index,
        side,
        lane: 0,
      }),
    );
  });
  const lanes = { left: 1, right: 1 };
  for (const side of [-1, 1] as const) {
    const ends: number[] = [];
    branches
      .filter((branch) => branch.side === side)
      .sort((x, y) => x.ep.a - y.ep.a)
      .forEach((branch) => {
        let lane = ends.findIndex((end) => end < branch.ep.a - 40);
        if (lane < 0) {
          lane = ends.length;
          ends.push(0);
        }
        ends[lane] = branch.ep.b;
        branch.lane = lane;
      });
    if (side < 0) lanes.left = Math.max(1, ends.length);
    else lanes.right = Math.max(1, ends.length);
  }
  return { branches, lanes };
}

const BUCKET = 30;
const TOP = 76;
const BOT = 112;

export type Layout = ReturnType<typeof layout>;

export function layout(
  tree: RunTree,
  branches: Branch[],
  lanes: { left: number; right: number },
  width: number,
  density: number,
) {
  const W = Math.max(320, width);
  const cx = Math.round(W / 2);
  const narrow = W < 680;
  const maxLanes = Math.max(lanes.left, lanes.right);
  const labelRoom = narrow ? 0 : Math.min(320, cx * 0.45);
  const reach = Math.max(80, Math.min(cx - labelRoom - 40, 44 + maxLanes * 46));
  const gap = (reach - 44) / maxLanes;
  const dur = Math.max(1, tree.duration);
  const n = Math.ceil(dur / BUCKET) + 1;
  const act = new Float64Array(n);
  const ev = new Float64Array(n);
  const b = (t: number) => Math.min(n - 1, Math.max(0, Math.floor(t / BUCKET)));
  for (const c of tree.cycles) {
    for (let i = b(c.a); i <= b(c.b); i++) act[i] = 1;
    ev[b(c.a)] += 2.4;
  }
  for (const branch of branches) {
    for (let i = b(branch.ep.a); i <= b(branch.ep.b); i++) act[i] = 1;
    ev[b(branch.ep.a)] += 1;
    ev[b(branch.ep.b)] += 0.6;
    for (const e of branch.ep.errors) ev[b(e.t)] += 0.3;
  }
  for (const e of tree.trunk.errors) ev[b(e.t)] += 0.3;
  for (const f of tree.findings) ev[b(f.t)] += 1;
  const h = new Float64Array(n);
  const gaps: { a: number; b: number }[] = [];
  const quiet = (i: number) => !act[i] && ev[i] < 1;
  for (let i = 0; i < n;) {
    if (quiet(i)) {
      let j = i;
      while (j < n && quiet(j)) j++;
      if ((j - i) * BUCKET >= 180) {
        gaps.push({ a: i * BUCKET, b: Math.min(dur, j * BUCKET) });
        for (let q = i; q < j; q++) h[q] = 44 / (j - i);
        i = j;
        continue;
      }
    }
    const e = ev[i];
    h[i] =
      e >= 0.5
        ? Math.max(BUCKET * density, e * 15)
        : BUCKET * density * (act[i] ? 0.55 : 0.3);
    i++;
  }
  const cum = new Float64Array(n + 1);
  for (let q = 0; q < n; q++) cum[q + 1] = cum[q] + h[q];
  const H = cum[n] + TOP + BOT;
  const base = H - BOT;
  const Y = (t: number) => {
    t = Math.max(0, Math.min(dur, t));
    const q = b(t);
    return base - (cum[q] + h[q] * ((t - q * BUCKET) / BUCKET));
  };
  const T = (y: number) => {
    const w = base - y;
    let lo = 0;
    let hi = n;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (cum[mid + 1] < w) lo = mid + 1;
      else hi = mid;
    }
    const q = Math.min(n - 1, lo);
    return Math.min(
      dur,
      q * BUCKET +
        BUCKET * Math.max(0, Math.min(1, (w - cum[q]) / Math.max(1e-6, h[q]))),
    );
  };
  const bx = (branch: Branch) =>
    cx + branch.side * (44 + branch.lane * gap + gap / 2);
  const labelX = {
    left: cx - (44 + lanes.left * gap) - 18,
    right: cx + (44 + lanes.right * gap) + 18,
  };
  return { W, H, cx, base, narrow, gap, dur, Y, T, bx, labelX, gaps };
}

/** The density that makes the tree about `target` pixels tall. */
export function fitDensity(
  tree: RunTree,
  branches: Branch[],
  lanes: { left: number; right: number },
  width: number,
  target: number,
) {
  let lo = 0.05;
  let hi = 2.5;
  for (let i = 0; i < 14; i++) {
    const mid = (lo + hi) / 2;
    if (layout(tree, branches, lanes, width, mid).H > target) hi = mid;
    else lo = mid;
  }
  return lo;
}

/** Errors within `px` pixels draw as one marker with a count. */
export function clusters(
  list: TreeError[],
  y: (e: TreeError) => number,
  px = 11,
) {
  const out: { y: number; list: TreeError[] }[] = [];
  for (const e of list) {
    const yy = y(e);
    const hit = out.find((c) => Math.abs(c.y - yy) < px);
    if (hit) hit.list.push(e);
    else out.push({ y: yy, list: [e] });
  }
  return out;
}

/** Labels slide to avoid each other; one pushed further than `maxShift` is dropped. */
export function placeLabels<T>(
  items: { item: T; want: number }[],
  gap = 34,
  maxShift = 90,
) {
  const placed: { item: T; want: number; y: number }[] = [];
  let prev = -Infinity;
  for (const label of [...items].sort((x, y) => x.want - y.want)) {
    const y = Math.max(label.want, prev + gap);
    if (y - label.want > maxShift) continue;
    prev = y;
    placed.push({ ...label, y });
  }
  return placed;
}

export function duration(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return h
    ? `${h} h ${m} min`
    : s >= 90
      ? `${Math.round(s / 60)} min`
      : `${s} s`;
}
