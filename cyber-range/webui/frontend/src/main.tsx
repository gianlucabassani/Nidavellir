import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import type { Workspace, Theme } from "./types";
import { Rune } from "./ui";
import { Research } from "./research";
import { NewResearch } from "./research/new";
import { Benchmark } from "./benchmark";
import { BenchmarkRegistry } from "./benchmark/registry";
import { NewComparison } from "./benchmark/new";
import { EvaluationDetail } from "./benchmark/detail";
import { Range } from "./range";
import { NewArena } from "./range/new";
import { ScenarioLibrary } from "./range/library";
import { ScenarioImport } from "./range/import";
import { ArenaWorkspace } from "./arena";
import { Activity } from "./activity";
import { AgentsLibrary } from "./shared/agents";
import { TargetsLibrary } from "./shared/targets";
import { Profile } from "./shared/profile";
import { Settings } from "./shared/settings";
import { ResearchAssistant } from "./shared/assistant";

function workspaceFromUrl(): Workspace {
  const value = new URLSearchParams(window.location.search).get("workspace");
  return value === "benchmark" || value === "range" ? value : "research";
}

function readTheme(): Theme {
  try {
    return localStorage.getItem("nidavellir-theme") === "night"
      ? "night"
      : "day";
  } catch {
    return "day";
  }
}

function App() {
  const [workspace, setWorkspace] = useState<Workspace>(workspaceFromUrl);
  const [, setRouteVersion] = useState(0);
  const [theme, setTheme] = useState<Theme>(readTheme);
  const heading = useRef<HTMLElement>(null);
  const username =
    document.getElementById("root")?.dataset.username || "Operator";
  const arenaId = window.location.pathname.startsWith("/console/arena/")
    ? decodeURIComponent(
        window.location.pathname.slice("/console/arena/".length),
      )
    : null;
  const newComparison = window.location.pathname === "/console/evaluations/new";
  const benchmarkRegistry =
    window.location.pathname === "/console/benchmark/registry";
  const activity = window.location.pathname === "/console/activity";
  const agentsLibrary = window.location.pathname === "/console/library/agents";
  const targetsLibrary =
    window.location.pathname === "/console/library/targets";
  const settingsPage = window.location.pathname === "/console/settings";
  const profilePage = window.location.pathname === "/console/profile";
  const newArena = window.location.pathname === "/console/arenas/new";
  const scenarioLibrary = window.location.pathname === "/console/scenarios";
  const scenarioImport =
    window.location.pathname === "/console/scenarios/import";
  const newResearch = window.location.pathname === "/console/research/new";
  const evaluationId =
    !newComparison &&
    window.location.pathname.startsWith("/console/evaluations/")
      ? decodeURIComponent(
          window.location.pathname.slice("/console/evaluations/".length),
        )
      : null;
  const activeWorkspace: Workspace | null =
    activity || agentsLibrary || targetsLibrary || settingsPage || profilePage
      ? null
      : evaluationId || newComparison || benchmarkRegistry
        ? "benchmark"
        : newResearch
          ? "research"
          : newArena || scenarioLibrary || scenarioImport
            ? "range"
            : arenaId
              ? "research"
              : workspace;
  const evidenceActive =
    activity &&
    new URLSearchParams(window.location.search).get("section") === "evidence";
  const sharedTools = [
    {
      label: "Targets",
      href: "/console/library/targets",
      active: targetsLibrary,
    },
    { label: "Agents", href: "/console/library/agents", active: agentsLibrary },
    {
      label: "Evidence",
      href: "/console/activity?section=evidence",
      active: evidenceActive,
    },
    {
      label: "Activity",
      href: "/console/activity?section=audit",
      active: activity && !evidenceActive,
    },
  ];
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("nidavellir-theme", theme);
    } catch {
      /* storage may be unavailable */
    }
  }, [theme]);
  useEffect(() => {
    const onPop = () => {
      setWorkspace(workspaceFromUrl());
      setRouteVersion((value) => value + 1);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  function navigate(next: Workspace) {
    const url = new URL(window.location.href);
    url.pathname = "/console";
    url.searchParams.set("workspace", next);
    window.history.pushState(null, "", url);
    setWorkspace(next);
    setRouteVersion((value) => value + 1);
    window.setTimeout(() => heading.current?.querySelector("h1")?.focus(), 0);
  }
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="command-bar">
          <a
            className="brand"
            href="/console?workspace=research"
            onClick={(event) => {
              event.preventDefault();
              navigate("research");
            }}
          >
            <span className="brand-mark">
              <img src="/static/anvil_emblem.png" alt="" />
            </span>
            <span>
              NIDAVELLIR<small>FORGE</small>
            </span>
          </a>
          <nav className="workspace-nav" aria-label="Primary workspaces">
            {(["research", "benchmark", "range"] as const).map((item) => (
              <button
                key={item}
                type="button"
                className={activeWorkspace === item ? "active" : ""}
                onClick={() => navigate(item)}
                aria-current={activeWorkspace === item ? "page" : undefined}
                aria-label={
                  item === "range"
                    ? "Cyber Range"
                    : item[0].toUpperCase() + item.slice(1)
                }
                title={
                  item === "range"
                    ? "Launch and observe isolated arenas"
                    : item === "benchmark"
                      ? "Compare pinned agent builds"
                      : "Investigate targets and retain proof"
                }
              >
                <Rune kind={item} />
                <span>
                  {item === "range"
                    ? "Cyber Range"
                    : item[0].toUpperCase() + item.slice(1)}
                </span>
              </button>
            ))}
          </nav>
          <div className="header-actions">
            <details className="tools-menu">
              <summary>
                Library <span aria-hidden="true">⌄</span>
              </summary>
              <div>
                {sharedTools.map((tool) => (
                  <a
                    key={tool.label}
                    href={tool.href}
                    aria-current={tool.active ? "page" : undefined}
                  >
                    {tool.label}
                  </a>
                ))}
              </div>
            </details>
            <button
              className="theme-toggle"
              type="button"
              aria-label={`Switch to ${theme === "day" ? "night" : "day"} theme`}
              onClick={() => setTheme(theme === "day" ? "night" : "day")}
            >
              {theme === "day" ? "◐" : "☼"}
              <span>{theme === "day" ? "Night" : "Day"}</span>
            </button>
            <details className="profile">
              <summary>
                <span className="avatar">
                  {username.slice(0, 2).toUpperCase()}
                </span>
                <span className="profile-name">
                  {username}
                  <small>Operator</small>
                </span>
                <span aria-hidden="true">⌄</span>
              </summary>
              <div className="profile-menu">
                <strong>Account</strong>
                <a href="/console/profile">Profile</a>
                <a href="/console/settings">Platform settings</a>
                <form method="post" action="/logout">
                  <input
                    type="hidden"
                    name="csrf_token"
                    value={
                      document.querySelector<HTMLMetaElement>(
                        'meta[name="csrf-token"]',
                      )?.content || ""
                    }
                  />
                  <button type="submit">Log out</button>
                </form>
              </div>
            </details>
          </div>
        </div>
      </header>
      <main
        className="workspace-main"
        id="main"
        ref={heading}
        onClick={(event) => {
          if (
            !arenaId ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
          )
            return;
          const anchor = (
            event.target as HTMLElement
          ).closest<HTMLAnchorElement>("a[href]");
          if (!anchor || anchor.target || anchor.hasAttribute("download"))
            return;
          const next = new URL(anchor.href);
          if (
            next.origin !== window.location.origin ||
            next.pathname !== window.location.pathname
          )
            return;
          event.preventDefault();
          window.history.pushState(null, "", next);
          window.dispatchEvent(new PopStateEvent("popstate"));
        }}
      >
        {arenaId ? (
          <ArenaWorkspace key={arenaId} id={arenaId} />
        ) : newResearch ? (
          <NewResearch />
        ) : newArena ? (
          <NewArena />
        ) : scenarioLibrary ? (
          <ScenarioLibrary />
        ) : scenarioImport ? (
          <ScenarioImport />
        ) : newComparison ? (
          <NewComparison />
        ) : benchmarkRegistry ? (
          <BenchmarkRegistry />
        ) : activity ? (
          <Activity />
        ) : agentsLibrary ? (
          <AgentsLibrary />
        ) : targetsLibrary ? (
          <TargetsLibrary />
        ) : settingsPage ? (
          <Settings />
        ) : profilePage ? (
          <Profile username={username} theme={theme} setTheme={setTheme} />
        ) : evaluationId ? (
          <EvaluationDetail id={evaluationId} />
        ) : workspace === "research" ? (
          <Research />
        ) : workspace === "benchmark" ? (
          <Benchmark />
        ) : (
          <Range />
        )}
      </main>
      <ResearchAssistant arenaId={arenaId} />
      <footer className="site-footer">
        <span>NIDAVELLIR FORGE / OPERATOR CONSOLE</span>
        <a href="/">Legacy console</a>
      </footer>
    </>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
