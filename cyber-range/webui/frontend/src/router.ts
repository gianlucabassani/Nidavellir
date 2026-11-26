/**
 * UX-02: minimal client-side router (no library, so ADR-0017 stands).
 * In-console navigation is pushState plus a synthetic popstate, which every
 * view already listens to. Each history entry remembers its scroll position
 * and where it was opened from, so back/forward restore the page and the
 * breadcrumb names the real origin.
 */
export type Origin = { href: string; label: string };
type EntryState = { scrollY?: number; from?: Origin } | null;

function current(): string {
  return window.location.pathname + window.location.search;
}

/** Human label for a console URL, used to name a breadcrumb's origin. */
export function routeLabel(url: URL): string {
  const path = url.pathname;
  const params = url.searchParams;
  if (path === "/console") {
    const workspace = params.get("workspace");
    return workspace === "range"
      ? "Cyber Range"
      : workspace === "benchmark"
        ? "Benchmark"
        : "Research";
  }
  if (path.startsWith("/console/arena/")) return "Arena";
  if (path.startsWith("/console/evaluations/") && path.endsWith("/compare"))
    return "Trial comparison";
  if (path.startsWith("/console/suites/")) return "Suite history";
  if (
    path.startsWith("/console/evaluations/") &&
    path !== "/console/evaluations/new"
  )
    return "Evaluation";
  const labels: Record<string, string> = {
    "/console/arenas": "All arenas",
    "/console/arenas/new": "New arena",
    "/console/arenas/custom": "New arena",
    "/console/evaluations": "All evaluations",
    "/console/evaluations/new": "New comparison",
    "/console/benchmark/registry": "Registry",
    "/console/scenarios": "Scenario library",
    "/console/scenarios/import": "Scenario import",
    "/console/research/new": "New research",
    "/console/research/review": "Source review",
    "/console/research/campaigns": "Campaigns",
    "/console/activity": "Activity",
    "/console/findings": "Findings",
    "/console/operations": "Operations",
    "/console/library/agents": "Agents",
    "/console/library/targets": "Targets",
    "/console/settings": "Settings",
    "/console/profile": "Profile",
  };
  if (path.startsWith("/console/research/review/")) return "Source review";
  if (path.startsWith("/console/research/campaigns/")) return "Campaign";
  return labels[path] || "Console";
}

export function isConsoleUrl(url: URL): boolean {
  return (
    url.origin === window.location.origin &&
    (url.pathname === "/console" || url.pathname.startsWith("/console/"))
  );
}

function notify() {
  window.dispatchEvent(new PopStateEvent("popstate", { state: history.state }));
}

export function navigate(href: string, options: { replace?: boolean } = {}) {
  const next = new URL(href, window.location.href);
  if (!isConsoleUrl(next)) {
    window.location.assign(next.href);
    return;
  }
  const here = new URL(window.location.href);
  const state = (history.state as EntryState) || {};
  // Remember where this entry was scrolled before leaving it.
  history.replaceState({ ...state, scrollY: window.scrollY }, "");
  const samePage = next.pathname === here.pathname;
  const from: Origin | undefined =
    samePage || options.replace
      ? state.from
      : { href: current(), label: routeLabel(here) };
  const entry: EntryState = { from, scrollY: 0 };
  if (options.replace) history.replaceState(entry, "", next);
  else history.pushState(entry, "", next);
  notify();
  if (!samePage) window.scrollTo(0, 0);
}

/** Origin of the current entry, or the given default. */
export function origin(fallback: Origin): Origin {
  return (history.state as EntryState)?.from || fallback;
}

/** Go back when the origin is the previous entry; otherwise navigate to it. */
export function goBack(target: Origin) {
  if ((history.state as EntryState)?.from?.href === target.href) history.back();
  else navigate(target.href);
}

let installed = false;
/** Intercept in-console link clicks and restore scroll on back/forward. */
export function installRouter() {
  if (installed) return;
  installed = true;
  history.scrollRestoration = "manual";
  document.addEventListener("click", (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    const anchor = (event.target as Element | null)?.closest?.(
      "a[href]",
    ) as HTMLAnchorElement | null;
    if (!anchor || anchor.target || anchor.hasAttribute("download")) return;
    const next = new URL(anchor.href);
    if (!isConsoleUrl(next)) return;
    event.preventDefault();
    anchor.closest("details")?.removeAttribute("open");
    navigate(next.href);
  });
  window.addEventListener("popstate", (event) => {
    if (!event.isTrusted) return;
    const y = (event.state as EntryState)?.scrollY ?? 0;
    // Views re-render on this same event; restore once their content is back.
    let tries = 0;
    const restore = () => {
      window.scrollTo(0, y);
      if (Math.abs(window.scrollY - y) > 2 && tries++ < 20)
        window.setTimeout(restore, 50);
    };
    window.setTimeout(restore, 0);
  });
}
