import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { getJson } from "../api";
import { navigate } from "../router";
import "./palette.css";

// UX-13 (FR-18): command palette (Ctrl/Cmd-K). Navigation, the primary actions
// the current view registers, and global search (text or digest prefix).
// Actions never bypass a view's own confirmation: they call the same handler
// the view's button calls.

export type PaletteAction = {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
};

const registry = new Map<string, PaletteAction[]>();
const listeners = new Set<() => void>();
let snapshot: PaletteAction[] = [];

function publish() {
  snapshot = [...registry.values()].flat();
  listeners.forEach((listener) => listener());
}

/** Register the current view's primary actions while it is mounted. */
export function usePaletteActions(owner: string, actions: PaletteAction[]) {
  const ref = useRef(actions);
  ref.current = actions;
  const signature = actions.map((action) => action.id + action.label).join("|");
  useEffect(() => {
    registry.set(
      owner,
      ref.current.map((action) => ({
        ...action,
        // Always the view's latest handler, not the one captured at mount.
        run: () => ref.current.find((item) => item.id === action.id)?.run(),
      })),
    );
    publish();
    return () => {
      registry.delete(owner);
      publish();
    };
  }, [owner, signature]);
}

function useViewActions() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => snapshot,
  );
}

const NAVIGATION: { label: string; href: string }[] = [
  { label: "Research", href: "/console?workspace=research" },
  { label: "Benchmark", href: "/console?workspace=benchmark" },
  { label: "Cyber Range", href: "/console?workspace=range" },
  { label: "Agents board", href: "/console/board" },
  { label: "All arenas", href: "/console/arenas" },
  { label: "New arena", href: "/console/arenas/new" },
  { label: "All evaluations", href: "/console/evaluations" },
  { label: "New comparison", href: "/console/evaluations/new" },
  { label: "Benchmark registry", href: "/console/benchmark/registry" },
  { label: "Scenario library", href: "/console/scenarios" },
  { label: "New research", href: "/console/research/new" },
  { label: "Campaigns", href: "/console/research/campaigns" },
  { label: "Evidence", href: "/console/activity?section=evidence" },
  { label: "Activity", href: "/console/activity?section=audit" },
  { label: "Targets", href: "/console/library/targets" },
  { label: "Agents", href: "/console/library/agents" },
  { label: "Settings", href: "/console/settings" },
];

type SearchResult = {
  mode: string;
  arenas: { id: string; scenario: string | null; status: string | null }[];
  findings: { arena_id: string; finding_id: string | null; title: string }[];
  transactions: {
    arena_id: string;
    digest: string | null;
    method: string | null;
    path: string;
    status: number | null;
  }[];
  spans: {
    arena_id: string | null;
    span_id: string;
    name: string;
    status: string;
  }[];
};

type Item = {
  key: string;
  group: string;
  label: string;
  hint?: string;
  run: () => void;
};

function arenaHref(id: string, params: Record<string, string> = {}) {
  const query = new URLSearchParams(params).toString();
  return `/console/arena/${encodeURIComponent(id)}${query ? `?${query}` : ""}`;
}

function matches(label: string, query: string) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const text = label.toLowerCase();
  return words.every((word) => text.includes(word));
}

export function CommandPalette() {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [results, setResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const viewActions = useViewActions();

  // Opening always starts fresh; closing acts on the element at once, so a
  // close and a reopen in the same render can never leave a stale dialog.
  const openRef = useRef(false);
  const show = () => {
    const element = dialog.current;
    setQuery("");
    setResults(null);
    setActive(0);
    openRef.current = true;
    setOpen(true);
    if (element && !element.open) element.showModal();
    input.current?.focus();
  };
  const hide = () => {
    openRef.current = false;
    setOpen(false);
    if (dialog.current?.open) dialog.current.close();
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (openRef.current) hide();
        else show();
      }
    };
    const onOpen = () => show();
    window.addEventListener("keydown", onKey);
    window.addEventListener("nv:palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("nv:palette", onOpen);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const text = query.trim();
    if (!open || text.length < 2) {
      setResults(null);
      setSearchError("");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearching(true);
      getJson<SearchResult>(
        `/api/console/search?${new URLSearchParams({ q: text })}`,
        controller.signal,
      )
        .then((data) => {
          setResults(data);
          setSearchError("");
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted)
            setSearchError(
              reason instanceof Error ? reason.message : "Search failed",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 200);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, open]);

  const close = hide;
  const go = (href: string) => () => {
    close();
    navigate(href);
  };

  const items = useMemo<Item[]>(() => {
    const text = query.trim();
    const list: Item[] = [];
    for (const action of viewActions)
      if (!text || matches(action.label, text))
        list.push({
          key: `action:${action.id}`,
          group: "This page",
          label: action.label,
          hint: action.hint,
          run: () => {
            close();
            action.run();
          },
        });
    for (const entry of NAVIGATION)
      if (!text || matches(entry.label, text))
        list.push({
          key: `nav:${entry.href}`,
          group: "Go to",
          label: entry.label,
          run: go(entry.href),
        });
    if (results) {
      for (const arena of results.arenas)
        list.push({
          key: `arena:${arena.id}`,
          group: "Arenas",
          label: arena.scenario ? `${arena.scenario} · ${arena.id}` : arena.id,
          hint: arena.status || undefined,
          run: go(arenaHref(arena.id)),
        });
      for (const finding of results.findings)
        list.push({
          key: `finding:${finding.arena_id}:${finding.finding_id}`,
          group: "Findings",
          label: finding.title || finding.finding_id || "Finding",
          hint: finding.arena_id,
          run: go(arenaHref(finding.arena_id, { tab: "findings" })),
        });
      for (const tx of results.transactions)
        list.push({
          key: `tx:${tx.arena_id}:${tx.digest}`,
          group: "HTTP transactions",
          label: `${tx.method || ""} ${tx.path}`.trim(),
          hint: `${tx.status ?? ""} ${tx.digest?.slice(0, 19) || ""}`.trim(),
          run: go(
            arenaHref(tx.arena_id, {
              tab: "http",
              pane: "detail",
              ...(tx.digest ? { digest: tx.digest } : {}),
            }),
          ),
        });
      for (const span of results.spans)
        if (span.arena_id)
          list.push({
            key: `span:${span.span_id}`,
            group: "Spans",
            label: span.name,
            hint: `${span.status} · ${span.arena_id}`,
            run: go(
              arenaHref(span.arena_id, { tab: "live", span: span.span_id }),
            ),
          });
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, results, viewActions]);

  useEffect(() => setActive(0), [query, results]);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(items.length - 1, index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter" && items[active]) {
      event.preventDefault();
      items[active].run();
    }
  }

  useEffect(() => {
    document
      .getElementById(`palette-item-${active}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  let lastGroup = "";
  return (
    <dialog
      ref={dialog}
      className="palette"
      aria-label="Command palette"
      onClose={() => {
        openRef.current = false;
        setOpen(false);
      }}
      onClick={(event) => {
        if (event.target === dialog.current) close();
      }}
    >
      <input
        ref={input}
        className="palette-input"
        role="combobox"
        aria-expanded="true"
        aria-controls="palette-list"
        aria-activedescendant={
          items[active] ? `palette-item-${active}` : undefined
        }
        aria-label="Search or jump to"
        placeholder="Jump to, run an action, or search text / sha256:digest…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKeyDown}
        autoComplete="off"
        spellCheck={false}
      />
      <div className="palette-status" role="status" aria-live="polite">
        {searching
          ? "Searching…"
          : searchError
            ? searchError
            : results
              ? results.mode === "digest"
                ? "Digest prefix results"
                : "Text results"
              : query.trim().length === 1
                ? "Type 2 characters to search"
                : ""}
      </div>
      <ul id="palette-list" role="listbox" className="palette-list">
        {items.map((item, index) => {
          const header = item.group !== lastGroup;
          lastGroup = item.group;
          return (
            <li key={item.key} role="presentation">
              {header && <div className="palette-group">{item.group}</div>}
              <div
                id={`palette-item-${index}`}
                role="option"
                aria-selected={index === active}
                className={`palette-item${index === active ? " active" : ""}`}
                onMouseMove={() => setActive(index)}
                onClick={item.run}
              >
                <span>{item.label}</span>
                {item.hint && <small>{item.hint}</small>}
              </div>
            </li>
          );
        })}
        {!items.length && (
          <li className="palette-empty">
            {query.trim().length >= 2 && !searching
              ? "No matches."
              : "No commands."}
          </li>
        )}
      </ul>
      <footer className="palette-foot">
        ↑↓ move · Enter open · Esc close · Ctrl/⌘ K toggle
      </footer>
    </dialog>
  );
}

export function PaletteButton() {
  const mac = /Mac|iPhone|iPad/.test(navigator.platform);
  return (
    <button
      type="button"
      className="palette-trigger"
      onClick={() => window.dispatchEvent(new Event("nv:palette"))}
      aria-keyshortcuts={mac ? "Meta+K" : "Control+K"}
    >
      Search <kbd>{mac ? "⌘K" : "Ctrl K"}</kbd>
    </button>
  );
}
