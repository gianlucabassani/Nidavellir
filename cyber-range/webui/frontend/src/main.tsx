import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./design/fonts.css";
import "./design/tokens.css";
import "./design/base.css";
import type { Workspace, Theme } from "./types";
import { ErrorBoundary, StaleBanner } from "./ui";
import { Research } from "./research";
import { NewResearch } from "./research/new";
import { Campaign, Campaigns } from "./research/campaigns";
import { SourceReviewSessions } from "./research/source-review";
import { SourceReviewSession } from "./research/source-review-session";
import { Benchmark } from "./benchmark";
import { BenchmarkRegistry } from "./benchmark/registry";
import { NewComparison } from "./benchmark/new";
import { EvaluationDetail } from "./benchmark/detail";
import { TrialCompare } from "./benchmark/compare";
import { CommandPalette } from "./shared/palette";
import { SuiteHistoryPage } from "./benchmark/history";
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
import { AllArenas, AllEvaluations } from "./shared/lists";
import { AgentsBoard } from "./shared/board";
import { FindingsPage } from "./research/findings";
import { installRouter } from "./router";
import { Shell } from "./shell/Shell";

installRouter();

function workspaceFromUrl(): Workspace {
  const value = new URLSearchParams(window.location.search).get("workspace");
  return value === "benchmark" || value === "range" ? value : "research";
}

// UX-08: an explicit choice wins; otherwise follow the system preference.
function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem("nidavellir-theme");
    return value === "night" || value === "day" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "night"
    : "day";
}

function readTheme(): Theme {
  return storedTheme() || systemTheme();
}

function App() {
  const [workspace, setWorkspace] = useState<Workspace>(workspaceFromUrl);
  const [, setRouteVersion] = useState(0);
  const [theme, setThemeState] = useState<Theme>(readTheme);
  const heading = useRef<HTMLElement>(null);
  const username =
    document.getElementById("root")?.dataset.username || "Operator";
  const arenaId = window.location.pathname.startsWith("/console/arena/")
    ? decodeURIComponent(
        window.location.pathname.slice("/console/arena/".length),
      )
    : null;
  const newComparison = window.location.pathname === "/console/evaluations/new";
  const allEvaluations = window.location.pathname === "/console/evaluations";
  const allArenas = window.location.pathname === "/console/arenas";
  const benchmarkRegistry =
    window.location.pathname === "/console/benchmark/registry";
  const activity = window.location.pathname === "/console/activity";
  const boardPage = window.location.pathname === "/console/board";
  const findingsPage = window.location.pathname === "/console/findings";
  const agentsLibrary = window.location.pathname === "/console/library/agents";
  const targetsLibrary =
    window.location.pathname === "/console/library/targets";
  const settingsPage = window.location.pathname === "/console/settings";
  const profilePage = window.location.pathname === "/console/profile";
  const newArena = ["/console/arenas/new", "/console/arenas/custom"].includes(
    window.location.pathname,
  );
  const scenarioLibrary = window.location.pathname === "/console/scenarios";
  const scenarioImport =
    window.location.pathname === "/console/scenarios/import";
  const newResearch = window.location.pathname === "/console/research/new";
  const sourceReviews = window.location.pathname === "/console/research/review";
  const sourceReviewId = window.location.pathname.startsWith(
    "/console/research/review/",
  )
    ? decodeURIComponent(
        window.location.pathname.slice("/console/research/review/".length),
      )
    : null;
  const campaigns = window.location.pathname === "/console/research/campaigns";
  const campaignId = window.location.pathname.startsWith(
    "/console/research/campaigns/",
  )
    ? decodeURIComponent(
        window.location.pathname.slice("/console/research/campaigns/".length),
      )
    : null;
  const evaluationPath =
    !newComparison &&
    window.location.pathname.startsWith("/console/evaluations/")
      ? window.location.pathname.slice("/console/evaluations/".length)
      : null;
  const compareId = evaluationPath?.endsWith("/compare")
    ? decodeURIComponent(evaluationPath.slice(0, -"/compare".length))
    : null;
  const evaluationId =
    evaluationPath && !compareId ? decodeURIComponent(evaluationPath) : null;
  const suiteMatch = window.location.pathname.match(
    /^\/console\/suites\/([^/]+)\/history$/,
  );
  const suiteHistoryId = suiteMatch ? decodeURIComponent(suiteMatch[1]) : null;
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  useEffect(() => {
    // Follow system changes until the operator picks a theme explicitly.
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return;
    const follow = () => {
      if (!storedTheme()) setThemeState(systemTheme());
    };
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);
  function setTheme(next: Theme) {
    setThemeState(next);
    try {
      localStorage.setItem("nidavellir-theme", next);
    } catch {
      /* storage may be unavailable */
    }
  }
  useEffect(() => {
    let lastPath = window.location.pathname;
    const onPop = () => {
      setWorkspace(workspaceFromUrl());
      setRouteVersion((value) => value + 1);
      if (window.location.pathname !== lastPath)
        window.setTimeout(
          () =>
            heading.current
              ?.querySelector("h1")
              ?.focus({ preventScroll: true }),
          0,
        );
      lastPath = window.location.pathname;
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return (
    <Shell
      username={username}
      theme={theme}
      setTheme={setTheme}
      mainRef={heading}
    >
      <CommandPalette />
      <StaleBanner />
      <ErrorBoundary
        key={
          // Arena tabs live in ?tab= and keep the workspace mounted.
          arenaId
            ? window.location.pathname
            : window.location.pathname + window.location.search
        }
        label="This view"
      >
        {arenaId ? (
          <ArenaWorkspace key={arenaId} id={arenaId} />
        ) : boardPage ? (
          <AgentsBoard />
        ) : findingsPage ? (
          <FindingsPage />
        ) : allArenas ? (
          <AllArenas />
        ) : allEvaluations ? (
          <AllEvaluations />
        ) : newResearch ? (
          <NewResearch />
        ) : sourceReviews ? (
          <SourceReviewSessions />
        ) : sourceReviewId ? (
          <SourceReviewSession key={sourceReviewId} id={sourceReviewId} />
        ) : campaigns ? (
          <Campaigns />
        ) : campaignId ? (
          <Campaign key={campaignId} id={campaignId} />
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
        ) : compareId ? (
          <TrialCompare key={window.location.search} evaluationId={compareId} />
        ) : suiteHistoryId ? (
          <SuiteHistoryPage suiteId={suiteHistoryId} />
        ) : evaluationId ? (
          <EvaluationDetail id={evaluationId} />
        ) : workspace === "research" ? (
          <Research />
        ) : workspace === "benchmark" ? (
          <Benchmark />
        ) : (
          <Range />
        )}
      </ErrorBoundary>
      <ResearchAssistant arenaId={arenaId} />
    </Shell>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
