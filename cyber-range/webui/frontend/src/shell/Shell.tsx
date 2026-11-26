// UX-16 (ADR-0019): the console shell. A navy top bar picks the workspace;
// the left sidebar is the only menu (inside an arena it becomes the arena's
// own menu, rendered by the arena workspace into #rail-arena). Only the
// sidebar menu scrolls: account and theme stay pinned at its foot.
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import type { Theme } from "../types";
import { Rune } from "../ui";
import {
  ago,
  isIdle,
  onDismissedChange,
  readDismissed,
  useBoard,
  type Board,
} from "../shared/board";
import { Icon } from "./icons";
import { NAV, WORKSPACES, arenaIdOf, workspaceOf, type NavItem } from "./nav";
import "./shell.css";

type Drawer = "agents" | "attention" | null;

function csrfToken() {
  return (
    document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
      ?.content || ""
  );
}

export function Shell({
  username,
  theme,
  setTheme,
  mainRef,
  children,
}: {
  username: string;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  mainRef?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const path = window.location.pathname;
  const params = new URLSearchParams(window.location.search);
  const arenaId = arenaIdOf(path);
  const space = workspaceOf(path, params);
  const { board, live } = useBoard();
  const [drawer, setDrawer] = useState<Drawer>(null);
  // Below 860 px the sidebar is an overlay opened from the top bar.
  const [railOpen, setRailOpen] = useState(false);
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  useEffect(() => onDismissedChange(setDismissed), []);
  useEffect(() => {
    if (!drawer) return;
    const close = (event: KeyboardEvent) =>
      event.key === "Escape" && setDrawer(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [drawer]);
  // Navigating closes an open drawer and the overlay sidebar.
  const location = path + window.location.search;
  useEffect(() => {
    setDrawer(null);
    setRailOpen(false);
  }, [location]);

  const now = Date.now();
  const agents = board
    ? board.arenas.flatMap((arena) =>
        arena.agents.map((agent) => ({ agent, arena })),
      )
    : [];
  const idle = board
    ? board.arenas
        .filter((arena) => isIdle(arena, board, now))
        .reduce((n, arena) => n + arena.agents.length, 0)
    : 0;
  const attention = board
    ? board.inbox.filter((item) => !dismissed.includes(item.key))
    : [];

  return (
    <div className={`shell ${railOpen ? "rail-open" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="shell-top">
        <header className="topbar">
          <button
            type="button"
            className="tbtn rail-toggle"
            aria-label={railOpen ? "Close menu" : "Open menu"}
            aria-expanded={railOpen}
            aria-controls="shell-rail"
            onClick={() => setRailOpen(!railOpen)}
          >
            <Icon name={railOpen ? "x" : "list"} />
          </button>
          <a
            className="brand"
            href="/console?workspace=research"
            title="Home: Research overview"
          >
            <img src="/static/anvil_emblem.png" alt="" width="30" height="30" />
            <span>
              <b>NIDAVELLIR</b>
              <small>FORGE</small>
            </span>
            <span className="visually-hidden">, go to Research overview</span>
          </a>
          <nav className="spaces" aria-label="Workspaces">
            {WORKSPACES.map((item) => (
              <a
                key={item.id}
                href={`/console?workspace=${item.id}`}
                className={space === item.id ? "on" : ""}
                aria-current={space === item.id ? "page" : undefined}
                title={item.title}
              >
                <Rune kind={item.id} />
                <span>{item.label}</span>
              </a>
            ))}
          </nav>
          <div className="top-actions">
            <button
              type="button"
              className="tbtn tbtn-search"
              onClick={() => window.dispatchEvent(new Event("nv:palette"))}
              aria-keyshortcuts={
                /Mac|iPhone|iPad/.test(navigator.platform)
                  ? "Meta+K"
                  : "Control+K"
              }
            >
              <Icon name="search" />
              <span className="tbtn-text">Search or jump</span>
              <kbd>
                {/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl K"}
              </kbd>
            </button>
            <button
              type="button"
              className="tbtn"
              aria-haspopup="dialog"
              aria-expanded={drawer === "agents"}
              onClick={() => setDrawer(drawer === "agents" ? null : "agents")}
              title="Connected agents"
            >
              <Icon name="agent" />
              <span>
                {board ? agents.length : "–"}
                <span className="tbtn-text">
                  {" "}
                  agent{agents.length === 1 ? "" : "s"}
                </span>
              </span>
              {idle > 0 && <span className="tbtn-count">{idle} idle</span>}
            </button>
            {/* The co-pilot launcher portals here (shared/assistant.tsx). */}
            <div id="assistant-slot" className="assistant-slot" />
            <button
              type="button"
              className="tbtn"
              aria-haspopup="dialog"
              aria-expanded={drawer === "attention"}
              aria-label={`Needs attention: ${attention.length}`}
              onClick={() =>
                setDrawer(drawer === "attention" ? null : "attention")
              }
            >
              <Icon name="bell" />
              {attention.length > 0 && (
                <span className="tbtn-count">{attention.length}</span>
              )}
            </button>
          </div>
        </header>
        <div className="braid" aria-hidden="true" />
      </div>
      {railOpen && (
        <div
          className="shell-scrim rail-scrim"
          onClick={() => setRailOpen(false)}
          aria-hidden="true"
        />
      )}
      <aside className="rail" id="shell-rail" aria-label="Sidebar">
        {arenaId ? (
          <div id="rail-arena" className="rail-arena" />
        ) : (
          <WorkspaceNav space={space} path={path} params={params} />
        )}
        <RailFoot
          username={username}
          theme={theme}
          setTheme={setTheme}
          live={live}
        />
      </aside>
      <main
        className="shell-main"
        id="main"
        ref={mainRef as RefObject<HTMLElement>}
      >
        {children}
      </main>
      {drawer && (
        <>
          <div
            className="shell-scrim"
            onClick={() => setDrawer(null)}
            aria-hidden="true"
          />
          <ShellDrawer
            kind={drawer}
            board={board}
            attention={attention}
            now={now}
            onClose={() => setDrawer(null)}
          />
        </>
      )}
    </div>
  );
}

function WorkspaceNav({
  space,
  path,
  params,
}: {
  space: keyof typeof NAV;
  path: string;
  params: URLSearchParams;
}) {
  return (
    <nav className="rail-nav" aria-label="Workspace">
      {NAV[space].map((group, index) => (
        <div key={group.caption || index} className="rail-group">
          {group.caption && <div className="rail-cap">{group.caption}</div>}
          {group.items.map((item) => (
            <RailLink
              key={item.href}
              item={item}
              current={item.match(path, params)}
            />
          ))}
        </div>
      ))}
    </nav>
  );
}

export function RailLink({
  item,
  current,
  end,
}: {
  item: Pick<NavItem, "label" | "href" | "icon" | "planned">;
  current: boolean;
  end?: ReactNode;
}) {
  if (item.planned)
    return (
      <span className="rail-link off" aria-disabled="true" title={item.planned}>
        <Icon name={item.icon} />
        <span>{item.label}</span>
        <span className="rail-end">
          <span className="feature-tag">Planned</span>
        </span>
        <span className="visually-hidden">. {item.planned}</span>
      </span>
    );
  return (
    <a
      className={`rail-link ${current ? "on" : ""}`}
      href={item.href}
      aria-current={current ? "page" : undefined}
    >
      <Icon name={item.icon} />
      <span>{item.label}</span>
      {end && <span className="rail-end">{end}</span>}
    </a>
  );
}

function RailFoot({
  username,
  theme,
  setTheme,
  live,
}: {
  username: string;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  live: boolean;
}) {
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") {
          setOpen(false);
          toggle.current?.focus();
        }
        return;
      }
      const target = event.target as Node;
      if (!menu.current?.contains(target) && !toggle.current?.contains(target))
        setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    menu.current?.querySelector<HTMLElement>("a, button")?.focus();
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);
  const link = (
    href: string,
    label: string,
    icon: Parameters<typeof Icon>[0]["name"],
  ) => (
    <a href={href} role="menuitem" onClick={() => setOpen(false)}>
      <Icon name={icon} size={14} />
      {label}
    </a>
  );
  return (
    <div className="rail-foot">
      <div className="rail-status" role="status">
        <span className={`dot ${live ? "ok" : "idle"}`} aria-hidden="true" />
        {live ? "Live updates connected" : "Reconnecting to live updates"}
      </div>
      <div className="rail-me">
        <button
          ref={toggle}
          type="button"
          className="rail-who"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <span className="avatar" aria-hidden="true">
            {username.slice(0, 2).toUpperCase()}
          </span>
          <span className="rail-id">
            <b>{username}</b>
            <small>Operator</small>
          </span>
          <Icon name="updown" size={13} />
        </button>
        <div className="seg theme-seg" role="group" aria-label="Theme">
          <button
            type="button"
            aria-pressed={theme === "day"}
            aria-label="Day theme"
            title="Day theme"
            onClick={() => setTheme("day")}
          >
            <Icon name="sun" size={14} />
          </button>
          <button
            type="button"
            aria-pressed={theme === "night"}
            aria-label="Night theme"
            title="Night theme"
            onClick={() => setTheme("night")}
          >
            <Icon name="moon" size={14} />
          </button>
        </div>
        {open && (
          <div className="account-menu" role="menu" ref={menu}>
            {link("/console/profile", "Profile", "user")}
            {link("/console/settings", "Platform settings", "gear")}
            {link("/console/activity?section=audit", "Activity log", "list")}
            <a href="/?legacy=1" role="menuitem">
              <Icon name="clock" size={14} />
              Legacy console
            </a>
            <hr />
            <form method="post" action="/logout">
              <input type="hidden" name="csrf_token" value={csrfToken()} />
              <button type="submit" role="menuitem">
                <Icon name="out" size={14} />
                Log out
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  arena_failed: "Arena failed",
  verdict: "Verdict waiting",
  budget_exhausted: "Budget exhausted",
  stop: "Research stopped",
  trial_finished: "Trial finished",
};

function ShellDrawer({
  kind,
  board,
  attention,
  now,
  onClose,
}: {
  kind: "agents" | "attention";
  board: Board | null;
  attention: Board["inbox"];
  now: number;
  onClose: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.focus();
  }, [kind]);
  const arenas = board
    ? board.arenas.filter((arena) => arena.agents.length)
    : [];
  return (
    <aside
      ref={panel}
      tabIndex={-1}
      className="shell-drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shell-drawer-title"
    >
      <div className="drawer-head">
        <div>
          <div className="label">
            {kind === "agents" ? "Connected now" : "Needs attention"}
          </div>
          <h2 id="shell-drawer-title">
            {kind === "agents"
              ? `${arenas.reduce((n, a) => n + a.agents.length, 0)} agents in ${arenas.length} arenas`
              : attention.length
                ? `${attention.length} waiting for you`
                : "Nothing waiting"}
          </h2>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="Close"
          onClick={onClose}
        >
          <Icon name="x" />
        </button>
      </div>
      <div className="drawer-body">
        {!board ? (
          <p className="drawer-empty">Loading live board…</p>
        ) : kind === "agents" ? (
          arenas.length ? (
            arenas.map((arena) => {
              const quiet = isIdle(arena, board, now);
              return (
                <a
                  key={arena.id}
                  className={`drawer-agent ${arena.budget.stopped ? "wait" : quiet ? "idle" : "run"}`}
                  href={`/console/arena/${encodeURIComponent(arena.id)}?tab=live`}
                >
                  <span className="drawer-agent-head">
                    <Icon name="agent" />
                    <b>{arena.agents.map((agent) => agent.name).join(", ")}</b>
                    <span className="drawer-state">
                      {arena.budget.stopped
                        ? "Needs you"
                        : arena.agents.every((agent) => agent.paused)
                          ? "Paused"
                          : quiet
                            ? `Idle > ${board.idle_minutes} min`
                            : "Working"}
                    </span>
                  </span>
                  <span className="drawer-now">
                    {arena.last_action
                      ? `${arena.last_action.name} · ${arena.last_action.status}`
                      : "No action yet"}
                  </span>
                  <span className="drawer-meta">
                    <span>{arena.name}</span>
                    <span>
                      {arena.last_action ? ago(arena.last_action.at, now) : "—"}
                    </span>
                    <span>
                      {arena.budget.remaining == null
                        ? "Budget unavailable"
                        : `${arena.budget.remaining} of ${arena.budget.cap} left`}
                    </span>
                  </span>
                </a>
              );
            })
          ) : (
            <p className="drawer-empty">
              No agent is connected. Create a scoped key on an arena&apos;s
              Agent access page.
            </p>
          )
        ) : attention.length ? (
          attention.map((item) => {
            const href = item.arena_id
              ? `/console/arena/${encodeURIComponent(item.arena_id)}?tab=live`
              : item.evaluation_id
                ? `/console/evaluations/${encodeURIComponent(item.evaluation_id)}`
                : "/console/board";
            return (
              <a
                key={item.key}
                className={`drawer-item kind-${item.kind}`}
                href={href}
              >
                <span className="label">
                  {KIND_LABEL[item.kind] || item.kind}
                </span>
                <b>{item.text}</b>
                <small>
                  {item.arena_name || item.arena_id || "Platform"} ·{" "}
                  {ago(item.at, now)}
                </small>
              </a>
            );
          })
        ) : (
          <p className="drawer-empty">
            Failed arenas, verdicts, budget exhaustion, stops and finished
            trials appear here.
          </p>
        )}
      </div>
      <div className="drawer-foot">
        <span>{kind === "agents" ? "Pushed live" : "Newest first"}</span>
        <a href="/console/board">Open the agents board</a>
      </div>
    </aside>
  );
}
