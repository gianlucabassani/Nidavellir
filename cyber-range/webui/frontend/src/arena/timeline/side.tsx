// UX-28: the panel beside the serpent. By default it is the run in numbers,
// each drawn as a share: the time and step budgets, failed calls, the
// agent's verdicts, findings by severity, where the steps went and the
// activity. A mark opens what it groups; a finding opens its report.
import { FindingReportView } from "../../shared/finding-report";
import {
  SEVERITIES,
  duration,
  sevOf,
  verdictClass,
  type Cluster,
  type Frame,
  type Timeline,
} from "./model";

const pct = (n: number, total: number) =>
  total > 0 ? `${((n / total) * 100).toFixed(n / total < 0.1 ? 1 : 0)}%` : "0%";
const num = (n: number) => n.toLocaleString("en-GB");

function Meter({
  label,
  value,
  detail,
  share,
  tone = "gold",
}: {
  label: string;
  value: string;
  detail: string;
  share: number;
  tone?: "gold" | "bad" | "ok";
}) {
  const clamped = Math.max(0, Math.min(1, share));
  return (
    <div className="tl-meter">
      <div className="tl-meter-head">
        <span className="tl-k">{label}</span>
        <b>{value}</b>
      </div>
      <div
        className={`tl-bar ${tone}`}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped * 100)}
      >
        <i style={{ width: `${clamped * 100}%` }} />
      </div>
      <span className="tl-detail">{detail}</span>
    </div>
  );
}

function Stack({
  label,
  parts,
  empty,
}: {
  label: string;
  parts: { key: string; name: string; n: number }[];
  empty: string;
}) {
  const total = parts.reduce((sum, part) => sum + part.n, 0);
  return (
    <div className="tl-stack">
      <div className="tl-meter-head">
        <span className="tl-k">{label}</span>
        <b>{num(total)}</b>
      </div>
      {total ? (
        <>
          <div className="tl-stackbar" aria-hidden="true">
            {parts
              .filter((part) => part.n)
              .map((part) => (
                <i
                  key={part.key}
                  className={part.key}
                  style={{ flexGrow: part.n }}
                />
              ))}
          </div>
          <ul className="tl-parts">
            {parts
              .filter((part) => part.n)
              .map((part) => (
                <li key={part.key}>
                  <i className={part.key} />
                  <span>{part.name}</span>
                  <b>{num(part.n)}</b>
                  <small>{pct(part.n, total)}</small>
                </li>
              ))}
          </ul>
        </>
      ) : (
        <span className="tl-detail">{empty}</span>
      )}
    </div>
  );
}

function Spark({ tree }: { tree: Timeline }) {
  const { bucket, steps, errors } = tree.activity;
  const keep = Math.min(steps.length, 90);
  const shown = steps.slice(-keep);
  const failed = errors.slice(-keep);
  const peak = Math.max(1, ...shown);
  const unit = bucket === 60 ? "minute" : duration(bucket);
  return (
    <div className="tl-stack">
      <div className="tl-meter-head">
        <span className="tl-k">Steps per {unit}</span>
        <b>peak {peak}</b>
      </div>
      <svg
        className="tl-spark"
        viewBox={`0 0 ${keep * 4} 40`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Steps per ${unit} over the last ${duration(keep * bucket)}`}
      >
        {shown.map((n, i) => (
          <g key={i}>
            <rect
              className="s"
              x={i * 4}
              y={40 - (n / peak) * 38}
              width={3}
              height={(n / peak) * 38}
            />
            {failed[i] > 0 && (
              <rect
                className="e"
                x={i * 4}
                y={40 - (failed[i] / peak) * 38}
                width={3}
                height={Math.max(1.5, (failed[i] / peak) * 38)}
              />
            )}
          </g>
        ))}
      </svg>
      <span className="tl-detail">
        The last {duration(keep * bucket)}; failed calls in red.
      </span>
    </div>
  );
}

export function SidePanel({
  arenaId,
  tree,
  frame,
  clock,
  cluster,
  finding,
  onFinding,
  onBack,
}: {
  arenaId: string;
  tree: Timeline;
  frame: Frame;
  clock: (t: number) => string;
  cluster: Cluster | null;
  finding: string | null;
  onFinding: (id: string) => void;
  onBack: () => void;
}) {
  if (finding) {
    const item = tree.findings.find((f) => f.id === finding);
    return (
      <aside className="tl-side tl-side-report" aria-label="Finding report">
        <button type="button" className="tl-back" onClick={onBack}>
          ← {cluster ? "Back to the mark" : "Back to the run"}
        </button>
        <span className="tl-k">
          Finding · {item ? `${clock(item.t)} · ${sevOf(item.severity)}` : ""}
        </span>
        <h3 className="tl-title">{item?.title}</h3>
        <FindingReportView arenaId={arenaId} findingId={finding} />
      </aside>
    );
  }
  if (cluster) {
    const findings = cluster.list.flatMap((e) =>
      e.kind === "finding" ? [e] : [],
    );
    const fails = cluster.list.flatMap((e) => (e.kind === "fail" ? [e] : []));
    const verdicts = cluster.list.flatMap((e) =>
      e.kind === "verdict" ? [e] : [],
    );
    const first = cluster.list[0].t;
    const last = cluster.list[cluster.list.length - 1].t;
    return (
      <aside className="tl-side" aria-label="What this mark groups">
        <button type="button" className="tl-back" onClick={onBack}>
          ← Back to the run
        </button>
        <span className="tl-k">
          {first === last ? clock(first) : `${clock(first)}–${clock(last)}`} ·{" "}
          {(cluster.f0 * 100).toFixed(1)}% of the budget
        </span>
        {findings.length > 0 && (
          <section className="tl-group">
            <h4>
              {findings.length} {findings.length === 1 ? "finding" : "findings"}
            </h4>
            <ul className="tl-list">
              {findings.map((e) => (
                <li key={`${e.item.id}-${e.t}`}>
                  <button
                    type="button"
                    disabled={!e.item.id}
                    onClick={() => e.item.id && onFinding(e.item.id)}
                  >
                    <i className={`tl-dot tl-sev-${sevOf(e.item.severity)}`} />
                    <span>{e.item.title}</span>
                    <small>{clock(e.t)}</small>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        {fails.length > 0 && (
          <section className="tl-group">
            <h4 className="bad">
              {fails.length} failed {fails.length === 1 ? "call" : "calls"}
            </h4>
            <ul className="tl-list plain">
              {fails.slice(0, 40).map((e, i) => (
                <li key={i}>
                  <span>
                    <b>{e.item.tool}</b> {e.item.target}
                  </span>
                  <small>
                    {clock(e.t)} · {e.item.status.replace("_", " ")}
                  </small>
                </li>
              ))}
            </ul>
            {fails.length > 40 && (
              <p className="tl-detail">and {fails.length - 40} more</p>
            )}
          </section>
        )}
        {verdicts.length > 0 && (
          <section className="tl-group">
            <h4>
              {verdicts.length}{" "}
              {verdicts.length === 1
                ? "hypothesis verdict"
                : "hypothesis verdicts"}
            </h4>
            <ul className="tl-list plain">
              {verdicts.map((e, i) => (
                <li key={i}>
                  <span>
                    <i
                      className={`tl-dot tl-v-${verdictClass(e.item.outcome)}`}
                    />
                    <b>{e.item.id}</b> {e.item.outcome || "tested"}
                    {e.item.claim && <em>{e.item.claim}</em>}
                  </span>
                  <small>
                    {clock(e.t)}
                    {e.item.findings.length
                      ? ` · ${e.item.findings.length} finding${e.item.findings.length > 1 ? "s" : ""}`
                      : ""}
                  </small>
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
    );
  }
  const elapsed = Math.max(0, tree.duration - tree.clock.start);
  const total =
    tree.clock.deadline != null ? tree.clock.deadline - tree.clock.start : null;
  const verdict = (k: string) =>
    tree.verdicts.filter((v) => verdictClass(v.outcome) === k).length;
  const bySev = (k: string) =>
    tree.findings.filter((f) => sevOf(f.severity) === k).length;
  const fam = (k: string) => tree.families[k] || 0;
  const repeats = tree.findings.filter(
    (f) => f.relation && f.relation !== "independent",
  ).length;
  return (
    <aside className="tl-side" aria-label="The run in numbers">
      <span className="tl-k">The run in numbers</span>
      <Meter
        label="Time budget"
        value={total ? pct(Math.min(elapsed, total), total) : duration(elapsed)}
        share={total ? elapsed / total : 1}
        detail={
          total
            ? elapsed >= total
              ? `${duration(total)} spent. The serpent bites its tail.`
              : `${duration(elapsed)} of ${duration(total)} · ${duration(total - elapsed)} left · deadline from the ${tree.clock.source === "budget" ? "budget policy" : "arena lease"}`
            : "No deadline is set, so the circle is the run so far."
        }
      />
      {tree.budget?.cap != null && (
        <Meter
          label="Step budget"
          value={pct(tree.budget.spent || 0, tree.budget.cap)}
          share={(tree.budget.spent || 0) / tree.budget.cap}
          detail={`${num(tree.budget.spent || 0)} of ${num(tree.budget.cap)} steps`}
        />
      )}
      <Meter
        label="Failed calls"
        tone="bad"
        value={pct(tree.totals.errors, tree.totals.steps)}
        share={tree.totals.steps ? tree.totals.errors / tree.totals.steps : 0}
        detail={`${num(tree.totals.errors)} of ${num(tree.totals.steps)} steps${tree.totals.refused ? ` · ${num(tree.totals.refused)} refused by the budget` : ""}`}
      />
      <Stack
        label="Hypothesis verdicts"
        empty="The agent has not marked a hypothesis tested yet."
        parts={[
          { key: "tl-v-supported", name: "Supported", n: verdict("supported") },
          { key: "tl-v-refuted", name: "Refuted", n: verdict("refuted") },
          { key: "tl-v-other", name: "Other", n: verdict("other") },
        ]}
      />
      <Stack
        label="Findings by severity"
        empty="No findings yet."
        parts={SEVERITIES.map((k) => ({
          key: `tl-sev-${k}`,
          name:
            k === "info" ? "Info or unrated" : k[0].toUpperCase() + k.slice(1),
          n: bySev(k),
        }))}
      />
      {repeats > 0 && (
        <p className="tl-detail">
          {repeats} {repeats === 1 ? "finding repeats" : "findings repeat"} an
          earlier one (duplicate or variant).
        </p>
      )}
      <Stack
        label="Where the steps went"
        empty="No steps yet."
        parts={[
          { key: "tl-f-http", name: "HTTP requests", n: fam("http") },
          { key: "tl-f-exec", name: "Commands", n: fam("exec") },
          { key: "tl-f-model", name: "Model calls", n: fam("model") },
          { key: "tl-f-other", name: "Platform tools", n: fam("other") },
        ]}
      />
      {tree.totals.steps > 0 && <Spark tree={tree} />}
      <div className="tl-meter-head">
        <span className="tl-k">Findings</span>
        <b>{tree.findings.length}</b>
      </div>
      {tree.findings.length ? (
        <ul className="tl-list">
          {tree.findings.map((f) => (
            <li key={`${f.id}-${f.t}`}>
              <button
                type="button"
                disabled={!f.id}
                onClick={() => f.id && onFinding(f.id)}
              >
                <i className={`tl-dot tl-sev-${sevOf(f.severity)}`} />
                <span>{f.title}</span>
                <small>{(frame.frac(f.t) * 100).toFixed(1)}%</small>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="tl-detail">
          Findings sprout from the serpent as the agent reports them.
        </p>
      )}
      {tree.truncated && (
        <p className="tl-detail">
          This run has more steps than the timeline reads at once; the newest
          are counted.
        </p>
      )}
    </aside>
  );
}
