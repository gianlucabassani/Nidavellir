// UX-17: the arena header. A navy "fade" card with the arena's identity,
// state and gate, the primary lifecycle actions, and the facts an operator
// checks first: actions used against the budget, time left, agents, findings.
import { useEffect, useRef, useState } from "react";
import type { ArenaData } from "../types";
import { postJson } from "../api";
import { Status, formatObserved } from "../ui";
import { useBoard } from "../shared/board";
import { Icon } from "../shell/icons";

export type LifecycleAction = "stop" | "resume" | "reset" | "destroy";

const EXTEND = [
  { seconds: 1800, label: "30 minutes" },
  { seconds: 3600, label: "1 hour" },
  { seconds: 7200, label: "2 hours" },
];

function timeLeft(expires: string | null) {
  if (!expires) return "Not set";
  const iso = expires.includes("T") ? expires : expires.replace(" ", "T");
  const at = Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(at)) return "Not reported";
  const minutes = Math.round((at - Date.now()) / 60000);
  if (minutes <= 0) return "Expired";
  return minutes >= 60
    ? `${Math.floor(minutes / 60)} h ${minutes % 60} min`
    : `${minutes} min`;
}

function useMenu() {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
      } else if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);
  return { open, setOpen, wrap };
}

export function ArenaHeader({
  arena,
  liveState,
  onAction,
  onChanged,
}: {
  arena: ArenaData;
  liveState: string;
  onAction: (action: LifecycleAction) => void;
  onChanged: () => void;
}) {
  const extend = useMenu();
  const more = useMenu();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const { board } = useBoard();
  const agents =
    board?.arenas.find((item) => item.id === arena.id)?.agents.length ?? null;
  const gate = (arena.budget.gate || "").toLowerCase();
  const stopped = gate === "stopped";
  const active = arena.state === "active";
  const archived = arena.state === "destroyed";
  const cap = arena.budget.cap;
  const used =
    cap != null && arena.budget.remaining != null
      ? cap - arena.budget.remaining
      : null;
  const ratio = cap && used != null ? Math.min(1, used / cap) : 0;
  const resetAllowed =
    arena.reset.status === "eligible" &&
    ["active", "destroyed"].includes(arena.state);
  const resetReason =
    arena.reset.status === "eligible"
      ? `Unavailable while the arena is ${arena.state}`
      : `Unavailable: ${
          arena.reset.reason
            ? arena.reset.reason.replaceAll("_", " ")
            : "the current recipe cannot be reset"
        }`;

  async function extendBy(seconds: number, label: string) {
    extend.setOpen(false);
    setBusy(true);
    setMessage(null);
    try {
      await postJson(
        `/api/console/arenas/${encodeURIComponent(arena.id)}/extend`,
        { seconds },
      );
      setMessage({ ok: true, text: `Extended by ${label}.` });
      onChanged();
    } catch (reason) {
      setMessage({
        ok: false,
        text: reason instanceof Error ? reason.message : "Extend failed",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={`arena-head ${archived ? "is-archived" : stopped ? "is-stopped" : ""}`}
      aria-labelledby="arena-title"
    >
      <div className="arena-head-top">
        <div className="arena-head-id">
          <div className="label">Arena · {arena.id}</div>
          <h1 id="arena-title" tabIndex={-1}>
            {arena.name}
          </h1>
        </div>
        <div className="arena-head-badges">
          <Status value={arena.state} />
          {gate && gate !== "open" && <Status value={`gate ${gate}`} />}
          {arena.simulation_mode && (
            <span className="feature-tag preview" title="Mock provider">
              Simulated
            </span>
          )}
        </div>
        <div className="arena-head-actions">
          {active && (
            <div className="arena-menu" ref={extend.wrap}>
              <button
                type="button"
                className="button button-on-dark"
                aria-haspopup="menu"
                aria-expanded={extend.open}
                disabled={busy || stopped}
                title={stopped ? "Resume research before extending" : undefined}
                onClick={() => extend.setOpen(!extend.open)}
              >
                <Icon name="clock" /> {busy ? "Extending…" : "Extend time"}
              </button>
              {extend.open && (
                <div className="arena-menu-list" role="menu">
                  {EXTEND.map((choice) => (
                    <button
                      key={choice.seconds}
                      type="button"
                      role="menuitem"
                      onClick={() => extendBy(choice.seconds, choice.label)}
                    >
                      Add {choice.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {active && (
            <button
              type="button"
              className={`button ${stopped ? "button-gold" : "button-on-dark"}`}
              onClick={() => onAction(stopped ? "resume" : "stop")}
            >
              <Icon name={stopped ? "bolt" : "x"} />
              {stopped ? "Resume research" : "Stop research"}
            </button>
          )}
          {arena.state !== "destroying" && (
            <div className="arena-menu" ref={more.wrap}>
              <button
                type="button"
                className="button button-on-dark"
                aria-haspopup="menu"
                aria-expanded={more.open}
                onClick={() => more.setOpen(!more.open)}
              >
                More
              </button>
              {more.open && (
                <div className="arena-menu-list" role="menu">
                  {resetAllowed ? (
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        more.setOpen(false);
                        onAction("reset");
                      }}
                    >
                      Reset arena
                    </button>
                  ) : (
                    <div className="arena-menu-off" aria-disabled="true">
                      <span>Reset arena</span>
                      <small>{resetReason}</small>
                    </div>
                  )}
                  {!archived && (
                    <button
                      type="button"
                      role="menuitem"
                      className="danger"
                      onClick={() => {
                        more.setOpen(false);
                        onAction("destroy");
                      }}
                    >
                      Destroy arena
                    </button>
                  )}
                  <a
                    role="menuitem"
                    href={`/arena/${encodeURIComponent(arena.id)}`}
                    title="Open the retained legacy arena view"
                  >
                    Legacy arena page
                  </a>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <dl className="arena-facts">
        <div>
          <dt>Scenario</dt>
          <dd className="sans">{arena.scenario}</dd>
        </div>
        <div>
          <dt>Actions used</dt>
          <dd>
            {used != null && cap != null ? `${used} / ${cap}` : "Not reported"}
          </dd>
          {used != null && cap != null && (
            <span
              className={`meter ${ratio >= 0.9 ? "bad" : ratio >= 0.75 ? "warn" : ""}`}
              role="img"
              aria-label={`${Math.round(ratio * 100)}% of the action budget used`}
            >
              <i style={{ width: `${ratio * 100}%` }} />
            </span>
          )}
        </div>
        <div>
          <dt>{archived ? "Ended" : "Time left"}</dt>
          <dd>
            {archived
              ? formatObserved(arena.observed_at)
              : timeLeft(arena.expires_at)}
          </dd>
        </div>
        <div>
          <dt>Agents</dt>
          <dd>{agents == null ? "—" : agents || "None"}</dd>
        </div>
        <div>
          <dt>Findings</dt>
          <dd>{arena.findings.length}</dd>
        </div>
        <div>
          <dt>Provider</dt>
          <dd>{arena.simulation_mode ? "mock" : arena.provider}</dd>
        </div>
        <div>
          <dt>Updates</dt>
          <dd className="sans arena-live">
            <span className={`dot ${liveState === "live" ? "ok" : "idle"}`} />
            {liveState === "live"
              ? "Live"
              : liveState === "reconnecting"
                ? "Reconnecting"
                : "Archived snapshot"}
          </dd>
        </div>
      </dl>
      {message && (
        <p
          className={`arena-head-msg ${message.ok ? "ok" : "bad"}`}
          role={message.ok ? "status" : "alert"}
        >
          {message.text}
        </p>
      )}
    </section>
  );
}
