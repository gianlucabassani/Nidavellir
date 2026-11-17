(() => {
  "use strict";
  const routes = new Set(["dashboard", "arena", "import", "poc", "finding", "archive", "settings", "benchmark", "benchmark-new", "comparison", "range", "range-live"]);
  const $ = (selector) => document.querySelector(selector);
  let pendingRun = null;
  let completedRun = false;
  let rangeStopped = false;
  let focusAfterNavigation = false;

  function selectedMode() {
    return new URL(window.location.href).searchParams.get("concept") === "canvas" ? "canvas" : "command";
  }

  function selectedRoute() {
    const route = window.location.hash.slice(1);
    return routes.has(route) ? route : "dashboard";
  }

  function setMode(mode) {
    const chosen = mode === "canvas" ? "canvas" : "command";
    document.body.classList.toggle("mode-command", chosen === "command");
    document.body.classList.toggle("mode-canvas", chosen === "canvas");
    document.querySelectorAll("[data-mode]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.mode === chosen));
    });
    const url = new URL(window.location.href);
    url.searchParams.set("concept", chosen);
    history.replaceState(null, "", url);
    render();
  }

  function render() {
    const mode = selectedMode();
    const route = selectedRoute();
    const onDashboard = route === "dashboard";
    const onArena = route === "arena";
    const onSettings = route === "settings";
    const onPrimary = ["benchmark", "benchmark-new", "comparison", "range", "range-live"].includes(route);
    $(".command-app").hidden = !onDashboard || mode !== "command";
    $(".canvas-app").hidden = !onDashboard || mode !== "canvas";
    $(".arena-app").hidden = !onArena;
    $(".settings-screen").hidden = !onSettings;
    document.querySelectorAll(".primary-workspace").forEach((screen) => {
      screen.hidden = screen.dataset.screen !== route;
    });
    $(".workflow").hidden = onDashboard || onArena || onSettings || onPrimary;
    const researchLink = $('.realm-link[data-route="dashboard"]');
    document.querySelectorAll(".realm-link").forEach((link) => {
      const active = link === researchLink
        ? ["dashboard", "arena", "import", "poc", "finding", "archive"].includes(route)
        : link.dataset.route === (route === "benchmark-new" || route === "comparison" ? "benchmark" : route === "range-live" ? "range" : route);
      link.classList.toggle("current", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.querySelectorAll("[data-stage]").forEach((panel) => {
      panel.hidden = panel.dataset.stage !== route;
    });
    document.querySelectorAll(".workflow-steps a").forEach((link) => {
      const active = link.dataset.route === route;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "step");
      else link.removeAttribute("aria-current");
    });
    const state = {
      dashboard: ["DRAFT", "Preparing", "50 available"],
      arena: ["ACTIVE · DEMO", "Active · mock state", completedRun ? "47 available" : "48 available"],
      import: ["DRAFT", "Preparing", "50 available"],
      poc: ["ACTIVE · DEMO", "Active · mock state", completedRun ? "47 available" : "48 available"],
      finding: ["ACTIVE · DEMO", "Active · mock state", completedRun ? "47 available" : "48 available"],
      archive: ["ARCHIVED", "Destroyed · record retained", completedRun ? "47 available" : "48 available"],
      settings: ["DRAFT", "Preparing", "50 available"],
      benchmark: ["DRAFT", "Preparing", "50 available"],
      "benchmark-new": ["DRAFT", "Preparing", "50 available"],
      comparison: ["DRAFT", "Preparing", "50 available"],
      range: ["DRAFT", "Preparing", "50 available"],
      "range-live": ["DRAFT", "Preparing", "50 available"]
    }[route];
    $("#workflow-state").textContent = state[0];
    $("#workflow-arena").textContent = state[1];
    $("#workflow-budget").textContent = state[2];
    const activeMain = onDashboard
      ? (mode === "command" ? $(".dashboard-command") : $(".dashboard-canvas"))
      : onArena ? $(".arena-main") : onSettings ? $(".settings-main") : onPrimary ? document.querySelector('[data-screen="' + route + '"] .primary-main') : $(".workflow-wrap");
    document.querySelectorAll("#content").forEach((element) => element.removeAttribute("id"));
    activeMain.id = "content";
    if (focusAfterNavigation) {
      const heading = onDashboard || onArena || onSettings || onPrimary ? activeMain.querySelector("h1") : document.querySelector('[data-stage="' + route + '"] h2');
      if (heading) {
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
        window.scrollTo({ top: 0, behavior: "instant" });
      }
      focusAfterNavigation = false;
    }
  }

  function navigate(route) {
    if (!routes.has(route)) return;
    focusAfterNavigation = true;
    if (window.location.hash === "#" + route) render();
    else window.location.hash = route;
  }

  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode)));
  document.querySelectorAll("[data-route]").forEach((element) => {
    element.addEventListener("click", (event) => {
      event.preventDefault();
      $("#profile-menu").open = false;
      navigate(element.dataset.route);
    });
  });
  document.addEventListener("click", (event) => {
    if (!$("#profile-menu").contains(event.target)) $("#profile-menu").open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") $("#profile-menu").open = false;
  });
  window.addEventListener("hashchange", render);

  $("#run-demo").addEventListener("click", () => {
    if (pendingRun) return;
    $("#run-demo").disabled = true;
    $("#cancel-run").disabled = false;
    $("#run-output").hidden = true;
    $("#run-status").textContent = "Demo job running…";
    pendingRun = window.setTimeout(() => {
      pendingRun = null;
      completedRun = true;
      $("#run-demo").disabled = false;
      $("#cancel-run").disabled = true;
      $("#run-output").hidden = false;
      $("#new-artifact").checked = true;
      $("#run-status").textContent = "Job complete · output and cleanup recorded.";
      render();
    }, 850);
  });
  $("#cancel-run").addEventListener("click", () => {
    if (!pendingRun) return;
    window.clearTimeout(pendingRun);
    pendingRun = null;
    $("#run-demo").disabled = false;
    $("#cancel-run").disabled = true;
    $("#run-status").textContent = "Demo job cancelled; no artifact produced.";
  });
  $("#new-finding-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const title = $("#new-finding-title").value.trim();
    const effect = $("#new-finding-effect").value.trim();
    if (!title || !effect) {
      $("#finding-message").textContent = "Enter a title and observed effect.";
      return;
    }
    $("#saved-finding").textContent = title;
    $("#finding-message").textContent = "Finding recorded in this mockup; no independent verdict was run.";
    navigate("archive");
  });
  $("#benchmark-form").addEventListener("submit", (event) => {
    event.preventDefault();
    navigate("comparison");
  });
  $("#stop-range").addEventListener("click", () => {
    if (!rangeStopped) $("#range-confirm").showModal();
  });
  $("#range-confirm").addEventListener("close", () => {
    if ($("#range-confirm").returnValue !== "confirm") return;
    rangeStopped = true;
    $("#range-state").textContent = "Stopped · demo";
    $("#stop-range").disabled = true;
    $("#stop-range").textContent = "Arena stopped";
  });
  setMode(selectedMode());
})();
