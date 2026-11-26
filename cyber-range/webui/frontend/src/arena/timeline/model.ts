// UX-28: the timeline model. The orchestrator folds the run
// (GET /arenas/{id}/run-tree); this file places it on the time budget's
// circle: where a moment of the run falls (0 at the arena's start, 1 at the
// deadline), and which nearby events share one mark.

export type Timeline = {
  schema: string;
  started_at: string | null;
  duration: number;
  live: boolean;
  truncated: boolean;
  clock: {
    start: number;
    deadline: number | null;
    source: "budget" | "lease" | null;
  };
  budget: { cap: number | null; spent: number | null } | null;
  cycles: { i: number; a: number; b: number; steps: number; errors: number }[];
  findings: TimelineFinding[];
  verdicts: Verdict[];
  failures: Failure[];
  families: Record<string, number>;
  activity: { bucket: number; steps: number[]; errors: number[] };
  totals: { steps: number; spans: number; errors: number; refused: number };
};
export type TimelineFinding = {
  id: string | null;
  title: string;
  severity: string | null;
  t: number;
  relation: string;
  related: string | null;
};
export type Verdict = {
  t: number;
  id: string;
  outcome: string | null;
  claim: string | null;
  findings: string[];
};
export type Failure = {
  t: number;
  tool: string;
  status: string;
  target: string;
};

export type Ev =
  | { kind: "finding"; t: number; f: number; item: TimelineFinding }
  | { kind: "fail"; t: number; f: number; item: Failure }
  | { kind: "verdict"; t: number; f: number; item: Verdict };
export type Cluster = {
  key: string;
  side: "out" | "in";
  f0: number;
  f1: number;
  f: number;
  lane: number;
  list: Ev[];
};

// The drawing's geometry: a 760-unit square, the budget circle in the middle.
export const C = 380;
export const R = 248;
export const TAU = Math.PI * 2;
export const ang = (f: number) => -Math.PI / 2 + f * TAU;
export const pt = (f: number, r: number): [number, number] => [
  C + r * Math.cos(ang(f)),
  C + r * Math.sin(ang(f)),
];
export const smooth = (a: number, b: number, x: number) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

export type Frame = {
  frac: (t: number) => number; // 0..1 of the budget at run second t
  head: number; // where the budget stands now
  total: number; // the budget in seconds
  open: boolean; // no deadline: the circle is the run so far
};

export function frameOf(tree: Timeline, preview: boolean): Frame {
  const start = tree.clock.start;
  const now = Math.max(start + 1, tree.duration);
  const open = tree.clock.deadline == null;
  const end = preview || open ? now : Math.max(start + 1, tree.clock.deadline!);
  const total = end - start;
  const frac = (t: number) => Math.max(0, (t - start) / total);
  return { frac, head: Math.min(1, frac(now)), total, open };
}

export const SEVERITIES = ["critical", "high", "medium", "low", "info"];
export const sevOf = (s: string | null) =>
  s && SEVERITIES.includes(s.toLowerCase()) ? s.toLowerCase() : "info";

/** Events closer than gapPx along the circle share one mark; a mark close to
 *  the previous one moves to the second lane so the two never touch. */
export function cluster(events: Ev[], gapPx: number, side: "out" | "in") {
  const sorted = [...events].sort((a, b) => a.f - b.f);
  const out: Cluster[] = [];
  for (const e of sorted) {
    const c = out.at(-1);
    if (c && (e.f - c.f0) * TAU * R < gapPx) {
      c.list.push(e);
      c.f1 = e.f;
    } else
      out.push({
        key: `${side}:${e.kind}:${e.t}`,
        side,
        f0: e.f,
        f1: e.f,
        f: e.f,
        lane: 0,
        list: [e],
      });
  }
  out.forEach((c, i) => {
    c.f = (c.f0 + c.f1) / 2;
    const prev = out[i - 1];
    c.lane =
      prev && !prev.lane && (c.f - prev.f) * TAU * R < gapPx * 1.4 ? 1 : 0;
  });
  return out;
}

export function clustersOf(tree: Timeline, frame: Frame) {
  const outside: Ev[] = [
    ...tree.findings.map((item) => ({
      kind: "finding" as const,
      t: item.t,
      f: frame.frac(item.t),
      item,
    })),
    ...tree.failures.map((item) => ({
      kind: "fail" as const,
      t: item.t,
      f: frame.frac(item.t),
      item,
    })),
  ];
  const inside: Ev[] = tree.verdicts.map((item) => ({
    kind: "verdict" as const,
    t: item.t,
    f: frame.frac(item.t),
    item,
  }));
  return [...cluster(inside, 18, "in"), ...cluster(outside, 24, "out")];
}

export function verdictClass(outcome: string | null) {
  if (outcome === "supported" || outcome === "confirmed") return "supported";
  if (outcome === "refuted" || outcome === "unsupported") return "refuted";
  return "other";
}

export function duration(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 90) return `${s} s`;
  const minutes = Math.round(s / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}
