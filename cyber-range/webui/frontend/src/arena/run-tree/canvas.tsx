// UX-27: the run tree's drawing. One element per branch, cycle, cluster of
// failed calls and finding: never one per step.
import type { KeyboardEvent, MouseEvent } from "react";
import {
  clusters,
  duration,
  placeLabels,
  type Branch,
  type Layout,
  type RunTree,
  type TreeError,
} from "./model";

export type Hover =
  | { kind: "branch"; id: string }
  | { kind: "ring"; i: number }
  | { kind: "trunk"; t: number }
  | { kind: "knot"; owner: string; list: TreeError[] }
  | { kind: "fruit"; id: string };
export type Pick =
  | { kind: "route"; key: string; focus?: number }
  | { kind: "cycle"; i: number }
  | { kind: "trunk"; focus?: number };

const cut = (text: string, max: number) =>
  text.length > max ? `${text.slice(0, Math.max(1, max - 1))}…` : text;
const ease = (k: number) => 1 - Math.pow(1 - Math.max(0, Math.min(1, k)), 3);

export function TreeCanvas({
  tree,
  branches,
  g,
  T,
  selected,
  dimmed,
  hits,
  onHover,
  onLeave,
  onPick,
  clock,
}: {
  tree: RunTree;
  branches: Branch[];
  g: Layout;
  /** The replay clock (seconds); the full duration when not replaying. */
  T: number;
  selected: string | null;
  dimmed: (branch: Branch) => boolean;
  hits: Record<string, number>;
  onHover: (hover: Hover, event: MouseEvent) => void;
  onLeave: () => void;
  onPick: (pick: Pick) => void;
  clock: (t: number) => string;
}) {
  const { W, H, cx, Y, bx, base, labelX, narrow } = g;
  const key = (event: KeyboardEvent, run: () => void) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      run();
    }
  };
  const ticks: number[] = [];
  let last = Infinity;
  for (let t = 0; t <= g.dur; t += 60) {
    const y = Y(t);
    if (last - y < 70 || g.gaps.some((gap) => t > gap.a && t < gap.b)) continue;
    last = y;
    ticks.push(t);
  }
  const knot = (
    x: number,
    c: { y: number; list: TreeError[] },
    side: number,
    owner: string,
    pick: Pick,
  ) => {
    const s = c.list.length > 1 ? 5.6 : 4.4;
    return (
      <g
        key={`k${owner}${c.list[0].id}`}
        className="rt-knot"
        role="button"
        tabIndex={0}
        aria-label={`${c.list.length} failed call${c.list.length > 1 ? "s" : ""}`}
        onMouseMove={(event) => {
          event.stopPropagation();
          onHover({ kind: "knot", owner, list: c.list }, event);
        }}
        onMouseLeave={onLeave}
        onClick={(event) => {
          event.stopPropagation();
          onPick(pick);
        }}
        onKeyDown={(event) => key(event, () => onPick(pick))}
      >
        <circle cx={x} cy={c.y} r={11} fill="transparent" />
        <rect
          x={-s}
          y={-s}
          width={2 * s}
          height={2 * s}
          rx={1.4}
          transform={`translate(${x} ${c.y}) rotate(45)`}
        />
        {c.list.length > 1 && (
          <text
            x={x + side * 11}
            y={c.y + 4}
            textAnchor={side < 0 ? "end" : "start"}
          >
            {c.list.length}
          </text>
        )}
      </g>
    );
  };
  // One label per route, at the tip of its newest episode.
  const tips = branches.filter(
    (branch) => branch.ep.last && branch.ep.a <= T && !dimmed(branch),
  );
  const labels = narrow
    ? []
    : ([-1, 1] as const).flatMap((side) =>
        placeLabels(
          tips
            .filter((branch) => branch.side === side)
            .map((branch) => ({
              item: branch,
              want:
                Math.min(Y(Math.min(T, branch.ep.b)), Y(branch.ep.a) - 18) - 6,
            })),
        ).map((label) => ({ ...label, side })),
      );
  const trunkTop = Y(Math.min(T, g.dur));
  return (
    <svg
      className="rt-svg"
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      role="group"
      aria-label="Run tree"
    >
      <defs>
        <filter
          id="rt-glow"
          filterUnits="userSpaceOnUse"
          x={-40}
          y={-40}
          width={W + 80}
          height={H + 80}
        >
          <feGaussianBlur stdDeviation={3.6} result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <linearGradient
          id="rt-trunk"
          gradientUnits="userSpaceOnUse"
          x1={0}
          x2={0}
          y1={base}
          y2={0}
        >
          <stop offset="0" stopColor="var(--rt-bark-deep)" />
          <stop offset="1" stopColor="var(--rt-bark)" />
        </linearGradient>
        <radialGradient id="rt-well" cx=".5" cy=".5" r=".5">
          <stop offset="0" stopColor="var(--rt-well)" />
          <stop offset="1" stopColor="var(--rt-well)" stopOpacity="0" />
        </radialGradient>
      </defs>
      {ticks.map((t) => (
        <text
          key={t}
          className="rt-tick"
          x={4}
          y={Y(t) + 4}
          opacity={t <= T ? 1 : 0.3}
        >
          {clock(t)}
        </text>
      ))}
      {!narrow &&
        g.gaps
          .filter((gap) => gap.a <= T)
          .map((gap) => (
            <text
              key={gap.a}
              className="rt-gap"
              x={cx + 18}
              y={(Y(gap.a) + Y(gap.b)) / 2 + 4}
            >
              {duration(gap.b - gap.a)} with nothing running
            </text>
          ))}
      <ellipse
        cx={cx}
        cy={base + 48}
        rx={Math.min(220, cx * 0.6)}
        ry={30}
        fill="url(#rt-well)"
      />
      <g className="rt-roots">
        {[-1, 1].flatMap((side) =>
          [0, 1, 2].map((i) => (
            <path
              key={`${side}${i}`}
              d={`M${cx + side * 3} ${base} C${cx + side * (16 + i * 12)} ${base + 14 + i * 5},${cx + side * (44 + i * 34)} ${base + 24 + i * 9},${cx + side * (64 + i * 44)} ${base + 46 + i * 13}`}
              strokeWidth={3.4 - i}
            />
          )),
        )}
      </g>
      <text className="rt-start" x={cx} y={base + 96} textAnchor="middle">
        Started {clock(0)}
      </text>

      {/* The trunk: one stretch per cycle of the agent, dotted between them. */}
      {tree.cycles.map((c, i) =>
        c.a > T ? null : (
          <g key={c.i}>
            {i > 0 && (
              <line
                className="rt-dots"
                x1={cx}
                x2={cx}
                y1={Y(tree.cycles[i - 1].b)}
                y2={Y(c.a)}
              />
            )}
            <line
              className={`rt-trunk ${selected === `cycle:${c.i}` ? "on" : ""}`}
              x1={cx}
              x2={cx}
              y1={Y(c.a) + 4}
              y2={Math.min(Y(c.a) - 2, Y(Math.min(c.b, T)))}
              onMouseMove={(event) => {
                const box = (
                  event.currentTarget.ownerSVGElement as SVGSVGElement
                ).getBoundingClientRect();
                onHover(
                  {
                    kind: "trunk",
                    t: g.T(((event.clientY - box.top) * H) / box.height),
                  },
                  event,
                );
              }}
              onMouseLeave={onLeave}
              onClick={() => onPick({ kind: "trunk" })}
            />
          </g>
        ),
      )}
      {tree.live && T >= g.dur && tree.cycles.length > 0 && (
        <line
          className="rt-dots"
          x1={cx}
          x2={cx}
          y1={Y(tree.cycles[tree.cycles.length - 1].b)}
          y2={trunkTop}
        />
      )}
      {tree.cycles.map((c) =>
        c.a > T ? null : (
          <g
            key={`r${c.i}`}
            className="rt-ring"
            role="button"
            tabIndex={0}
            aria-label={`Cycle ${c.i + 1}`}
            onMouseMove={(event) => onHover({ kind: "ring", i: c.i }, event)}
            onMouseLeave={onLeave}
            onClick={() => onPick({ kind: "cycle", i: c.i })}
            onKeyDown={(event) =>
              key(event, () => onPick({ kind: "cycle", i: c.i }))
            }
          >
            <ellipse cx={cx} cy={Y(c.a)} rx={16} ry={5.5} />
            {!narrow && (
              <>
                <text className="h" x={cx - 28} y={Y(c.a) - 6} textAnchor="end">
                  Cycle {c.i + 1}
                </text>
                <text x={cx - 28} y={Y(c.a) + 10} textAnchor="end">
                  {duration(c.b - c.a)} · {c.steps} steps
                  {c.errors ? (
                    <tspan className="err">{` · ${c.errors} failed`}</tspan>
                  ) : null}
                </text>
              </>
            )}
          </g>
        ),
      )}

      {branches.map((branch) => {
        const { ep, route } = branch;
        if (ep.a > T) return null;
        const x = bx(branch);
        const d = x - cx;
        const y0 = Y(ep.a);
        const yt = Math.min(Y(Math.min(T, ep.b)), y0 - 18);
        const grown = T >= ep.b;
        const on = selected === route.key;
        const off = dimmed(branch);
        const hit = (hits[route.key] || 0) > 0;
        const birth = T < g.dur ? ease((T - ep.a) / 40) : 1;
        const curve = `M${cx} ${y0} C${cx + d * 0.55} ${y0},${x} ${y0 - 4},${x} ${y0 - 18}`;
        const width = on ? 5 : hit ? 4 : 3 + Math.min(1.5, ep.steps / 60);
        const tip = ep.last ? route.state : "paused";
        const open = () => onPick({ kind: "route", key: route.key });
        return (
          <g
            key={branch.id}
            className={`rt-branch ${route.state} ${off ? "dim" : ""} ${on ? "on" : ""} ${hit ? "hit" : ""}`}
          >
            <g
              role="button"
              tabIndex={off ? -1 : 0}
              aria-label={`${route.name}: ${route.claim || ""} ${ep.steps} steps`}
              onMouseMove={(event) =>
                onHover({ kind: "branch", id: branch.id }, event)
              }
              onMouseLeave={onLeave}
              onClick={open}
              onKeyDown={(event) => key(event, open)}
            >
              <path d={`${curve} L${x} ${yt}`} className="rt-hitarea" />
              <path
                d={curve}
                className="rt-stroke"
                strokeWidth={width}
                pathLength={1}
                strokeDasharray={birth < 1 ? `${birth} 1` : undefined}
                filter={on || hit ? "url(#rt-glow)" : undefined}
              />
              {birth >= 1 && yt < y0 - 18 && (
                <line
                  className="rt-stroke"
                  x1={x}
                  x2={x}
                  y1={y0 - 18}
                  y2={yt}
                  strokeWidth={width}
                />
              )}
              {!grown && (
                <circle
                  className="rt-grow"
                  cx={x}
                  cy={yt}
                  r={3.6}
                  filter="url(#rt-glow)"
                />
              )}
              {grown && tip === "finding" && (
                <g className="rt-fruit">
                  <circle cx={x} cy={yt - 6} r={9} filter="url(#rt-glow)" />
                  <path d={`M${x} ${yt - 10.5}l4.5 4.5-4.5 4.5-4.5-4.5z`} />
                </g>
              )}
              {grown && tip === "refuted" && (
                <path
                  className="rt-wither"
                  d={`M${x - 6} ${yt + 1}L${x - 1} ${yt - 4}L${x + 2} ${yt + 2}L${x + 7} ${yt - 3}`}
                />
              )}
              {grown && tip === "done" && (
                <g className="rt-bud">
                  <circle cx={x} cy={yt} r={6} />
                  <circle cx={x} cy={yt} r={2.4} className="core" />
                </g>
              )}
              {grown && tip === "open" && (
                <circle
                  className={`rt-open ${tree.live ? "live" : ""}`}
                  cx={x}
                  cy={yt}
                  r={5}
                />
              )}
              {grown && tip === "paused" && (
                <rect
                  className="rt-stub"
                  x={x - 4}
                  y={yt - 1.5}
                  width={8}
                  height={3}
                />
              )}
            </g>
            {!off &&
              clusters(
                ep.errors.filter((e) => e.t <= T),
                (e) => Math.min(Y(e.t), y0 - 20),
              ).map((c) =>
                knot(x, c, branch.side, branch.id, {
                  kind: "route",
                  key: route.key,
                  focus: c.list[0].id,
                }),
              )}
          </g>
        );
      })}
      {clusters(
        tree.trunk.errors.filter((e) => e.t <= T),
        (e) => Y(e.t),
      ).map((c) =>
        knot(cx, c, -1, "trunk", { kind: "trunk", focus: c.list[0].id }),
      )}
      {tree.findings
        .filter((f) => !f.route && f.t <= T)
        .map((f) => (
          <g
            key={f.id}
            className="rt-fruit trunk"
            onMouseMove={(event) => onHover({ kind: "fruit", id: f.id }, event)}
            onMouseLeave={onLeave}
          >
            <circle cx={cx} cy={Y(f.t)} r={9} filter="url(#rt-glow)" />
          </g>
        ))}

      {labels.map(({ item: branch, want, y, side }) => {
        const route = branch.route;
        const lx = side < 0 ? labelX.left : labelX.right;
        const room = side < 0 ? lx - 70 : W - lx - 10;
        const max = Math.max(12, Math.floor(room / 7));
        const finding = tree.findings.find((f) => f.route === route.key);
        const text = finding
          ? finding.title
          : route.claim || `${route.steps} steps`;
        const hitCount = hits[route.key] || 0;
        const open = () => onPick({ kind: "route", key: route.key });
        return (
          <g
            key={`l${route.key}`}
            className={`rt-label ${route.state}`}
            onMouseMove={(event) =>
              onHover({ kind: "branch", id: branch.id }, event)
            }
            onMouseLeave={onLeave}
            onClick={open}
          >
            <path
              d={`M${bx(branch) + side * 8} ${want + 6} L${lx - side * 26} ${want + 6} L${lx - side * 8} ${y}`}
            />
            <text
              className="h"
              x={lx}
              y={y - 3}
              textAnchor={side < 0 ? "end" : "start"}
            >
              {route.name}
              {route.errors ? (
                <tspan className="err">{`  ◆${route.errors}`}</tspan>
              ) : null}
              {hitCount ? (
                <tspan className="hits">{`  ${hitCount}×`}</tspan>
              ) : null}
            </text>
            <text x={lx} y={y + 12} textAnchor={side < 0 ? "end" : "start"}>
              {cut(text, max)}
            </text>
          </g>
        );
      })}

      {(tree.live || T < g.dur) && (
        <g className="rt-now">
          <circle cx={cx} cy={trunkTop} r={7} filter="url(#rt-glow)" />
          <text x={cx} y={trunkTop - 16} textAnchor="middle">
            {tree.live && T >= g.dur ? `Now ${clock(T)}` : clock(T)}
          </text>
        </g>
      )}
    </svg>
  );
}
