// UX-17 (ADR-0019): dashboard charts in plain SVG/CSS, no chart library.
// Specs: columns <= 24 px with a 4 px rounded data end, 2 px surface gaps
// between stacked segments, hairline solid grid, 2 px lines, markers r >= 4
// with a surface ring. Every chart has a legend for >= 2 series, a per-mark
// tooltip on hover and keyboard focus, and a table view: tooltips enhance,
// they never gate. Family colours passed the CVD validator in both themes.
import { useId, useState, type ReactNode } from "react";
import "./charts.css";

export const FAMILIES = [
  { key: "http", label: "HTTP" },
  { key: "exec", label: "Shell" },
  { key: "model", label: "Model" },
  { key: "other", label: "Other" },
] as const;
export type Family = (typeof FAMILIES)[number]["key"];

export type ActivityBucket = {
  start: string;
} & Record<Family | "failed" | "refused" | "findings" | "spent", number>;

const fmt = new Intl.NumberFormat("en-US");
export const n = (value: number) => fmt.format(value);

function niceMax(value: number) {
  if (value <= 4) return 4;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 4, 5, 10].find((k) => k * power >= value) || 10;
  return step * power;
}

export function clockOf(value: string, withSeconds = false) {
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

function TableToggle({
  table,
  setTable,
}: {
  table: boolean;
  setTable: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      className="chart-view"
      aria-pressed={table}
      onClick={() => setTable(!table)}
    >
      {table ? "Show chart" : "Show table"}
    </button>
  );
}

/** Actions per interval, stacked by family; failures and findings are marks. */
export function ActivityChart({
  buckets,
  bucketSeconds,
  caption,
}: {
  buckets: ActivityBucket[];
  bucketSeconds: number;
  caption: string;
}) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const id = useId();
  const totals = buckets.map((b) =>
    FAMILIES.reduce((sum, f) => sum + b[f.key], 0),
  );
  const max = niceMax(Math.max(1, ...totals));
  const every = Math.max(1, Math.ceil(buckets.length / 6));
  const per =
    bucketSeconds >= 3600
      ? `${bucketSeconds / 3600} h`
      : bucketSeconds >= 60
        ? `${bucketSeconds / 60} min`
        : `${bucketSeconds} s`;
  const sums = Object.fromEntries(
    FAMILIES.map((f) => [f.key, buckets.reduce((s, b) => s + b[f.key], 0)]),
  ) as Record<Family, number>;
  const tip = (b: ActivityBucket, i: number) =>
    `${clockOf(b.start)}: ${n(totals[i])} actions` +
    FAMILIES.filter((f) => b[f.key])
      .map((f) => `, ${f.label} ${n(b[f.key])}`)
      .join("") +
    (b.failed ? `, ${n(b.failed)} failed` : "") +
    (b.refused ? `, ${n(b.refused)} refused` : "") +
    (b.findings
      ? `, ${n(b.findings)} finding${b.findings > 1 ? "s" : ""}`
      : "");
  return (
    <figure className="chart" aria-labelledby={`${id}-cap`}>
      <figcaption id={`${id}-cap`} className="visually-hidden">
        {caption}
      </figcaption>
      {table ? (
        <div className="chart-table-wrap">
          <table className="chart-table">
            <thead>
              <tr>
                <th>From</th>
                {FAMILIES.map((f) => (
                  <th key={f.key} className="r">
                    {f.label}
                  </th>
                ))}
                <th className="r">Failed</th>
                <th className="r">Refused</th>
                <th className="r">Findings</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.start}>
                  <td>{clockOf(b.start)}</td>
                  {FAMILIES.map((f) => (
                    <td key={f.key} className="r">
                      {n(b[f.key])}
                    </td>
                  ))}
                  <td className="r">{n(b.failed)}</td>
                  <td className="r">{n(b.refused)}</td>
                  <td className="r">{n(b.findings)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="act">
          <div className="act-y" aria-hidden="true">
            <span>{n(max)}</span>
            <span>{n(max / 2)}</span>
            <span>0</span>
          </div>
          <div className="act-plot">
            <div className="act-grid" aria-hidden="true">
              <i />
              <i />
            </div>
            <div className="act-cols" role="list">
              {buckets.map((b, i) => (
                <div
                  key={b.start}
                  role="listitem"
                  tabIndex={0}
                  className={`act-col ${hover === i ? "on" : ""}`}
                  aria-label={tip(b, i)}
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                >
                  {b.failed > 0 && (
                    <span className="act-fail" aria-hidden="true">
                      {b.failed}
                    </span>
                  )}
                  <span
                    className="act-stack"
                    style={{ height: `${(totals[i] / max) * 100}%` }}
                  >
                    {FAMILIES.slice()
                      .reverse()
                      .map((f) =>
                        b[f.key] ? (
                          <i
                            key={f.key}
                            className={`fam-${f.key}`}
                            style={{ flexGrow: b[f.key] }}
                          />
                        ) : null,
                      )}
                  </span>
                  {hover === i && (
                    <span className="chart-tip" role="tooltip">
                      <b>{n(totals[i])} actions</b>
                      <span>from {clockOf(b.start)}</span>
                      {FAMILIES.filter((f) => b[f.key]).map((f) => (
                        <span key={f.key} className="tip-row">
                          <i className={`sw fam-${f.key}`} />
                          {f.label} <b>{n(b[f.key])}</b>
                        </span>
                      ))}
                      {b.failed > 0 && <span>{n(b.failed)} failed</span>}
                      {b.refused > 0 && <span>{n(b.refused)} refused</span>}
                      {b.findings > 0 && (
                        <span>
                          {n(b.findings)} finding{b.findings > 1 ? "s" : ""}
                        </span>
                      )}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
          <span aria-hidden="true" />
          <div className="act-marks" aria-hidden="true">
            {buckets.map((b) => (
              <span key={b.start}>
                {b.findings > 0 && <b className="mk-find" />}
              </span>
            ))}
          </div>
          <span aria-hidden="true" />
          <div className="act-x" aria-hidden="true">
            {buckets.map((b, i) => (
              <span key={b.start}>
                {i % every === 0 ? clockOf(b.start) : ""}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="chart-legend">
        <span className="chart-cap">Actions per {per}</span>
        {FAMILIES.map((f) => (
          <span key={f.key}>
            <i className={`sw fam-${f.key}`} />
            {f.label} <b>{n(sums[f.key])}</b>
          </span>
        ))}
        <span>
          <span className="act-fail">n</span> Failed
        </span>
        <span>
          <b className="mk-find" /> Finding
        </span>
        <TableToggle table={table} setTable={setTable} />
      </div>
    </figure>
  );
}

/** Budget spent over time against the limit, projected to expiry when live. */
export function BurnChart({
  buckets,
  bucketSeconds,
  start,
  end,
  expires,
  used,
  cap,
  live,
}: {
  buckets: ActivityBucket[];
  bucketSeconds: number;
  start: string;
  end: string;
  expires: string | null;
  used: number;
  cap: number;
  live: boolean;
}) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const t0 = Date.parse(start.replace(" ", "T") + "Z");
  const tNow = Date.parse(end.replace(" ", "T") + "Z");
  const tEnd =
    live && expires
      ? Math.max(
          tNow,
          Date.parse(
            expires.replace(" ", "T") +
              (/[zZ]|[+-]\d\d:\d\d$/.test(expires) ? "" : "Z"),
          ),
        )
      : tNow;
  const span = Math.max(1, tEnd - t0);
  const top = Math.max(cap, used, 1);
  const X = (t: number) => ((t - t0) / span) * 100;
  const Y = (v: number) => 100 - (v / top) * 100;
  // Cumulative spend from the spans; the last point is the service's own count.
  let cumulative = 0;
  const points = buckets.map((b, i) => {
    cumulative += b.spent;
    return {
      t: Math.min(t0 + (i + 1) * bucketSeconds * 1000, tNow),
      v: cumulative,
    };
  });
  if (points.length) points[points.length - 1].v = used;
  const path = [{ t: t0, v: 0 }, ...points];
  const line = path
    .map((p) => `${X(p.t).toFixed(2)},${Y(p.v).toFixed(2)}`)
    .join(" ");
  const recent = buckets.slice(-3);
  const pace =
    recent.reduce((s, b) => s + b.spent, 0) /
    Math.max(1, (recent.length * bucketSeconds) / 60);
  let projection: ReactNode = null;
  let sentence: ReactNode;
  if (live && expires && tEnd > tNow && pace > 0) {
    const minutesLeft = (tEnd - tNow) / 60000;
    const toLimit = (cap - used) / pace;
    const endMinutes = Math.min(minutesLeft, toLimit);
    projection = (
      <line
        className="burn-proj"
        x1={X(tNow)}
        y1={Y(used)}
        x2={X(tNow + endMinutes * 60000)}
        y2={Y(used + pace * endMinutes)}
      />
    );
    sentence =
      toLimit < minutesLeft ? (
        <>
          At {pace.toFixed(1)} actions/min the budget runs out at{" "}
          <b>{clockOf(new Date(tNow + toLimit * 60000).toISOString())}</b>,{" "}
          {Math.round(minutesLeft - toLimit)} min before the arena expires.
        </>
      ) : (
        <>
          At {pace.toFixed(1)} actions/min the budget lasts until expiry, ending
          near <b>{n(Math.round(used + pace * minutesLeft))}</b> of {n(cap)}.
        </>
      );
  } else if (used >= cap)
    sentence = (
      <>
        Budget exhausted. Agents are refused every action until you raise the
        limit.
      </>
    );
  else if (live && pace === 0)
    sentence = <>No budgeted action in the last intervals, so no projection.</>;
  else
    sentence = (
      <>
        <b>{n(used)}</b> of {n(cap)} used
        {live ? ". No expiry is set, so there is no projection." : "."}
      </>
    );
  return (
    <figure className="chart">
      {table ? (
        <div className="chart-table-wrap">
          <table className="chart-table">
            <thead>
              <tr>
                <th>Until</th>
                <th className="r">Spent in interval</th>
                <th className="r">Spent so far</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={i}>
                  <td>{clockOf(new Date(p.t).toISOString())}</td>
                  <td className="r">{n(buckets[i].spent)}</td>
                  <td className="r">{n(p.v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="burn">
          <div className="act-y" aria-hidden="true">
            <span>{n(Math.round(top))}</span>
            <span>{n(Math.round(top / 2))}</span>
            <span>0</span>
          </div>
          <div
            className="burn-plot"
            onPointerMove={(event) => {
              const box = event.currentTarget.getBoundingClientRect();
              const t = t0 + ((event.clientX - box.left) / box.width) * span;
              let best = 0;
              path.forEach((p, i) => {
                if (Math.abs(p.t - t) < Math.abs(path[best].t - t)) best = i;
              });
              setHover(best);
            }}
            onPointerLeave={() => setHover(null)}
          >
            <svg
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <line
                className="burn-grid"
                x1="0"
                x2="100"
                y1={Y(top / 2)}
                y2={Y(top / 2)}
              />
              <line
                className="burn-limit"
                x1="0"
                x2="100"
                y1={Y(cap)}
                y2={Y(cap)}
              />
              <polygon
                className="burn-area"
                points={`0,100 ${line} ${X(tNow)},100`}
              />
              <polyline className="burn-line" points={line} />
              {projection}
              {tEnd > tNow && (
                <line
                  className="burn-now"
                  x1={X(tNow)}
                  x2={X(tNow)}
                  y1="0"
                  y2="100"
                />
              )}
              {hover != null && (
                <line
                  className="burn-cross"
                  x1={X(path[hover].t)}
                  x2={X(path[hover].t)}
                  y1="0"
                  y2="100"
                />
              )}
            </svg>
            <span className="burn-tag limit" style={{ top: `${Y(cap)}%` }}>
              Limit {n(cap)}
            </span>
            {hover != null && (
              <>
                <span
                  className="burn-dot"
                  style={{
                    left: `${X(path[hover].t)}%`,
                    top: `${Y(path[hover].v)}%`,
                  }}
                />
                <span
                  className="chart-tip"
                  role="tooltip"
                  style={{ left: `${Math.min(80, X(path[hover].t))}%` }}
                >
                  <b>{n(path[hover].v)} spent</b>
                  <span>
                    by {clockOf(new Date(path[hover].t).toISOString())}
                  </span>
                </span>
              </>
            )}
          </div>
          <span aria-hidden="true" />
          <div className="burn-x" aria-hidden="true">
            <span>{clockOf(start)}</span>
            {tEnd > tNow && X(tNow) > 14 && X(tNow) < 62 && (
              <span className="burn-x-now" style={{ left: `${X(tNow)}%` }}>
                Now
              </span>
            )}
            <span>
              {tEnd > tNow
                ? `Expires ${clockOf(new Date(tEnd).toISOString())}`
                : clockOf(end)}
            </span>
          </div>
        </div>
      )}
      <p className="chart-say">{sentence}</p>
      <div className="chart-legend">
        <span>
          <i className="sw line" /> Spent
        </span>
        <span>
          <i className="sw limit" /> Limit
        </span>
        {projection && (
          <span>
            <i className="sw proj" /> Projection
          </span>
        )}
        <TableToggle table={table} setTable={setTable} />
      </div>
    </figure>
  );
}

/** One horizontal bar per row; failures are the red end of the same bar. */
export function Bars({
  rows,
}: {
  rows: {
    key: string;
    label: ReactNode;
    sub?: ReactNode;
    value: number;
    failed?: number;
    note?: ReactNode;
    family?: Family;
  }[];
}) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <div className="bars" role="list">
      {rows.map((row) => (
        <div key={row.key} className="bars-row" role="listitem">
          <span className="bars-name">
            {row.label}
            {row.sub && <small>{row.sub}</small>}
          </span>
          <span className="bars-track" aria-hidden="true">
            {row.value > 0 && (
              <>
                <i
                  className={row.family ? `fam-${row.family}` : "bars-fill"}
                  style={{
                    width: `${((row.value - (row.failed || 0)) / max) * 100}%`,
                  }}
                />
                {row.failed ? (
                  <i
                    className="bars-bad"
                    style={{
                      width: `${Math.max(1.5, (row.failed / max) * 100)}%`,
                    }}
                  />
                ) : null}
              </>
            )}
          </span>
          <span className="bars-n">{row.value ? n(row.value) : "—"}</span>
          <span className="bars-note">
            {row.failed ? `${n(row.failed)} failed` : row.note}
          </span>
        </div>
      ))}
    </div>
  );
}

/** One whole split into parts (thin segmented bar) with its legend. */
export function Share({
  parts,
}: {
  parts: {
    key: string;
    label: string;
    value: number;
    tone: "ok" | "bad" | "warn";
  }[];
}) {
  const sum = parts.reduce((s, p) => s + p.value, 0);
  const pct = (v: number) =>
    sum ? `${((v / sum) * 100).toFixed(v / sum < 0.1 && v ? 1 : 0)}%` : "—";
  return (
    <div className="share-wrap">
      <div
        className="share"
        role="img"
        aria-label={parts
          .map((p) => `${p.label} ${n(p.value)} (${pct(p.value)})`)
          .join(", ")}
      >
        {parts
          .filter((p) => p.value)
          .map((p) => (
            <i
              key={p.key}
              className={`tone-${p.tone}`}
              style={{ flexGrow: p.value }}
            />
          ))}
      </div>
      <dl className="share-legend">
        {parts.map((p) => (
          <div key={p.key}>
            <dt>
              <i className={`sw tone-${p.tone}`} />
              {p.label}
            </dt>
            <dd>
              {n(p.value)} <span>{pct(p.value)}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
