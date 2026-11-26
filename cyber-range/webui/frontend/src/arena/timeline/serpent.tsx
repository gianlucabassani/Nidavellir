// UX-28: the serpent. The circle is the time budget; the serpent is born at
// the top with a thin tail and grows clockwise as time is spent. When the
// budget runs out its head reaches the tail and bites it. What happened
// sprouts from the body: findings and failed calls outside, the agent's
// verdicts inside, its cycles as bands across the scales.
import { memo, useMemo, type KeyboardEvent, type MouseEvent } from "react";
import {
  C,
  R,
  TAU,
  ang,
  duration,
  pt,
  SEVERITIES,
  sevOf,
  smooth,
  verdictClass,
  type Cluster,
  type Frame,
  type Timeline,
} from "./model";

const f1 = (n: number) => n.toFixed(1);
const line = (points: [number, number][]) =>
  points.map(([x, y]) => `${f1(x)} ${f1(y)}`).join(" L");

function widthAt(p: number, maxW: number) {
  return (f: number) => {
    const s = p ? f / p : 0;
    return 3 + (maxW - 3) * smooth(0, 0.38, s) - 1.5 * smooth(0.9, 0.985, s);
  };
}

function bodyOf(p: number, maxW: number) {
  const w = widthAt(p, maxW);
  const n = Math.max(24, Math.round(p * 520));
  const outer: [number, number][] = [];
  const inner: [number, number][] = [];
  const belly: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const f = (p * i) / n;
    outer.push(pt(f, R + w(f) / 2));
    inner.unshift(pt(f, R - w(f) / 2));
    belly.push(pt(f, R - w(f) / 2 + 2.2));
  }
  // scales: chevrons pointing at the tail, a row every 9 units of body; a
  // dorsal diamond every third row
  const step = 9 / (TAU * R);
  let scales = "";
  const spine: { x: number; y: number; s: number; r: number }[] = [];
  for (let f = step, k = 0; f < p - 0.012; f += step, k++) {
    const width = w(f);
    if (width < 6) continue;
    const a = pt(f, R + width / 2 - 1);
    const b = pt(f + step * 0.7, R);
    const c = pt(f, R - width / 2 + 1);
    scales += `M${f1(a[0])} ${f1(a[1])} L${f1(b[0])} ${f1(b[1])} L${f1(c[0])} ${f1(c[1])} `;
    if (k % 3 === 0) {
      const [x, y] = pt(f + step * 0.35, R + width * 0.18);
      spine.push({
        x,
        y,
        s: Math.max(1.6, width * 0.12),
        r: (ang(f) * 180) / Math.PI + 45,
      });
    }
  }
  return {
    hide: `M${line(outer)} L${line(inner)} Z`,
    belly: `M${line(belly)}`,
    scales,
    spine,
    w,
  };
}

function Head({
  p,
  w,
  bitten,
  live,
}: {
  p: number;
  w: number;
  bitten: boolean;
  live: boolean;
}) {
  const [x, y] = pt(p, R);
  const turn = (ang(p) * 180) / Math.PI + 90;
  const k = Math.max(0.7, w / 17);
  const upper = `M-6 -8 L10 -15 L28 -11 L44 -6 L52 -2 L50 0 L30 ${bitten ? -3 : 0} L12 ${bitten ? -1 : 1} L-6 2 Z`;
  const lower = bitten
    ? "M-6 2 L12 3 L28 7 L46 13 L44 17 L26 16 L8 14 L-6 8 Z"
    : "M-6 2 L12 1 L30 0 L50 0 L46 5 L26 10 L8 14 L-6 8 Z";
  return (
    <g
      className={`tl-head${bitten ? " bitten" : ""}${live ? " live" : ""}`}
      transform={`translate(${f1(x)} ${f1(y)}) rotate(${f1(turn)}) scale(${k.toFixed(2)})`}
    >
      <path
        className="tl-crest"
        d="M6 -12 L-8 -21 L-1 -20 L12 -13 Z M0 10 L-9 17 L-3 16 L8 11 Z"
      />
      {!bitten && (
        <path className="tl-tongue" d="M50 0 L60 0 M60 0 l6 -4 M60 0 l6 4" />
      )}
      <path className="tl-skull" d={lower} />
      <path className="tl-skull" d={upper} />
      {bitten && (
        <path
          className="tl-teeth"
          d="M32 -3 l3 4 l2 -5 M40 -2 l2 4 l2 -5 M30 8 l2 -4 l3 5 M38 11 l2 -4 l2 5"
        />
      )}
      <path className="tl-brow" d="M14 -12 L32 -8" />
      <path
        className="tl-eye"
        d="M19 -8.5 Q25 -12.5 31 -7.5 Q25 -5.5 19 -8.5 Z"
      />
      <path className="tl-pupil" d="M25 -10.6 L25 -6.4" />
      <circle className="tl-nostril" cx="46" cy="-3.6" r="1.2" />
    </g>
  );
}

// A small donut: the share of supported / refuted / other verdicts.
function Donut({
  x,
  y,
  r,
  parts,
}: {
  x: number;
  y: number;
  r: number;
  parts: [string, number][];
}) {
  const total = parts.reduce((sum, [, n]) => sum + n, 0);
  let at = 0;
  return (
    <g>
      <circle className="tl-donut-bg" cx={x} cy={y} r={r} />
      {parts
        .filter(([, n]) => n > 0)
        .map(([cls, n]) => {
          const a0 = -Math.PI / 2 + (at / total) * TAU;
          at += n;
          const a1 = -Math.PI / 2 + (at / total) * TAU;
          if (n === total)
            return (
              <circle
                key={cls}
                className={`tl-arc ${cls}`}
                cx={x}
                cy={y}
                r={r - 1.6}
              />
            );
          const big = a1 - a0 > Math.PI ? 1 : 0;
          const rr = r - 1.6;
          return (
            <path
              key={cls}
              className={`tl-arc ${cls}`}
              d={`M${f1(x + rr * Math.cos(a0))} ${f1(y + rr * Math.sin(a0))} A${rr} ${rr} 0 ${big} 1 ${f1(x + rr * Math.cos(a1))} ${f1(y + rr * Math.sin(a1))}`}
            />
          );
        })}
    </g>
  );
}

function label(c: Cluster) {
  const n = (kind: string) => c.list.filter((e) => e.kind === kind).length;
  const parts = [];
  if (n("finding"))
    parts.push(`${n("finding")} finding${n("finding") > 1 ? "s" : ""}`);
  if (n("fail"))
    parts.push(`${n("fail")} failed call${n("fail") > 1 ? "s" : ""}`);
  if (n("verdict"))
    parts.push(`${n("verdict")} verdict${n("verdict") > 1 ? "s" : ""}`);
  return parts.join(", ");
}

export const Serpent = memo(function Serpent({
  tree,
  frame,
  p,
  clusters,
  selected,
  hovered,
  onHover,
  onPick,
}: {
  tree: Timeline;
  frame: Frame;
  p: number;
  clusters: Cluster[];
  selected: string | null;
  hovered: string | null;
  onHover: (key: string | null, event?: MouseEvent) => void;
  onPick: (cluster: Cluster) => void;
}) {
  const shown = Math.max(0.004, p);
  const bitten = p >= 0.999;
  const maxW = 12 + 14 * Math.min(1, shown / 0.25);
  const body = useMemo(() => bodyOf(shown, maxW), [shown, maxW]);
  const w = body.w;
  const ticks = [0.25, 0.5, 0.75].map((f) => {
    const [ax, ay] = pt(f, R + 15);
    const [bx, by] = pt(f, R + 21);
    const [lx, ly] = pt(f, R + (f === 0.5 ? 96 : 70));
    return { f, ax, ay, bx, by, lx, ly };
  });
  const hot = clusters.find((c) => c.key === (hovered ?? selected));
  const arc = (a: number, b: number, r: number) => {
    const [x0, y0] = pt(a, r);
    const [x1, y1] = pt(Math.max(b, a + 0.002), r);
    return `M${f1(x0)} ${f1(y0)} A${r} ${r} 0 ${b - a > 0.5 ? 1 : 0} 1 ${f1(x1)} ${f1(y1)}`;
  };
  const key = (event: KeyboardEvent, c: Cluster) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onPick(c);
    }
  };
  return (
    <g>
      <circle className="tl-track" cx={C} cy={C} r={R} />
      {ticks.map((t) => (
        <g key={t.f} className="tl-tick">
          <line x1={t.ax} y1={t.ay} x2={t.bx} y2={t.by} />
          <text
            x={t.lx}
            y={t.ly + 4}
            textAnchor={
              t.f === 0.25 ? "start" : t.f === 0.75 ? "end" : "middle"
            }
          >
            {duration(frame.total * t.f)}
          </text>
        </g>
      ))}
      <path className="tl-hide" d={body.hide} />
      <path className="tl-scales" d={body.scales} />
      {body.spine.map((s, i) => (
        <rect
          key={i}
          className="tl-spine"
          x={-s.s}
          y={-s.s}
          width={2 * s.s}
          height={2 * s.s}
          transform={`translate(${f1(s.x)} ${f1(s.y)}) rotate(${f1(s.r)})`}
        />
      ))}
      <path className="tl-belly" d={body.belly} />
      {hot && hot.f0 <= shown && (
        <path
          className="tl-span"
          d={arc(hot.f0 - 0.002, Math.min(shown, hot.f1 + 0.002), R)}
          strokeWidth={w(Math.min(shown, hot.f)) + 6}
        />
      )}
      {tree.cycles.map((cycle) => {
        const f = frame.frac(cycle.a);
        if (f > shown || f <= 0.002) return null;
        const width = w(f);
        const [ax, ay] = pt(f, R + width / 2);
        const [bx, by] = pt(f, R - width / 2);
        return (
          <line
            key={cycle.i}
            className="tl-cycle"
            x1={ax}
            y1={ay}
            x2={bx}
            y2={by}
          >
            <title>{`Agent cycle ${cycle.i + 1}`}</title>
          </line>
        );
      })}
      <Head
        p={shown}
        w={w(shown) || maxW}
        bitten={bitten}
        live={tree.live && !bitten}
      />
      {clusters.map((c) => {
        const width = w(Math.min(c.f, shown)) || 4;
        const future = c.f0 > shown + 1e-6;
        const cls = `tl-mark ${c.side}${future ? " fut" : ""}${selected === c.key ? " sel" : ""}`;
        const common = {
          className: cls,
          role: "button",
          tabIndex: future ? -1 : 0,
          "aria-label": label(c),
          onMouseMove: (event: MouseEvent) => onHover(c.key, event),
          onMouseLeave: () => onHover(null),
          onClick: () => onPick(c),
          onKeyDown: (event: KeyboardEvent) => key(event, c),
        };
        if (c.side === "out") {
          const findings = c.list.filter((e) => e.kind === "finding");
          const fails = c.list.filter((e) => e.kind === "fail");
          let r = R + width / 2 + 18 + c.lane * 30;
          const [sx, sy] = pt(c.f, R + width / 2 + 1);
          const [ex, ey] = pt(c.f, r - 9);
          const parts = [];
          if (findings.length) {
            const [x, y] = pt(c.f, r);
            const s = findings.length > 1 ? 10 : 8;
            const worst = findings
              .map((e) => sevOf(e.kind === "finding" ? e.item.severity : null))
              .sort((a, b) => SEVERITIES.indexOf(a) - SEVERITIES.indexOf(b))[0];
            const echo = findings.every(
              (e) => e.kind === "finding" && e.item.relation === "duplicate",
            );
            parts.push(
              <g
                key="gem"
                className={`tl-gem tl-sev-${worst}${echo ? " echo" : ""}`}
              >
                <path
                  d={`M${f1(x)} ${f1(y - s)} l${s} ${s} -${s} ${s} -${s} -${s}z`}
                />
                {findings.length > 1 ? (
                  <text x={x} y={y + 3.6} textAnchor="middle">
                    {findings.length}
                  </text>
                ) : (
                  <path
                    className="tl-core"
                    d={`M${f1(x)} ${f1(y - 3)} l3 3 -3 3 -3 -3z`}
                  />
                )}
              </g>,
            );
            r += 21;
          }
          if (fails.length) {
            const [x, y] = pt(c.f, r);
            const [tx, ty] = pt(c.f + 9 / (TAU * R), r);
            parts.push(
              <g key="x" className="tl-fail">
                <path
                  d={`M${f1(x - 4)} ${f1(y - 4)} l8 8 M${f1(x + 4)} ${f1(y - 4)} l-8 8`}
                />
                {fails.length > 1 && (
                  <text x={tx + 2} y={ty + 3.6}>
                    {fails.length}
                  </text>
                )}
              </g>,
            );
          }
          const [hx, hy] = pt(c.f, R + width / 2 + 28 + c.lane * 30);
          return (
            <g key={c.key} {...common}>
              <line className="tl-stem" x1={sx} y1={sy} x2={ex} y2={ey} />
              <circle className="tl-rivet" cx={sx} cy={sy} r={1.8} />
              {parts}
              <circle className="tl-hit" cx={hx} cy={hy} r={18} />
            </g>
          );
        }
        const [x, y] = pt(c.f, R - width / 2 - 14 - c.lane * 22);
        const count = (k: string) =>
          c.list.filter(
            (e) => e.kind === "verdict" && verdictClass(e.item.outcome) === k,
          ).length;
        const single = c.list.length === 1;
        const first = c.list[0];
        const only =
          single && first.kind === "verdict"
            ? verdictClass(first.item.outcome)
            : "";
        return (
          <g key={c.key} {...common}>
            {single ? (
              only === "refuted" ? (
                <path
                  className="tl-v refuted"
                  d={`M${f1(x - 4)} ${f1(y + 4)} L${f1(x + 4)} ${f1(y - 4)}`}
                />
              ) : (
                <circle className={`tl-v ${only}`} cx={x} cy={y} r={4} />
              )
            ) : (
              <>
                <Donut
                  x={x}
                  y={y}
                  r={9}
                  parts={[
                    ["supported", count("supported")],
                    ["refuted", count("refuted")],
                    ["other", count("other")],
                  ]}
                />
                <text className="tl-n" x={x} y={y + 3.4} textAnchor="middle">
                  {c.list.length}
                </text>
              </>
            )}
            <circle className="tl-hit" cx={x} cy={y} r={13} />
          </g>
        );
      })}
    </g>
  );
});
