(() => {
  "use strict";
  const views = new Set(["import", "poc", "finding", "archive"]);
  const byId = (id) => document.getElementById(id);
  const note = byId("poc-message");
  let pending = null;
  let hasArtifact = false;

  function setConcept(value) {
    const name = value === "b" ? "b" : "a";
    document.body.classList.toggle("concept-a", name === "a");
    document.body.classList.toggle("concept-b", name === "b");
    byId("choose-a").setAttribute("aria-pressed", String(name === "a"));
    byId("choose-b").setAttribute("aria-pressed", String(name === "b"));
    const url = new URL(window.location.href);
    url.searchParams.set("concept", name);
    history.replaceState(null, "", url);
  }

  function renderView(focus = false) {
    const requested = window.location.hash.slice(1);
    const current = views.has(requested) ? requested : "import";
    document.querySelectorAll(".view").forEach((view) => {
      view.hidden = view.id !== current;
    });
    document.querySelectorAll(".step").forEach((step) => {
      const active = step.dataset.go === current;
      step.classList.toggle("active", active);
      if (active) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    });
    const states = {
      import: ["Bozza · non avviata", "In preparazione", "50 disponibili", "Nessuna"],
      poc: ["Sessione dimostrativa", "Attiva · simulata", hasArtifact ? "49 disponibili" : "50 disponibili", hasArtifact ? "PoC dimostrativo" : "Nessuna"],
      finding: ["Sessione dimostrativa", "Attiva · simulata", hasArtifact ? "49 disponibili" : "50 disponibili", hasArtifact ? "PoC dimostrativo" : "Nessuna"],
      archive: ["Archiviato · sola lettura", "Distrutta · record conservato", hasArtifact ? "49 usate: 1" : "Nessuna azione", "Ultimo stato registrato"]
    };
    const targets = ["record-state", "arena-state", "budget-state", "observed-state"];
    targets.forEach((id, index) => { byId(id).textContent = states[current][index]; });
    if (focus) {
      const heading = byId(current).querySelector("h2");
      heading.setAttribute("tabindex", "-1");
      heading.focus({ preventScroll: true });
      byId("main").scrollIntoView({ block: "start" });
    }
  }

  function navigate(view) {
    if (!views.has(view)) return;
    if (window.location.hash === "#" + view) renderView(true);
    else window.location.hash = view;
  }

  byId("choose-a").addEventListener("click", () => setConcept("a"));
  byId("choose-b").addEventListener("click", () => setConcept("b"));
  document.querySelectorAll("[data-next]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.next === "finding" && hasArtifact) byId("artifact-choice").checked = true;
      navigate(button.dataset.next);
    });
  });
  window.addEventListener("hashchange", () => renderView(true));

  byId("run-poc").addEventListener("click", () => {
    if (pending) return;
    byId("poc-output").hidden = true;
    byId("run-poc").disabled = true;
    byId("cancel-poc").disabled = false;
    note.textContent = "Job dimostrativo in esecuzione…";
    pending = window.setTimeout(() => {
      pending = null;
      hasArtifact = true;
      byId("run-poc").disabled = false;
      byId("cancel-poc").disabled = true;
      byId("poc-output").hidden = false;
      note.textContent = "Job completato · output e cleanup disponibili.";
      renderView();
    }, 850);
  });
  byId("cancel-poc").addEventListener("click", () => {
    if (!pending) return;
    window.clearTimeout(pending);
    pending = null;
    byId("run-poc").disabled = false;
    byId("cancel-poc").disabled = true;
    note.textContent = "Job dimostrativo annullato. Nessun artifact prodotto.";
  });
  byId("finding-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const title = byId("finding-name").value.trim();
    const effect = byId("finding-effect").value.trim();
    if (!title || !effect) {
      byId("finding-status").textContent = "Inserisci titolo ed effetto osservato.";
      return;
    }
    byId("archive-finding").textContent = title;
    byId("finding-status").textContent = "Finding registrato nel prototipo; nessun verdetto indipendente è stato eseguito.";
    navigate("archive");
  });
  setConcept(new URL(window.location.href).searchParams.get("concept"));
  renderView();
})();
