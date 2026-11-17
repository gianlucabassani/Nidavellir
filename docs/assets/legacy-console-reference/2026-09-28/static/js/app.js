/* Nidavellir console — client behavior (vanilla JS, no build step). */
(function () {
  "use strict";

  const C = {
    bg: "#1c2030", text: "#e6e8ee", muted: "#8b91a3", border: "#323848",
    accent: "#22d3ee", danger: "#f87171", warn: "#f59e0b", ok: "#34d399",
  };

  /* ---- orchestrator health badge (every page) ------------------------- */
  function pollHealth() {
    const badge = document.getElementById("orch-badge");
    const dot = document.getElementById("orch-dot");
    const text = document.getElementById("orch-text");
    if (!badge) return;
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) => {
        const ok = d.status === "ok";
        badge.className = "badge " + (ok ? "badge--ok" : "badge--danger");
        dot.className = "dot " + (ok ? "dot--active" : "dot--failed");
        text.textContent = ok ? "online" : "offline";
      })
      .catch(() => {
        badge.className = "badge badge--danger";
        if (dot) dot.className = "dot dot--failed";
        if (text) text.textContent = "offline";
      })
      .finally(() => setTimeout(pollHealth, 10000));
  }

  /* ---- connected-model chip (every page) ------------------------------ */
  // Schematic provider marks (not trademarks) — colored bubble + glyph.
  const BRANDS = {
    anthropic: { name: "Anthropic · Claude", color: "#d97757", model: "claude-opus-4-8",
      svg: '<svg viewBox="0 0 24 24"><path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" fill="none"/></svg>' },
    openai: { name: "OpenAI", color: "#10a37f", model: "gpt-4o",
      svg: '<svg viewBox="0 0 24 24"><path d="M12 3l7.79 4.5v9L12 21l-7.79-4.5v-9z" fill="none" stroke="currentColor" stroke-width="2"/></svg>' },
    gemini: { name: "Google · Gemini", color: "#4285f4", model: "gemini-2.5-flash",
      svg: '<svg viewBox="0 0 24 24"><path d="M12 2c.6 5.3 3.1 7.8 8.4 8.4-5.3.6-7.8 3.1-8.4 8.4-.6-5.3-3.1-7.8-8.4-8.4C8.9 9.8 11.4 7.3 12 2z" fill="currentColor"/></svg>' },
    deepseek: { name: "DeepSeek", color: "#4d6bfe", model: "deepseek-chat",
      svg: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M7 13c2 2.2 8 2.2 10-1.2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' },
    ollama: { name: "Ollama · local", color: "#414959", model: "llama3",
      svg: '<svg viewBox="0 0 24 24"><path d="M8.5 3v4M15.5 3v4M6 10a6 6 0 0112 0v4a6 6 0 01-12 0z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' },
    local: { name: "Local model", color: "#22d3ee", model: "",
      svg: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' },
    openrouter: { name: "OpenRouter", color: "#7a83ff", model: "anthropic/claude-3.5-sonnet",
      svg: '<svg viewBox="0 0 24 24"><path d="M4 12h5l3-4 3 8 3-4h2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' },
    huggingface: { name: "Hugging Face", color: "#ffb300", model: "meta-llama/Llama-3.1-8B-Instruct",
      svg: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8.5 10h.01M15.5 10h.01M8.5 14.5c1.6 1.6 5.4 1.6 7 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' },
    custom: { name: "Custom · OpenAI-compatible", color: "#22d3ee", model: "",
      svg: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2c3 3 3 17 0 20M12 2c-3 3-3 17 0 20" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>' },
  };
  const FALLBACK = { name: "AI model", color: "#6b7280",
    svg: '<svg viewBox="0 0 24 24"><rect x="5" y="8" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 4v4M9.5 13h.01M14.5 13h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' };
  const brandOf = (p) => BRANDS[(p || "").toLowerCase()] || FALLBACK;

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  const PROVIDERS = ["anthropic", "openai", "openrouter", "huggingface", "gemini",
    "deepseek", "ollama", "local", "custom"];
  const KEYLESS = ["local", "ollama", "custom"]; // local/self-hosted may run without a key
  // Providers where a base URL is relevant (OpenAI-compatible). anthropic is fixed.
  const NEEDS_BASE = ["openrouter", "huggingface", "ollama", "local", "custom"];

  let modelConn = null;   // {configured, provider, model, key_last4, status, updated_at}
  let liveAgent = null;   // {connected, provider, model, stance, ...} self-declared
  let pickProvider = null; // provider currently selected in the modal

  const setBubble = (el, b) => { el.style.background = b.color; el.innerHTML = b.svg; };
  const csrfToken = () => {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : "";
  };

  // Hover dropdown (desktop fast path) — built once.
  function buildProviderMenu() {
    const list = document.getElementById("model-menu-list");
    if (!list || list.childElementCount) return;
    PROVIDERS.forEach((p) => {
      const b = brandOf(p);
      const item = document.createElement("button");
      item.type = "button";
      item.className = "model-menu__item";
      item.setAttribute("role", "menuitem");
      item.innerHTML =
        '<span class="model-menu__logo" style="background:' + b.color + '">' + b.svg +
        "</span><span>" + escapeHtml(b.name) + "</span>";
      item.addEventListener("click", () => openModelConfig(p));
      list.appendChild(item);
    });
  }

  // Provider tiles inside the modal (works without hover, e.g. touch).
  function buildPicker() {
    const pick = document.getElementById("model-pick");
    if (!pick || pick.childElementCount) return;
    PROVIDERS.forEach((p) => {
      const b = brandOf(p);
      const t = document.createElement("button");
      t.type = "button";
      t.className = "model-pick__item";
      t.dataset.provider = p;
      t.title = b.name;
      t.innerHTML = '<span class="model-pick__logo" style="background:' + b.color + '">' + b.svg + "</span>";
      t.addEventListener("click", () => selectProvider(p, false));
      pick.appendChild(t);
    });
  }

  function renderChip() {
    const chip = document.getElementById("model-chip");
    if (!chip) return;
    const logo = document.getElementById("model-chip-logo");
    const name = document.getElementById("model-chip-name");
    const dot = document.getElementById("model-chip-dot");
    const active = !!(liveAgent && liveAgent.connected);
    if (modelConn && modelConn.configured) {
      const b = brandOf(modelConn.provider);
      setBubble(logo, b);
      name.textContent = modelConn.model || b.name;
      dot.className = "dot " + (active ? "dot--active" : "dot--standby");
      chip.title = b.name + " · " + (active ? "active" : "standby") + " — click to manage";
    } else {
      setBubble(logo, FALLBACK);
      name.textContent = "Connect model";
      dot.className = "dot";
      chip.title = "Connect a model — hover to pick a provider";
    }
  }

  function refreshModel() {
    if (!document.getElementById("model-chip")) return Promise.resolve();
    return Promise.all([
      fetch("/api/model-connection").then((r) => r.json()).catch(() => null),
      fetch("/api/current-agent").then((r) => r.json()).catch(() => null),
    ]).then(([mc, la]) => {
      modelConn = mc && mc.configured ? mc : null;
      liveAgent = la;
      renderChip();
    });
  }
  function pollModel() { refreshModel().finally(() => setTimeout(pollModel, 10000)); }

  function setFormError(msg) {
    const el = document.getElementById("model-form-err");
    if (!el) return;
    el.textContent = msg || "";
    el.hidden = !msg;
  }

  function selectProvider(provider, keepModel) {
    pickProvider = provider;
    const b = brandOf(provider);
    setBubble(document.getElementById("model-modal-logo"), b);
    document.getElementById("model-modal-name").textContent = b.name;
    document.getElementById("model-modal-provider").textContent = "Provider · " + provider;
    document.querySelectorAll("#model-pick .model-pick__item").forEach((el) => {
      el.classList.toggle("is-on", el.dataset.provider === provider);
    });
    if (!keepModel) document.getElementById("model-form-model").value = b.model || "";
    document.getElementById("model-form-key").placeholder =
      KEYLESS.includes(provider) ? "(optional for local runtimes)" : "paste your key";
    // Per-connection base URL: shown for OpenAI-compatible providers, prefilled
    // when re-opening the current connection.
    const baseRow = document.getElementById("model-form-base-row");
    if (baseRow) baseRow.hidden = !NEEDS_BASE.includes(provider);
    const baseInp = document.getElementById("model-form-base-url");
    if (baseInp) {
      const cur = modelConn && modelConn.configured && modelConn.provider === provider;
      baseInp.value = (cur && modelConn.base_url) ? modelConn.base_url : "";
    }
    renderVerify(null, "clear");
    showModalMeta();
  }

  function showModalMeta() {
    const kv = document.getElementById("model-modal-kv");
    const remove = document.getElementById("model-form-remove");
    const save = document.getElementById("model-form-save");
    const hint = document.getElementById("model-form-keyhint");
    const isCurrent = modelConn && modelConn.configured && modelConn.provider === pickProvider;
    if (isCurrent) {
      const active = !!(liveAgent && liveAgent.connected);
      const rows = [
        ["Status", active ? "active" : "standby (waiting)"],
        ["Stored key", modelConn.key_last4 ? "•••• " + modelConn.key_last4 : "—"],
        ...(modelConn.base_url ? [["Base URL", modelConn.base_url]] : []),
        ["Updated", modelConn.updated_at || "—"],
      ];
      kv.innerHTML = rows.map(([k, v]) => "<dt>" + k + "</dt><dd>" + escapeHtml(v) + "</dd>").join("");
      remove.hidden = false;
      save.textContent = "Update";
      hint.textContent = "Leave the key blank to keep the stored one. Encrypted at rest.";
    } else {
      kv.innerHTML = "";
      remove.hidden = true;
      save.textContent = "Connect";
      hint.textContent = "Encrypted at rest — never shown again.";
    }
  }

  function openModelConfig(provider) {
    buildPicker();
    const keepModel = !!(modelConn && modelConn.configured && modelConn.provider === provider);
    selectProvider(provider, keepModel);
    if (keepModel) document.getElementById("model-form-model").value = modelConn.model || "";
    document.getElementById("model-form-key").value = "";
    setFormError("");
    document.getElementById("model-modal").hidden = false;
    setTimeout(() => document.getElementById("model-form-key").focus(), 30);
  }

  // Clicking the bubble → manage the current connection, or start a new one.
  function openModelModal() {
    openModelConfig((modelConn && modelConn.provider) || pickProvider || PROVIDERS[0]);
  }
  function closeModelModal() {
    const m = document.getElementById("model-modal");
    if (m) m.hidden = true;
  }

  function saveModel(e) {
    e.preventDefault();
    const provider = pickProvider;
    const model = document.getElementById("model-form-model").value.trim();
    const key = document.getElementById("model-form-key").value;
    const baseUrl = (document.getElementById("model-form-base-url").value || "").trim();
    if (!model) { setFormError("Enter a model id."); return false; }
    if (provider === "custom" && !baseUrl) {
      setFormError("A custom endpoint needs a Base URL (https://host/v1)."); return false;
    }
    // Blank key is allowed only when keeping an existing same-provider key, or
    // for keyless local runtimes — the orchestrator enforces the same rule.
    const reusing = modelConn && modelConn.configured && modelConn.provider === provider;
    if (!key && !reusing && !KEYLESS.includes(provider)) {
      setFormError("Enter your API key."); return false;
    }
    const save = document.getElementById("model-form-save");
    save.disabled = true;
    setFormError("");
    fetch("/api/model-connection", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ provider: provider, model: model, api_key: key, base_url: baseUrl || null }),
    })
      .then((r) => r.json().then((b) => ({ ok: r.ok, b: b || {} })))
      .then(({ ok, b }) => {
        if (!ok) { setFormError(b.error || "Save failed."); return; }
        modelConn = b.configured ? b : null;
        renderChip();
        // Keep the modal open and confirm the stored key works (non-blocking).
        document.getElementById("model-form-key").value = "";
        showModalMeta();
        testModel();
      })
      .catch(() => setFormError("Network error."))
      .finally(() => { save.disabled = false; });
    return false;
  }

  function removeModel() {
    if (!confirm("Forget the stored model key?")) return;
    fetch("/api/model-connection", {
      method: "DELETE",
      headers: { "X-CSRFToken": csrfToken() },
    })
      .then((r) => r.json().catch(() => ({})))
      .then(() => { modelConn = null; renderChip(); closeModelModal(); })
      .catch(() => {});
  }

  function renderVerify(res, phase) {
    const el = document.getElementById("model-form-verify");
    if (!el) return;
    if (phase === "clear") { el.hidden = true; el.textContent = ""; el.className = "model-form__verify"; return; }
    el.hidden = false;
    if (phase === "pending") { el.textContent = "Testing connection…"; el.className = "model-form__verify is-pending"; return; }
    if (res && res.verified) {
      el.textContent = "✓ " + (res.detail || "key accepted");
      el.className = "model-form__verify is-ok";
    } else if (res && res.checked === false) {
      el.textContent = "⚠ " + (res.detail || "couldn't verify (no egress?)");
      el.className = "model-form__verify is-warn";
    } else {
      el.textContent = "✗ " + ((res && res.detail) || "the provider rejected the key");
      el.className = "model-form__verify is-bad";
    }
  }

  // "Test connection" — ping the provider to confirm the key works. If the key
  // field is filled, tests that key (pre-save); otherwise tests the stored one.
  function testModel() {
    const key = document.getElementById("model-form-key").value;
    const model = document.getElementById("model-form-model").value.trim();
    const baseUrl = (document.getElementById("model-form-base-url").value || "").trim();
    const body = key ? { provider: pickProvider, model: model, api_key: key, base_url: baseUrl || null } : {};
    renderVerify(null, "pending");
    fetch("/api/model-connection/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body),
    })
      .then((r) => r.json().catch(() => ({ verified: false, checked: false })))
      .then((res) => renderVerify(res))
      .catch(() => renderVerify({ verified: false, checked: false, detail: "network error" }));
  }

  /* ---- status → badge markup (mirrors _macros.html) ------------------- */
  function statusBadge(status) {
    const map = {
      active: "ok", pending: "warn", deploying: "warn",
      destroying: "danger", failed: "danger", error_destroying: "danger",
      destroyed: "idle",
    };
    const cls = map[status] || "idle";
    const label = (status || "unknown").replace(/_/g, " ").toUpperCase();
    return '<span class="badge badge--' + cls + '">' + label + "</span>";
  }

  /* ---- parse flat outputs into nodes + networks ----------------------- */
  function parseTopology(o) {
    o = o || {};
    const nodes = [];
    Object.keys(o).forEach((k) => {
      const m = k.match(/^node_(.+)_name$/);
      if (!m) return;
      const n = m[1];
      nodes.push({
        key: n,
        ip: o["node_" + n + "_private_ip"] || "",
        state: o["node_" + n + "_state"] || "running",
        url: o["node_" + n + "_url"] || "",
        ssh: o["node_" + n + "_ssh_command"] || "",
      });
    });
    let nets = o.lab_networks || (o.lab_network ? [o.lab_network] : []);
    if (!nets.length && nodes.length) nets = ["arena-net"];
    return { nodes, nets };
  }

  // Post-deploy view (/arena): adapt the provider's flat outputs into the SAME
  // topology model the spec preview uses, so the live arena renders with the
  // identical Packet-Tracer aesthetic (icons + switch-star). Flat outputs carry
  // no per-node segment membership, so every node hangs off one arena switch —
  // the live IPs / state / links live in the Nodes table beside the diagram.
  function outputsToTopology(o) {
    const { nodes, nets } = parseTopology(o);
    const seg = nets[0] || "arena-net";
    return {
      segments: [{ name: seg, cidr: null }],
      nodes: nodes.map((nd) => ({
        name: nd.key,
        kind: nd.ssh ? "foothold" : nd.url ? "target" : "host",
        stance: nd.ssh ? "attacker" : null,
        entrypoint: !!nd.ssh,
        ports: [],
        segments: [seg],
        dead: !!(nd.state && nd.state !== "running"),
      })),
      egress: o && o.egress === "open" ? "open" : "blocked",
    };
  }

  function renderTopology(o) {
    renderSpecTopology("topo", outputsToTopology(o));
  }

  /* ---- engagement/run workspace tabs (ROADMAP C3) ---------------------- */
  // One page, one contextual surface at a time. The tab is part of the URL so an
  // operator can link a colleague straight to the findings or the evidence.
  function initWorkspaceTabs() {
    const bar = document.getElementById("ws-tabs");
    if (!bar) return;
    const tabs = [...bar.querySelectorAll("[data-tab]")];
    const panels = [...document.querySelectorAll(".ws-panel")];
    if (!tabs.length) return;

    function show(name, push) {
      const target = tabs.some((t) => t.dataset.tab === name) ? name : tabs[0].dataset.tab;
      tabs.forEach((t) => {
        const on = t.dataset.tab === target;
        t.classList.toggle("on", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      panels.forEach((p) => { p.hidden = p.dataset.tab !== target; });
      if (push && location.hash.slice(1) !== target) {
        history.replaceState(null, "", "#" + target);
      }
      // Cytoscape cannot measure a hidden container, so re-fit when it appears.
      if (target === "infrastructure") setTimeout(() => window.Nidavellir.fit(), 0);
    }

    tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.tab, true)));
    window.addEventListener("hashchange", () => show(location.hash.slice(1), false));
    show(location.hash.slice(1) || tabs[0].dataset.tab, false);
  }

  /* ---- arena detail page ---------------------------------------------- */
  // Live workspace state arrives over SSE (ROADMAP C3). The timer-based poller
  // below stays as the fallback for a browser or proxy that cannot hold a stream.
  let arenaStream = null;

  function initArena() {
    const id = document.body.dataset.instanceId;
    let last = {};
    try { last = JSON.parse(document.getElementById("lab-data").textContent || "{}"); } catch (e) {}
    renderTopology(last);
    initWorkspaceChanges(id);
    initResearchPreflight(id);

    let prevStatus = null;

    function applyState(d) {
      const badge = document.getElementById("lab-status");
      if (badge && d.status) badge.innerHTML = statusBadge(d.status);
      // Reaching 'active' for the first time → reload to populate the node table.
      if (d.status === "active" && prevStatus && prevStatus !== "active") {
        window.location.reload(); return true;
      }
      prevStatus = d.status;
      if (d.outputs && JSON.stringify(d.outputs) !== JSON.stringify(last)) {
        last = d.outputs; renderTopology(last);
      }
      return false;
    }

    function pollArena() {
      let delay = 3000;
      const poll = () => {
        fetch("/api/poll/" + id)
          .then((r) => r.json())
          .then((d) => {
            if (applyState(d)) return;
            delay = d.status === "active" ? 6000 : 3000;
            setTimeout(poll, delay);
          })
          .catch(() => setTimeout(poll, 8000));
      };
      poll();
    }

    if (!window.EventSource) { pollArena(); return; }
    let failures = 0;
    const stream = new EventSource("/api/arenas/" + id + "/stream");
    arenaStream = stream;
    stream.addEventListener("state", (m) => {
      failures = 0;
      try { applyState(JSON.parse(m.data)); } catch (e) {}
    });
    stream.addEventListener("activity", (m) => {
      failures = 0;
      let events = [];
      try { events = (JSON.parse(m.data).events || []); } catch (e) { return; }
      if (events.length) engOnActivity(events);
      if (events.some((e) => e.type === "http_request")) httpLoad();
    });
    stream.onerror = () => {
      // EventSource retries on its own; give up and poll only if it keeps failing.
      if (stream.readyState === EventSource.CLOSED && ++failures >= 3) {
        arenaStream = null; pollArena();
      }
    };
  }

  function initResearchPreflight(arenaId) {
    const card = document.getElementById("preflight-card");
    if (!card || !arenaId) return;
    fetch("/api/arenas/" + encodeURIComponent(arenaId) + "/preflight")
      .then((response) => response.json().then((body) => ({ response, body })))
      .then(({ response, body }) => {
        if (!response.ok || !body.target) return;
        card.hidden = false;
        const target = body.target || {};
        const identity = target.identity || {};
        const reset = body.reset_contract || {};
        const state = document.getElementById("preflight-state");
        state.className = "badge " +
          (body.status === "passed" ? "badge--ok" :
            (body.status === "failed" ? "badge--danger" : "badge--idle"));
        state.textContent = body.status || "pending";
        document.getElementById("preflight-source").textContent = target.source || "—";
        document.getElementById("preflight-source").title = target.source || "";
        document.getElementById("preflight-identity").textContent =
          identity.digest ? identity.digest.slice(0, 16) : "resolving…";
        document.getElementById("preflight-identity").title = identity.digest || "";
        document.getElementById("preflight-platform").textContent =
          target.platform || identity.platform || "provider native";
        document.getElementById("preflight-reset").textContent =
          reset.strategy ? reset.strategy.replace(/_/g, " ") : "—";
        const checks = document.getElementById("preflight-checks");
        checks.textContent = "";
        (body.checks || []).forEach((check) => {
          const row = document.createElement("div");
          row.className = "preflight-check " +
            (check.ok ? "preflight-check--ok" : "preflight-check--fail") +
            (check.required ? "" : " preflight-check--optional");
          const icon = document.createElement("i");
          icon.className = "fa-solid " + (check.ok ? "fa-circle-check" : "fa-circle-xmark");
          const text = document.createElement("div");
          const title = document.createElement("b");
          title.textContent = (check.id || "check").replace(/_/g, " ");
          const detail = document.createElement("div");
          detail.className = "muted";
          detail.textContent = check.detail || "";
          text.append(title, detail);
          row.append(icon, text);
          checks.appendChild(row);
        });
      })
      .catch(() => {});
  }

  function initWorkspaceChanges(arenaId) {
    const card = document.getElementById("workspace-card");
    if (!card || !arenaId) return;
    const nodeSelect = document.getElementById("workspace-node");
    const pathSelect = document.getElementById("workspace-path");
    const baseInput = document.getElementById("workspace-base");
    const diffBox = document.getElementById("workspace-diff");
    const count = document.getElementById("workspace-count");
    const meta = document.getElementById("workspace-meta");
    const note = document.getElementById("workspace-note");
    const more = document.getElementById("workspace-more");
    const refresh = document.getElementById("workspace-refresh");
    const exportButton = document.getElementById("workspace-export");
    const includeUntracked = document.getElementById("workspace-include-untracked");
    let nextStart = null;
    let loading = false;

    function renderDiff(text) {
      diffBox.textContent = "";
      if (!text) {
        const empty = document.createElement("span");
        empty.className = "workspace-empty";
        empty.textContent = "No tracked changes against this baseline.";
        diffBox.appendChild(empty);
        return;
      }
      text.split("\n").forEach((line) => {
        const row = document.createElement("span");
        row.className = "workspace-line";
        if (line.startsWith("+++") || line.startsWith("---") ||
            line.startsWith("diff ") || line.startsWith("index ")) {
          row.classList.add("workspace-line--meta");
        } else if (line.startsWith("@@")) {
          row.classList.add("workspace-line--hunk");
        } else if (line.startsWith("+")) {
          row.classList.add("workspace-line--add");
        } else if (line.startsWith("-")) {
          row.classList.add("workspace-line--del");
        }
        row.textContent = line || " ";
        diffBox.appendChild(row);
      });
    }

    function setFiles(files, selected) {
      pathSelect.textContent = "";
      const all = document.createElement("option");
      all.value = "";
      all.textContent = "All tracked changes";
      pathSelect.appendChild(all);
      (files || []).forEach((file) => {
        const option = document.createElement("option");
        option.value = file.path;
        option.textContent = (file.untracked ? "? " : "") + file.path;
        pathSelect.appendChild(option);
      });
      pathSelect.value = selected || "";
    }

    function load(startLine) {
      if (loading || !nodeSelect.value) return;
      loading = true;
      refresh.disabled = true;
      more.disabled = true;
      const query = new URLSearchParams({
        base: (baseInput.value || "HEAD").trim(),
        context_lines: "3",
        start_line: String(startLine || 0),
        max_lines: "300",
      });
      if (pathSelect.value) query.set("path", pathSelect.value);
      fetch("/api/arenas/" + encodeURIComponent(arenaId) + "/workspaces/" +
            encodeURIComponent(nodeSelect.value) + "/diff?" + query.toString())
        .then((response) => response.json().then((body) => ({ response, body })))
        .then(({ response, body }) => {
          if (!response.ok) throw new Error(body.error || "Workspace inspection failed");
          const previousPath = pathSelect.value;
          setFiles(body.changed_files, previousPath);
          renderDiff(body.diff || "");
          count.textContent = body.changed_file_count + " file" +
            (body.changed_file_count === 1 ? "" : "s");
          const accessLabel = body.workspace && body.workspace.kind === "whitebox"
            ? "writable research copy · target unchanged"
            : (body.workspace && body.workspace.writable
              ? "writable setup checkout" : "read-only source");
          meta.textContent = accessLabel +
            " · baseline " + (body.baseline || body.base || "HEAD").slice(0, 12) +
            " · lines " + body.start_line + "–" + (body.start_line + body.returned_lines) +
            " of " + body.total_lines;
          note.textContent = body.note || (body.truncated ? "Diff is paginated to keep agent and browser context bounded." : "");
          nextStart = body.next_start_line;
          more.hidden = nextStart == null;
        })
        .catch((error) => {
          renderDiff("");
          meta.textContent = error.message;
          note.textContent = "";
          more.hidden = true;
        })
        .finally(() => {
          loading = false;
          refresh.disabled = false;
          more.disabled = false;
        });
    }

    fetch("/api/arenas/" + encodeURIComponent(arenaId) + "/workspaces")
      .then((response) => response.json().then((body) => ({ response, body })))
      .then(({ response, body }) => {
        if (!response.ok || !(body.workspaces || []).length) return;
        nodeSelect.textContent = "";
        body.workspaces.forEach((workspace) => {
          const option = document.createElement("option");
          option.value = workspace.node;
          option.textContent = workspace.node + (workspace.writable ? " · writable" : " · white-box");
          nodeSelect.appendChild(option);
        });
        card.hidden = false;
        load(0);
      })
      .catch(() => {});

    nodeSelect.addEventListener("change", () => { setFiles([], ""); load(0); });
    pathSelect.addEventListener("change", () => load(0));
    refresh.addEventListener("click", () => load(0));
    exportButton.addEventListener("click", () => {
      if (!nodeSelect.value) return;
      const selected = pathSelect.selectedOptions[0];
      const isUntracked = selected && selected.textContent.startsWith("? ");
      if (includeUntracked.checked && (!pathSelect.value || !isUntracked)) {
        note.textContent = "Select one untracked file before including its content.";
        return;
      }
      exportButton.disabled = true;
      postJson(
        "/api/arenas/" + encodeURIComponent(arenaId) + "/workspaces/" +
          encodeURIComponent(nodeSelect.value) + "/patch-artifacts",
        {
          base: (baseInput.value || "HEAD").trim(),
          path: pathSelect.value || null,
          context_lines: 3,
          include_untracked_paths: includeUntracked.checked ? [pathSelect.value] : [],
        }
      ).then(({ status, data }) => {
        if (status !== 200) throw new Error(data.error || data.detail || "Patch export failed");
        const artifact = data.artifact || {};
        const findingArtifact = document.getElementById("mf-artifact");
        if (findingArtifact) findingArtifact.value = artifact.digest || "";
        const blob = new Blob([data.patch || ""], { type: "text/x-diff;charset=utf-8" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = nodeSelect.value + "-" + (artifact.digest || "patch").slice(-12) + ".patch";
        link.click();
        URL.revokeObjectURL(link.href);
        note.textContent = "Exported " + artifact.bytes + " bytes · " + artifact.digest +
          " · attached to the next manual finding.";
      }).catch((error) => {
        note.textContent = error.message;
      }).finally(() => { exportButton.disabled = false; });
    });
    more.addEventListener("click", () => load(nextStart));
  }

  /* ---- utilities ------------------------------------------------------ */
  window.copyField = function (elId) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.select();
    navigator.clipboard.writeText(el.value).catch(() => {});
  };

  window.destroyInstance = function (id) {
    if (!confirm("Destroy this arena? This action is irreversible.")) return;
    const meta = document.querySelector('meta[name="csrf-token"]');
    fetch("/api/destroy/" + id, {
      method: "POST",
      headers: meta ? { "X-CSRFToken": meta.content } : {},
    })
      .then((r) => {
        if (r.ok) { window.location.href = "/engagements"; return; }
        return r.json().catch(() => ({})).then((b) => {
          throw new Error(b.error || "Destroy failed (HTTP " + r.status + ")");
        });
      })
      .catch((e) => alert("Error: " + e.message));
  };

  /* ---- co-pilot chat (connected model + arena context) ---------------- */
  let copilotHistory = [];
  let copilotBusy = false;
  const currentArena = () => window.NIDAVELLIR_ARENA || null;

  const isCompactNavigation = () => window.innerWidth <= 1000;

  function syncSidebarToggle() {
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("sidebar-toggle");
    if (!sidebar || !toggle) return;
    const expanded = isCompactNavigation()
      ? sidebar.classList.contains("open")
      : !document.body.classList.contains("nav-collapsed");
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  }

  function closeSidebar() {
    const sidebar = document.getElementById("sidebar");
    if (sidebar) sidebar.classList.remove("open");
    syncSidebarToggle();
  }

  function toggleSidebar() {
    // Compact: off-canvas open/close. Desktop: collapse to an icon-only rail
    // (items stay clickable), persisted across pages.
    if (isCompactNavigation()) {
      document.body.classList.remove("nav-collapsed");
      document.getElementById("sidebar").classList.toggle("open");
      syncSidebarToggle();
      return;
    }
    const collapsed = document.body.classList.toggle("nav-collapsed");
    try { localStorage.setItem("nav-collapsed", collapsed ? "1" : "0"); } catch (e) {}
    syncSidebarToggle();
  }

  function toggleCopilot() {
    const el = document.getElementById("copilot");
    if (!el) return;
    const opening = el.hidden;
    el.hidden = !opening;
    document.body.classList.toggle("copilot-open", opening);
    if (opening) {
      const arena = currentArena();
      const ctx = document.getElementById("copilot-ctx");
      if (ctx) ctx.textContent = arena ? ("arena · " + arena.slice(0, 12)) : "no arena selected";
      const inp = document.getElementById("copilot-input");
      if (inp) setTimeout(() => inp.focus(), 50);
    }
  }

  function appendCopilotMsg(role, text) {
    const log = document.getElementById("copilot-log");
    const hint = log.querySelector(".copilot__hint");
    if (hint) hint.remove();
    const msg = document.createElement("div");
    msg.className = "copilot__msg copilot__msg--" + role;
    msg.textContent = text;
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
    return msg;
  }

  function sendCopilot(e) {
    if (e) e.preventDefault();
    if (copilotBusy) return false;
    const input = document.getElementById("copilot-input");
    const text = (input.value || "").trim();
    if (!text) return false;
    appendCopilotMsg("user", text);
    copilotHistory.push({ role: "user", content: text });
    input.value = "";
    copilotBusy = true;
    document.getElementById("copilot-send").disabled = true;
    const bubble = appendCopilotMsg("assistant", "…");
    let acc = "";
    fetch("/api/copilot", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ arena_id: currentArena(), messages: copilotHistory }),
    })
      .then((resp) => {
        if (!resp.body || !resp.body.getReader) {
          return resp.text().then((t) => { acc = t; bubble.textContent = t || "…"; });
        }
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        const log = document.getElementById("copilot-log");
        const pump = () => reader.read().then(({ done, value }) => {
          if (done) return;
          acc += dec.decode(value, { stream: true });
          bubble.textContent = acc || "…";
          log.scrollTop = log.scrollHeight;
          return pump();
        });
        return pump();
      })
      .then(() => {
        // Record the assistant turn ONLY on a real reply. The proxy streams errors
        // as a "[co-pilot] …" line at HTTP 200, so on that sentinel (or an empty
        // reply) drop the just-sent user turn instead — keeping the history
        // strictly alternating so the next request isn't two consecutive user
        // turns (which the provider rejects).
        if (acc && !acc.startsWith("[co-pilot]")) {
          copilotHistory.push({ role: "assistant", content: acc });
        } else {
          copilotHistory.pop();
          bubble.classList.add("copilot__msg--error");
        }
      })
      .catch(() => {
        bubble.textContent = "[co-pilot] connection error.";
        bubble.classList.add("copilot__msg--error");
        copilotHistory.pop();
      })
      .finally(() => {
        copilotBusy = false;
        document.getElementById("copilot-send").disabled = false;
      });
    return false;
  }

  /* ---- engagement: unified roles board (setup + agent bindings) -------- */
  /* ---- in-arena console: positioning (all) · configurator (SUT) · live log ----
     Posture: the platform HOSTS and MONITORS a bring-your-own agent — it never
     drives the agent itself. "Positioning" grants a binding (authorization, live
     per tool-call); the operator then points their own agent app (Claude Code, a
     custom MCP framework, …) at the gateway with that key+stance and tells IT to
     act. Every tool call streams into the live-activity log below. Boards are
     read-only (safe to repaint on poll); the assign form + configurator action
     area build once / on shape change, so half-typed input survives a refresh. */
  let engArena = null, engActive = false, engSut = false, engGateway = "";
  let engTimer = null, engCfgSig = null, engRecipeDone = false;
  let engEvents = [];   // newest-first window the live log and positioning read from

  const POS_STANCES = [
    { id: "attacker", label: "Attacker", icon: "fa-crosshairs",    color: "var(--attacker)", desc: "Pentest the targets from the foothold" },
    { id: "defender", label: "Defender", icon: "fa-shield-halved", color: "var(--defender)", desc: "Read the detection / event feed" },
    { id: "mitm",     label: "MITM",     icon: "fa-user-secret",   color: "var(--mitm)",     desc: "Observe in-path segment traffic" },
  ];

  function engApi(path, method, body) {
    const opts = { method: method || "GET", headers: {} };
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    if (method && method !== "GET") opts.headers["X-CSRFToken"] = csrfToken();
    return fetch("/api/setup/" + engArena + path, opts).then((r) => r.json());
  }

  function initEngagement(arena, active, isSut, gateway) {
    engArena = arena; engActive = !!active; engSut = !!isSut;
    engGateway = gateway || ""; engCfgSig = null; engRecipeDone = false;
    engRenderRecipe();
    engRefresh();
    // The stream drives updates now; this slow tick is only a safety net for
    // state that no audit event announces (an agent key expiring, say).
    if (engTimer) clearInterval(engTimer);
    engTimer = setInterval(engRefresh, arenaStream ? 30000 : 4000);
  }

  // New audit events from the workspace stream: render them, and refresh the
  // panels whose state those events just changed.
  function engOnActivity(fresh) {
    const newestFirst = fresh.slice().reverse();
    engEvents = newestFirst.concat(engEvents).slice(0, 200);
    engRenderLog(engEvents);
    const touchesPanels = fresh.some((e) =>
      /^(agent_|setup_|binding|finding)/.test(e.type || ""));
    if (touchesPanels && engArena) engRefresh();
  }

  // Configurator lives in an overlay modal (opened from its overview card); the
  // 4s engRefresh keeps its board/console fresh whether it's open or closed.
  function openConfigurator() {
    const m = document.getElementById("configurator-modal");
    if (m) { m.hidden = false; engRefresh(); }
  }
  function closeConfigurator() {
    const m = document.getElementById("configurator-modal");
    if (m) m.hidden = true;
  }

  function engRefresh() {
    const pBind = fetch("/api/arenas/" + engArena + "/bindings")
      .then((r) => r.json()).then((d) => d.bindings || []).catch(() => []);
    const pEvents = fetch("/api/arenas/" + engArena + "/events")
      .then((r) => r.json()).then((d) => d.events || []).catch(() => []);
    const pSetup = (engActive && engSut) ? engApi("").catch(() => null) : Promise.resolve(null);
    Promise.all([pBind, pEvents, pSetup]).then(([binds, events, setup]) => {
      engEvents = events;
      engRenderPositioning(binds, events);
      engRenderConfigurator(setup);
      engRenderLog(events);
    }).catch(() => {});
  }

  function engErr(msg) {
    const e = document.getElementById("pos-err");
    if (e) { e.textContent = msg || ""; e.hidden = !msg; }
  }
  function engCfgErr(msg) {
    const e = document.getElementById("cfg-err");
    if (e) { e.textContent = msg || ""; e.hidden = !msg; }
  }

  /* -- positioning ----------------------------------------------------------- */

  // actor -> { actions, connected, lastCmd } from the recent event window, so a
  // positioned key shows authorized → connected → active as its agent acts.
  function engActorActivity(events) {
    const map = {};
    (events || []).forEach((e) => {
      const p = e.payload || {};
      const actor = p.actor || e.actor;
      if (!actor) return;
      const m = map[actor] || (map[actor] = { actions: 0, connected: false });
      if (["agent_exec", "finding", "mitm_observe", "setup_step"].includes(e.type)) m.actions++;
      if (e.type === "agent_session") m.connected = true;
    });
    return map;
  }

  function engKeyState(b, act) {
    if (b.paused) return { cls: "warn", txt: "paused" };
    const a = act[b.agent_name];
    if (a && a.actions) return { cls: "ok", txt: "active · " + a.actions + " action" + (a.actions === 1 ? "" : "s") };
    if (a && a.connected) return { cls: "accent", txt: "connected" };
    return { cls: "idle", txt: "awaiting agent" };
  }

  function engKeyChip(b, act) {
    const st = engKeyState(b, act);
    const enc = encodeURIComponent(b.agent_name);
    const pauseBtn = b.paused
      ? '<button class="btn btn-primary btn-xs" data-eng="resume" data-name="' + enc + '">Resume</button>'
      : '<button class="btn btn-xs" data-eng="pause" data-name="' + enc + '">Pause</button>';
    return '<div class="pos-key">' +
      '<span class="mono pos-key__n">' + escapeHtml(b.agent_name) + "</span>" +
      '<span class="badge badge--' + st.cls + '">' + st.txt + "</span>" +
      '<span class="pos-key__by muted">by ' + escapeHtml(b.granted_by || "—") + (b.auto ? " · auto" : "") + "</span>" +
      '<span class="pos-key__act">' + pauseBtn +
      '<button class="btn btn-danger btn-xs" data-eng="revoke" data-name="' + enc + '">Revoke</button></span></div>';
  }

  function engStanceBadge(sb, act) {
    if (!sb.length) return '<span class="badge badge--idle">no agent</span>';
    let best = "awaiting";
    sb.forEach((b) => {
      const a = act[b.agent_name];
      if (a && a.actions) best = "active";
      else if (a && a.connected && best !== "active") best = "connected";
      else if (b.paused && best === "awaiting") best = "paused";
    });
    const map = { active: ["ok", "active"], connected: ["accent", "connected"],
                  paused: ["warn", "paused"], awaiting: ["accent", "authorized"] };
    const [cls, txt] = map[best];
    return '<span class="badge badge--' + cls + '">' + txt + "</span>";
  }

  function engRenderPositioning(binds, events) {
    const act = engActorActivity(events);
    const st = document.getElementById("pos-state");
    if (st) {
      st.className = "badge badge--" + (binds.length ? "accent" : "idle");
      st.textContent = binds.length
        ? binds.length + " agent" + (binds.length === 1 ? "" : "s") + " positioned"
        : "no agents positioned";
    }
    const board = document.getElementById("pos-board");
    if (board) {
      let rows = "";
      POS_STANCES.forEach((s) => {
        const sb = binds.filter((b) => (b.stance || "") === s.id);
        rows += '<div class="pos-row">' +
          '<div class="pos-role"><span class="pos-ic" style="color:' + s.color + '">' +
            '<i class="fa-solid ' + s.icon + '"></i></span>' +
            '<div><div class="pos-role__t">' + s.label + "</div>" +
            '<div class="pos-role__d muted">' + s.desc + "</div></div></div>" +
          '<div class="pos-mid"><div class="pos-stat">' + engStanceBadge(sb, act) + "</div>" +
            (sb.length
              ? '<div class="pos-keys">' + sb.map((b) => engKeyChip(b, act)).join("") + "</div>"
              : '<div class="pos-keys pos-keys--empty muted">No agent authorized — Assign a key, then connect your agent app (recipe below).</div>') +
          "</div>" +
          '<div class="pos-assign-col"><button class="btn btn-sm" data-pos-assign="' + s.id + '">' +
            (sb.length ? "+ key" : "Assign") + "</button></div></div>";
      });
      const others = binds.filter((b) => !POS_STANCES.some((s) => s.id === (b.stance || "")));
      if (others.length) {
        rows += '<div class="pos-row pos-row--other"><div class="pos-role muted">' +
          '<span class="pos-ic"><i class="fa-solid fa-key"></i></span>' +
          '<div><div class="pos-role__t">Other</div><div class="pos-role__d muted">configurator / unrestricted</div></div></div>' +
          '<div class="pos-mid"><div class="pos-stat"></div><div class="pos-keys">' +
          others.map((b) => engKeyChip(b, act)).join("") + "</div></div><div class=\"pos-assign-col\"></div></div>";
      }
      board.innerHTML = rows;
      engWireBoard();
    }
    engRenderAssign();
  }

  function engRenderAssign() {
    const host = document.getElementById("pos-actions");
    if (!host || host.dataset.ready) return;  // build once, preserve typing
    host.dataset.ready = "1";
    const opts = POS_STANCES.map((s) => '<option value="' + s.id + '">' + s.label + "</option>").join("");
    host.innerHTML =
      '<div class="pos-assign"><span class="pos-assign__h">Authorize an agent key:</span>' +
      '<select class="select" id="pos-stance" style="max-width:140px">' + opts + "</select>" +
      '<input class="input mono" id="pos-key" placeholder="agent key name (e.g. red-team-1)" style="max-width:240px">' +
      '<button class="btn btn-primary btn-sm" data-eng="grant">Authorize</button></div>' +
      '<div class="import-msg" id="pos-err" hidden style="margin:0 18px 14px"></div>';
    host.querySelector('[data-eng="grant"]').addEventListener("click", engGrant);
  }

  function _copyfield(value, id) {
    return '<div class="copyfield"><input class="input mono" readonly value="' +
      escapeHtml(value) + '" id="' + id + '">' +
      '<button class="btn btn-sm" onclick="copyField(\'' + id + '\')">' +
      '<i class="fa-regular fa-copy"></i></button></div>';
  }
  window.downloadMcpConfig = function (gw) {
    const cfg = { mcpServers: { "nidavellir-arena": { type: "http", url: gw } } };
    const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = ".mcp.json";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
  };
  function engRenderRecipe() {
    const host = document.getElementById("pos-recipe");
    if (!host || engRecipeDone) return;
    engRecipeDone = true;
    const gw = engGateway || "http://localhost:9000/mcp";
    const arena = escapeHtml(engArena || "<arena_id>");
    const upCmd = "NIDAVELLIR_AGENT_KEY=<agent-key> NIDAVELLIR_STANCE=attacker " +
      "docker compose --profile agent-gateway up -d agent-gateway";
    host.innerHTML =
      '<details class="pos-recipe"><summary><i class="fa-solid fa-plug"></i> ' +
      "Connect your agent app — one command, no hand-written config</summary>" +
      '<ol class="pos-recipe__steps">' +
      '<li>Create an agent key (admin) and Authorize it above (stance <b>attacker</b>):' +
        _copyfield("docker exec nidavellir-orchestrator python auth.py create-key red-team-1 agent", "rc-key") + "</li>" +
      '<li>Start the gateway carrying that key + stance:' + _copyfield(upCmd, "rc-up") + "</li>" +
      '<li>Add it to Claude Code — one line, no file to edit:' +
        _copyfield("claude mcp add --transport http nidavellir-arena " + gw, "rc-mcp") +
        '<button class="btn btn-sm" style="margin-top:6px" onclick="downloadMcpConfig(\'' + escapeHtml(gw) + '\')">' +
        '<i class="fa-solid fa-download"></i> or download .mcp.json</button></li>' +
      '<li>Tell your agent to work this arena — pass <b>arena_id=<span class="mono">' + arena + '</span></b>, ' +
        'e.g. <i>“announce yourself, then attack arena ' + arena + ' from the foothold and report findings”</i>. ' +
        "Every action streams into <b>Live activity</b> below, where you can Pause or Revoke.</li>" +
      "</ol></details>";
  }

  /* -- configurator (SUT only) ----------------------------------------------- */

  function engSetupDriver(mode) {
    if (mode === "operator") return "Operator (human)";
    if (mode === "hitl") return "Agent proposes · you approve";
    if (mode === "autonomous") return "Agent (autonomous)";
    return "—";
  }

  function engRenderConfigurator(setup) {
    const board = document.getElementById("cfg-board");
    if (!board) return;  // not a SUT arena — the card isn't rendered
    const stEl = document.getElementById("cfg-state");
    if (!engActive) {
      board.innerHTML = '<div class="cfg-note" style="padding:16px 18px">Arena is not active.</div>';
      if (stEl) { stEl.className = "badge badge--idle"; stEl.textContent = "inactive"; }
      return;
    }
    const open = setup && setup.open, exp = setup && setup.expired;
    if (stEl) {
      stEl.className = "badge badge--" + (open ? (exp ? "danger" : "ok") : "idle");
      stEl.textContent = open ? (exp ? "expired" : "setup open") : "not started";
    }
    // Closed-state overview line (the arena page shows this without opening the modal).
    const ov = document.getElementById("cfg-overview-summary");
    if (ov) {
      ov.textContent = !engActive
        ? "Arena is not active."
        : open
          ? engSetupDriver(setup.mode) + " · " + setup.steps_run + "/" + setup.command_budget +
            " steps" + (exp ? " · session expired" : "")
          : "Not started — bring the software-under-test up on the victim before positioning an agent.";
    }
    if (open) {
      board.innerHTML = '<div class="cfg-meta" style="padding:14px 18px">' +
        "<b>Driver:</b> " + escapeHtml(engSetupDriver(setup.mode)) +
        ' · <b>Scope:</b> <span class="mono">' + escapeHtml((setup.nodes || []).join(", ") || "victim") + "</span>" +
        " · <b>Steps:</b> " + setup.steps_run + "/" + setup.command_budget +
        " · <b>Egress:</b> " + (setup.egress_enforced ? "open" : "off") + "</div>";
    } else {
      board.innerHTML = '<div class="cfg-note" style="padding:14px 18px">The software-under-test is not set up yet. ' +
        "Start the setup phase below to bring the service up on the victim before positioning an attacker.</div>";
    }
    const sig = open ? "open|" + setup.mode : "start";
    const acts = document.getElementById("cfg-actions");
    if (acts && sig !== engCfgSig) { engCfgSig = sig; acts.innerHTML = engCfgActions(setup); engWireCfg(); }
    else if (open) engPatch(setup);
  }

  function engCfgActions(setup) {
    let html = "";
    if (!setup || !setup.open) {
      html = '<div class="cfg-start" style="padding:0 18px 16px">' +
        '<label class="cfg-fld"><span>Mode</span><select class="select" id="eng-mode">' +
        '<option value="operator">operator-scripted (you run steps)</option>' +
        '<option value="hitl">HITL (agent proposes, you approve)</option>' +
        '<option value="autonomous">autonomous (agent runs directly — needs platform flag)</option>' +
        "</select></label>" +
        '<label class="cfg-fld"><span>Time-box (s)</span><input class="input" id="eng-tb" type="number" value="1800" min="60"></label>' +
        '<label class="cfg-fld"><span>Step budget</span><input class="input" id="eng-budget" type="number" value="50" min="1"></label>' +
        '<label class="cfg-check"><input type="checkbox" id="eng-egress"> open setup egress (victim can fetch dependencies)</label>' +
        '<button class="btn btn-primary btn-sm" data-eng="start">Start setup</button></div>';
    } else {
      html = '<div style="padding:0 18px 16px">';
      const conn = setup.connect || {}, ck = Object.keys(conn);
      if (ck.length) {
        html += '<div class="cfg-note" style="margin-bottom:8px"><b>Connect:</b> ' +
          ck.map((n) => escapeHtml(n) + ' → <span class="mono">' + escapeHtml(conn[n]) + "</span>").join(" · ") + "</div>";
      }
      if (setup.mode === "operator") {
        const no = (setup.nodes || []).map((n) => '<option value="' + escapeHtml(n) + '">' + escapeHtml(n) + "</option>").join("");
        html += '<div class="cfg-step"><select class="select" id="eng-node" style="max-width:150px">' + no + "</select>" +
          '<input class="input mono" id="eng-cmd" placeholder="setup command, e.g. apt-get install -y nginx">' +
          '<button class="btn btn-sm" data-eng="step">Run</button></div><pre class="cfg-out" id="eng-out" hidden></pre>';
      } else if (setup.mode === "hitl") {
        html += '<div class="cfg-gen"><button class="btn btn-sm" id="eng-gen-btn" data-eng="generate">' +
          '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate steps (your model)</button>' +
          '<span class="muted" style="font-size:12px;margin-left:8px" id="eng-gen-msg"></span></div>' +
          '<div id="eng-props">' + engProposals(setup) + "</div>";
      } else {
        html += '<div class="cfg-note">Autonomous: the connected agent runs setup steps directly through ' +
          "the gateway (double-locked). Watch Live activity below.</div>";
      }
      html += '<div style="margin-top:12px"><button class="btn btn-danger btn-sm" data-eng="finish">Finish setup</button></div></div>';
    }
    html += '<div class="import-msg" id="cfg-err" hidden style="margin:0 18px 14px"></div>';
    return html;
  }

  function engProposals(s) {
    const pend = s.pending_proposals || [];
    return pend.length
      ? '<div class="cfg-props">' + pend.map((p) =>
          '<div class="cfg-prop"><div class="mono">' + escapeHtml(p.command) + "</div>" +
          (p.rationale ? '<div class="muted" style="font-size:12px;margin-top:3px">' + escapeHtml(p.rationale) + "</div>" : "") +
          '<div class="cfg-prop__act"><span class="muted" style="font-size:12px">' + escapeHtml(p.node) + "</span>" +
          '<button class="btn btn-primary btn-sm" onclick="Nidavellir.engDecide(\'' + p.step_id + "','approve')\">Approve</button>" +
          '<button class="btn btn-danger btn-sm" onclick="Nidavellir.engDecide(\'' + p.step_id + "','reject')\">Reject</button>" +
          "</div></div>").join("") + "</div>"
      : '<div class="cfg-note">No pending proposals. The connected agent (configurator stance) proposes ' +
        "steps via the gateway; approve them here.</div>";
  }

  function engPatch(s) {
    if (s.mode === "hitl") {
      const w = document.getElementById("eng-props");
      if (w && !(document.activeElement && w.contains(document.activeElement))) w.innerHTML = engProposals(s);
    }
  }

  /* -- live activity log ----------------------------------------------------- */

  function engLogLine(e) {
    const p = e.payload || {};
    const actor = escapeHtml(p.actor || e.actor || "—");
    const t = e.type || "";
    let icon = "fa-circle", color = "var(--muted)", txt = escapeHtml(t);
    if (t === "agent_exec") {
      icon = "fa-terminal"; color = "var(--attacker)";
      txt = "ran <code>" + escapeHtml((p.command || "").slice(0, 140)) + "</code> on <b>" +
        escapeHtml(p.node || "?") + "</b> → exit " + (p.exit_code != null ? p.exit_code : "?");
    } else if (t === "finding") {
      icon = "fa-bug"; color = "var(--warn)";
      txt = "reported <b>" + escapeHtml(p.title || "finding") + "</b>" + (p.cwe ? " (" + escapeHtml(p.cwe) + ")" : "");
    } else if (t === "agent_session") {
      icon = "fa-plug"; color = "var(--accent)";
      txt = "connected — " + escapeHtml(p.model || "agent") + (p.stance ? " as " + escapeHtml(p.stance) : "");
    } else if (t === "mitm_observe") {
      icon = "fa-user-secret"; color = "var(--mitm)";
      txt = "captured " + (p.packets != null ? p.packets : "?") + " packet(s)";
    } else if (t === "setup_step") {
      icon = "fa-screwdriver-wrench"; color = "var(--accent)";
      txt = "setup <code>" + escapeHtml((p.command || "").slice(0, 140)) + "</code> on <b>" + escapeHtml(p.node || "?") + "</b>";
    } else if (t.indexOf("setup") === 0) {
      icon = "fa-screwdriver-wrench"; color = "var(--accent)"; txt = escapeHtml(t.replace(/_/g, " "));
    } else if (t.indexOf("binding") >= 0) {
      icon = "fa-chess"; color = "var(--accent)";
      txt = escapeHtml(t.replace(/_/g, " ")) + (p.stance ? " (" + escapeHtml(p.stance) + ")" : "");
    }
    const full = e.ts || "";
    const tm = (full.match(/\d{2}:\d{2}:\d{2}/) || [full])[0];  // compact time; full on hover
    return '<div class="log-row"><span class="log-ic" style="color:' + color + '">' +
      '<i class="fa-solid ' + icon + '"></i></span>' +
      '<span class="log-ts mono faint" title="' + escapeHtml(full) + '">' + escapeHtml(tm) + "</span>" +
      '<span class="log-actor mono" title="' + actor + '">' + actor + "</span>" +
      '<span class="log-txt">' + txt + "</span></div>";
  }

  function engRenderLog(events) {
    const host = document.getElementById("log-stream");
    if (!host) return;
    const cnt = document.getElementById("log-count");
    if (cnt) cnt.textContent = events.length ? events.length + " event" + (events.length === 1 ? "" : "s") : "";
    host.innerHTML = events.length
      ? events.map(engLogLine).join("")
      : '<div class="empty" style="padding:24px">No activity yet — once your agent connects and runs a tool, it appears here live.</div>';
  }

  /* -- wiring & actions ------------------------------------------------------ */

  function engWireBoard() {
    document.querySelectorAll("#pos-board [data-eng]").forEach((btn) => {
      const act = btn.dataset.eng, name = btn.dataset.name ? decodeURIComponent(btn.dataset.name) : null;
      btn.addEventListener("click", () => {
        if (act === "pause" || act === "resume") {
          postJson("/api/arenas/" + engArena + "/bindings/" + encodeURIComponent(name) + "/" + act)
            .then(({ status, data }) => { if (status === 200) engRefresh(); else engErr(data.error || data.detail || "HTTP " + status); });
        } else if (act === "revoke") {
          if (!confirm("Revoke " + name + "'s access to this arena?")) return;
          fetch("/api/arenas/" + engArena + "/bindings/" + encodeURIComponent(name),
            { method: "DELETE", headers: { "X-CSRFToken": csrfToken() } })
            .then((r) => r.json().catch(() => ({}))).then(engRefresh);
        }
      });
    });
    document.querySelectorAll("#pos-board [data-pos-assign]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sel = document.getElementById("pos-stance"), key = document.getElementById("pos-key");
        if (sel) sel.value = btn.dataset.posAssign;
        if (key) key.focus();
      });
    });
  }

  function engWireCfg() {
    document.querySelectorAll("#cfg-actions [data-eng]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const act = btn.dataset.eng;
        if (act === "start") engStart();
        else if (act === "step") engStep();
        else if (act === "generate") engGenerate();
        else if (act === "finish") {
          if (confirm("Finish setup and revoke the configurator capability?")) engApi("/finish", "POST").then(engRefresh);
        }
      });
    });
  }

  function engGrant() {
    const stance = document.getElementById("pos-stance").value;
    const name = document.getElementById("pos-key").value.trim();
    if (!name) { engErr("Enter the agent key name to authorize (create one with auth.py create-key … agent)."); return; }
    postJson("/api/arenas/" + engArena + "/bindings", { agent_name: name, stance: stance || null })
      .then(({ status, data }) => {
        if (status === 200) { engErr(""); document.getElementById("pos-key").value = ""; engRefresh(); }
        else engErr(data.error || data.detail || "HTTP " + status);
      });
  }
  function engStart() {
    engApi("/start", "POST", {
      mode: document.getElementById("eng-mode").value,
      time_box_seconds: +document.getElementById("eng-tb").value || 1800,
      command_budget: +document.getElementById("eng-budget").value || 50,
      setup_egress: document.getElementById("eng-egress").checked,
    }).then((r) => { if (r.error) engCfgErr(r.error); else { engCfgErr(""); engRefresh(); } });
  }
  function engStep() {
    const command = document.getElementById("eng-cmd").value.trim();
    if (!command) return;
    engApi("/step", "POST", { node: document.getElementById("eng-node").value, command }).then((r) => {
      if (r.error) { engCfgErr(r.error); return; }
      engCfgErr("");
      const out = document.getElementById("eng-out");
      if (out) { out.hidden = false; out.textContent = "$ " + command + "\n" + (r.stdout || "") + (r.stderr || ""); }
      document.getElementById("eng-cmd").value = "";
      engRefresh();
    });
  }
  function engDecide(stepId, decision) {
    engApi("/proposals/" + stepId + "/" + decision, "POST").then((r) => { if (r.error) engCfgErr(r.error); engRefresh(); });
  }
  function engGenerate() {
    const btn = document.getElementById("eng-gen-btn"), msg = document.getElementById("eng-gen-msg");
    if (btn) btn.disabled = true;
    if (msg) msg.textContent = "Asking your connected model…";
    engApi("/generate-proposals", "POST").then((r) => {
      if (btn) btn.disabled = false;
      if (r.errors && r.errors.length) { if (msg) msg.textContent = r.errors[0]; return; }
      if (r.error || r.detail) { if (msg) msg.textContent = r.error || r.detail; return; }
      if (msg) msg.textContent = "Drafted " + (r.proposed || 0) + " step(s) — review below.";
      engRefresh();
    }).catch(() => { if (btn) btn.disabled = false; if (msg) msg.textContent = "request failed"; });
  }

  /* ---- agents console (live connections + activity trace) ------------- */
  let agentsTimer = null;
  let agentConns = [];   // latest connections (the agent config modal + usage graph read this)

  function initAgents() {
    let data = {};
    try { data = JSON.parse(document.getElementById("agents-data").textContent || "{}"); } catch (e) {}
    renderAgents(data);                       // first paint from embedded JSON (no flash)
    if (agentsTimer) clearInterval(agentsTimer);
    agentsTimer = setInterval(refreshAgents, 8000);
  }
  function refreshAgents() {
    fetch("/api/agents").then((r) => r.json()).then(renderAgents).catch(() => {});
  }

  function renderAgents(d) {
    d = d || {};
    const conns = d.connections || [];
    agentConns = conns;                       // shared with the config modal + usage graph
    const tl = d.timeline || [];
    const count = document.getElementById("agents-count");
    if (count) count.textContent = conns.length + " connection" + (conns.length === 1 ? "" : "s");

    const cw = document.getElementById("agents-connections");
    if (cw) {
      cw.innerHTML = conns.length
        ? '<div class="agent-grid">' + conns.map(agentCard).join("") + "</div>"
        : '<div class="muted" style="font-size:13px">No agents connected yet. Connect a bring-your-own agent through the MCP gateway (stance <b>attacker</b> or <b>configurator</b>); it appears here once it announces itself or runs a command.</div>';
    }
    agentUsage();

    const tw = document.getElementById("agents-timeline");
    if (tw) {
      tw.innerHTML = tl.length
        ? agentTimeline(tl)
        : '<div class="empty" style="padding:24px">No agent activity yet.</div>';
    }
  }

  function agentCard(c, idx) {
    const b = brandOf(c.provider);
    const dot = c.active ? "dot--active" : "dot--standby";
    // Clicking the card opens the agent CONFIG modal (details + actions) — not
    // a jump to the lab (the modal has an explicit "Open arena" action).
    return '<div class="agent-card" role="button" tabindex="0" onclick="Nidavellir.openAgentConfig(' + idx + ')">' +
      '<div class="agent-card__top">' +
        '<span class="badge badge--accent">' + escapeHtml(c.stance || "agent") + "</span>" +
        '<span class="dot ' + dot + '" title="' + (c.active ? "recent activity" : "idle") + '"></span>' +
      "</div>" +
      '<div class="agent-card__model">' +
        '<span class="agent-card__logo" style="background:' + b.color + '">' + b.svg + "</span>" +
        '<span class="mono">' + escapeHtml(c.model || b.name) + "</span></div>" +
      '<div class="muted" style="font-size:12px;margin:2px 0 8px">' + escapeHtml(b.name) + "</div>" +
      '<div class="agent-card__arena mono">' +
        escapeHtml(c.arena_name || "") + ' <span class="faint">' + escapeHtml((c.arena_id || "").slice(0, 8)) + "</span></div>" +
      '<div class="agent-card__stats">' +
        "<span><b>" + (c.commands || 0) + "</b> cmds</span>" +
        "<span><b>" + (c.findings || 0) + "</b> findings</span>" +
        '<span class="faint" title="last seen">' + escapeHtml(c.last_seen || "—") + "</span>" +
      "</div></div>";
  }

  /* ---- usage graph: per-model step consumption, filterable by stance ----- */
  let usageStance = "all";
  function _statBox(n, label) {
    return '<div class="usage-stat"><div class="usage-stat__n">' + n + '</div>' +
      '<div class="usage-stat__l">' + label + "</div></div>";
  }
  function agentUsage() {
    const wrap = document.getElementById("agents-usage");
    if (!wrap) return;
    const conns = agentConns || [];
    const stances = Array.from(new Set(conns.map((c) => c.stance || "agent"))).sort();
    if (usageStance !== "all" && !stances.includes(usageStance)) usageStance = "all";
    const shown = usageStance === "all" ? conns : conns.filter((c) => (c.stance || "agent") === usageStance);

    const byModel = {};
    shown.forEach((c) => {
      const k = c.model || brandOf(c.provider).name;
      const m = byModel[k] || (byModel[k] = { model: k, provider: c.provider, steps: 0, findings: 0, conns: 0 });
      m.steps += c.commands || 0; m.findings += c.findings || 0; m.conns += 1;
    });
    const models = Object.values(byModel).sort((a, b) => b.steps - a.steps);
    const totalSteps = models.reduce((s, m) => s + m.steps, 0);
    const totalFinds = models.reduce((s, m) => s + m.findings, 0);
    const maxSteps = Math.max.apply(null, models.map((m) => m.steps).concat([1]));

    const chips = '<div class="usage-filter">' +
      ['all'].concat(stances).map((s) =>
        '<button class="usage-chip' + (usageStance === s ? " on" : "") + '" data-stance="' + escapeHtml(s) + '">' +
        (s === "all" ? "All" : escapeHtml(s)) + "</button>").join("") + "</div>";

    const summary = '<div class="usage-summary">' +
      _statBox(totalSteps, "steps") + _statBox(totalFinds, "findings") +
      _statBox(models.length, "models") + _statBox(shown.length, "connections") + "</div>";

    const bars = models.length
      ? '<div class="usage-bars">' + models.map((m) => {
          const b = brandOf(m.provider);
          const pct = Math.round((m.steps / maxSteps) * 100);
          return '<div class="usage-row">' +
            '<span class="usage-row__logo" style="background:' + b.color + '">' + b.svg + "</span>" +
            '<div class="grow">' +
              '<div class="usage-row__head"><span class="mono">' + escapeHtml(m.model) + "</span>" +
                '<span class="usage-row__val mono">' + m.steps + " steps" + (m.findings ? " · " + m.findings + " find" : "") + "</span></div>" +
              '<div class="usage-bar"><div class="usage-bar__fill" style="width:' + pct + "%;background:" + b.color + '"></div></div>' +
              '<div class="usage-row__meta faint">' + m.conns + " connection" + (m.conns === 1 ? "" : "s") + " · " + escapeHtml(b.name) + "</div>" +
            "</div></div>";
        }).join("") + "</div>"
      : '<div class="muted" style="font-size:13px;margin-top:10px">No usage for this filter yet — steps accrue as agents run commands. ' +
        "(Token / $ cost needs the agent to report usage; this graphs <b>steps</b>, the platform's unit of agent work.)</div>";

    wrap.innerHTML = chips + summary + bars;
    wrap.querySelectorAll("[data-stance]").forEach((btn) =>
      btn.addEventListener("click", () => { usageStance = btn.dataset.stance; agentUsage(); }));
  }

  /* ---- agent config modal (opened from a connection card) --------------- */
  function openAgentConfig(idx) {
    const c = (agentConns || [])[idx];
    if (!c) return;
    const b = brandOf(c.provider);
    const arena = encodeURIComponent(c.arena_id || "");
    document.getElementById("agent-modal-head").innerHTML =
      '<span class="model-bubble" style="background:' + b.color + '">' + b.svg + "</span>" +
      '<div><div class="modal__title mono">' + escapeHtml(c.model || b.name) + "</div>" +
      '<div class="modal__sub">' + escapeHtml(b.name) + " · " + escapeHtml(c.stance || "agent") +
        (c.active ? ' · <span style="color:var(--ok)">active</span>' : " · idle") + "</div></div>";
    const kv = [
      ["Stance", c.stance || "agent"], ["Model", c.model || "—"], ["Provider", b.name],
      ["Arena", (c.arena_name || "—") + " · " + (c.arena_id || "").slice(0, 8)],
      ["Arena status", c.status || "—"], ["Steps", c.commands || 0], ["Findings", c.findings || 0],
      ["Last seen", c.last_seen || "—"], ["Agent key", c.actor || "—"],
    ];
    document.getElementById("agent-modal-kv").innerHTML = kv.map((r) =>
      "<dt>" + escapeHtml(r[0]) + "</dt><dd class='mono'>" + escapeHtml(String(r[1])) + "</dd>").join("");
    const msg = document.getElementById("agent-modal-msg");
    if (msg) { msg.textContent = ""; msg.className = "import-msg"; }
    // Render base action immediately; the binding-dependent actions (pause /
    // resume / revoke) resolve once we know whether a live binding exists and
    // whether it's currently paused (P2-11 kill-switch).
    renderAgentActions(arena, c.actor, null, true);
    if (c.actor) {
      fetch("/api/arenas/" + arena + "/bindings").then((r) => r.json())
        .then((d) => {
          const b = (d.bindings || []).find((x) => x.agent_name === c.actor) || null;
          renderAgentActions(arena, c.actor, b, false);
        })
        .catch(() => renderAgentActions(arena, c.actor, null, false));
    }
    document.getElementById("agent-modal").hidden = false;
  }
  // Build the agent-modal action row. `binding` is the live binding (or null if
  // the agent has no active binding); `loading` shows a transient hint while we
  // resolve it.
  function renderAgentActions(arena, name, binding, loading) {
    const el = document.getElementById("agent-modal-actions");
    if (!el) return;
    const acts = ['<a class="btn btn-primary" href="/arena/' + arena + '"><i class="fa-solid fa-up-right-from-square"></i> Open arena</a>'];
    const enc = name ? encodeURIComponent(name) : "";
    if (name && !loading && binding) {
      if (binding.paused) {
        acts.push('<button class="btn btn-primary" onclick="Nidavellir.resumeAgent(\'' + arena + "','" + enc +
          '\')"><i class="fa-solid fa-play"></i> Resume</button>');
      } else {
        acts.push('<button class="btn" onclick="Nidavellir.pauseAgent(\'' + arena + "','" + enc +
          '\')"><i class="fa-solid fa-pause"></i> Pause</button>');
      }
      acts.push('<button class="btn btn-danger" onclick="Nidavellir.revokeAgent(\'' + arena + "','" + enc +
        '\')"><i class="fa-solid fa-ban"></i> Kill binding</button>');
    } else if (name && loading) {
      acts.push('<span class="muted" style="font-size:12px;align-self:center">checking binding…</span>');
    }
    el.innerHTML = acts.join("");
  }
  function closeAgentConfig() {
    const m = document.getElementById("agent-modal");
    if (m) m.hidden = true;
  }
  // After a pause/resume/kill, re-resolve the binding so the action row reflects
  // the new state, and refresh the connection cards.
  function _reloadAgentBinding(arena, name) {
    fetch("/api/arenas/" + arena + "/bindings").then((r) => r.json())
      .then((d) => {
        const b = (d.bindings || []).find((x) => x.agent_name === decodeURIComponent(name)) || null;
        renderAgentActions(arena, decodeURIComponent(name), b, false);
      }).catch(() => {});
    refreshAgents();
  }
  function _agentMsg(cls, text) {
    const msg = document.getElementById("agent-modal-msg");
    if (msg) { msg.className = "import-msg " + (cls || ""); msg.textContent = text; }
  }
  function revokeAgent(arena, name) {
    fetch("/api/arenas/" + arena + "/bindings/" + name,
      { method: "DELETE", headers: { "X-CSRFToken": csrfToken() } })
      .then((r) => r.json().catch(() => ({})))
      .then((d) => {
        _agentMsg("ok", d.revoked ? "Binding killed." : (d.detail || "No active binding for this agent."));
        _reloadAgentBinding(arena, name);
      })
      .catch(() => {});
  }
  function pauseAgent(arena, name) {
    postJson("/api/arenas/" + arena + "/bindings/" + name + "/pause")
      .then(({ status, data }) => {
        _agentMsg(status === 200 ? "ok" : "err", status === 200 ? "Agent paused — actions are halted until resumed." : (data.error || data.detail || ("HTTP " + status)));
        _reloadAgentBinding(arena, name);
      })
      .catch(() => {});
  }
  function resumeAgent(arena, name) {
    postJson("/api/arenas/" + arena + "/bindings/" + name + "/resume")
      .then(({ status, data }) => {
        _agentMsg(status === 200 ? "ok" : "err", status === 200 ? "Agent resumed." : (data.error || data.detail || ("HTTP " + status)));
        _reloadAgentBinding(arena, name);
      })
      .catch(() => {});
  }

  function agentTimeline(tl) {
    return '<table class="table"><thead><tr><th>Time</th><th>Arena</th><th>Action</th><th>Actor</th><th>Detail</th></tr></thead><tbody>' +
      tl.map((e) =>
        '<tr><td class="mono faint" style="white-space:nowrap">' + escapeHtml(e.ts || "") + "</td>" +
        '<td class="mono faint"><a href="/arena/' + encodeURIComponent(e.arena_id || "") + '">' + escapeHtml((e.arena_id || "").slice(0, 8)) + "</a></td>" +
        "<td>" + agentTypeBadge(e.type) + "</td>" +
        "<td>" + escapeHtml(e.actor || "") + (e.stance ? ' <span class="faint">(' + escapeHtml(e.stance) + ")</span>" : "") + "</td>" +
        '<td class="mono" style="font-size:12px">' + escapeHtml(e.summary || "") + "</td></tr>"
      ).join("") + "</tbody></table>";
  }

  function agentTypeBadge(t) {
    const m = {
      agent_session: "accent", agent_exec: "ok", setup_step: "accent",
      setup_proposal: "warn", setup_proposal_decision: "info",
      setup_finished: "idle", finding: "ok",
    };
    return '<span class="badge badge--' + (m[t] || "idle") + '">' + escapeHtml((t || "?").replace(/_/g, " ")) + "</span>";
  }

  /* ---- scenario topology PREVIEW (pre-deploy, from the spec) ---------- */
  // The post-deploy #topo is built from provider outputs; this renders the
  // authored shape (nodes + segments + agent stances) BEFORE deploy — used on
  // the launch preview, the custom-builder live preview, the paste-to-import
  // preview, and the scenarios browser. Packet-Tracer style: each segment is a
  // network SWITCH, devices hang off their switch (laptop = attacker, server =
  // target, desktop = host, cloud = internet), with a deterministic star layout
  // (no force-directed overlap).
  const specCy = {}; // containerId -> cytoscape instance

  function postJson(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body || {}),
    }).then((r) =>
      r.json().then((d) => ({ status: r.status, data: d })).catch(() => ({ status: r.status, data: {} }))
    );
  }

  /* ---- HTTP research workspace (R1 slice 6): send / inspect / replay /
         attach — the console only presents; scope stays server-side ------- */
  let httpArena = null;
  let httpReadOnly = false;
  let httpReplayOf = null;

  function httpEsc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  function initHttpWorkspace() {
    const card = document.getElementById("http-card");
    if (!card) return;
    httpArena = card.dataset.arena;
    httpReadOnly = card.dataset.readonly === "1";
    httpLoad();
  }

  function httpLoad() {
    const list = document.getElementById("http-list");
    if (!list || !httpArena) return;
    fetch("/api/arenas/" + encodeURIComponent(httpArena) +
          "/http/transactions?limit=50")
      .then((r) => r.json())
      .then((d) => {
        const rows = d.transactions || [];
        if (!rows.length) {
          list.innerHTML =
            '<div class="card-pad muted" style="padding:18px">No stored transactions' +
            (httpReadOnly ? " from this engagement." : " yet — open Send request above.") + "</div>";
          return;
        }
        const body = rows.map((t) => {
          const req = t.request || {};
          return '<tr>' +
            '<td class="mono" style="white-space:nowrap">' + httpEsc((t.created_at || "").replace("T", " ").slice(0, 19)) + "</td>" +
            '<td><span class="badge badge--info">' + httpEsc(req.method) + "</span> <b>" +
              httpEsc(req.path) + "</b><div class=\"faint mono\" style=\"font-size:11px\">" + httpEsc(req.node) + "</div></td>" +
            '<td class="mono">' + httpEsc((t.response || {}).status) + "</td>" +
            '<td class="mono">' + httpEsc((t.response || {}).body_bytes) +
              ((t.response || {}).truncated ? ' <span class="badge badge--idle">cut</span>' : "") + "</td>" +
            '<td class="mono" style="font-size:11px" title="' + httpEsc(t.digest) + '">' +
              (t.replay_of ? '<i class="fa-solid fa-rotate-left" title="replay of ' + httpEsc(t.replay_of.slice(0, 19)) + '…"></i> ' : "") +
              httpEsc(String(t.digest).slice(7, 19)) + "…</td>" +
            '<td style="white-space:nowrap">' +
              '<button class="btn btn-sm" onclick="Nidavellir.httpInspect(\'' + t.digest + '\')"><i class="fa-solid fa-magnifying-glass"></i></button> ' +
              (httpReadOnly ? "" :
                '<button class="btn btn-sm" title="Replay with edits" onclick="Nidavellir.httpReplay(\'' + t.digest + '\')"><i class="fa-solid fa-rotate-left"></i></button> ') +
              '<button class="btn btn-sm" title="Attach to finding" onclick="Nidavellir.httpAttach(\'' + t.digest + '\')"><i class="fa-solid fa-paperclip"></i></button>' +
            "</td></tr>";
        }).join("");
        list.innerHTML =
          '<table class="table"><thead><tr><th>Time</th><th>Request</th><th>Status</th>' +
          "<th>Bytes</th><th>Digest</th><th></th></tr></thead><tbody>" + body + "</tbody></table>";
      })
      .catch(() => { list.innerHTML = '<div class="card-pad muted" style="padding:18px">Transaction store unavailable.</div>'; });
  }

  function httpToggleForm() {
    const form = document.getElementById("http-form");
    if (!form) return;
    form.hidden = !form.hidden;
    if (!form.hidden && httpReplayOf === null) {
      const err = document.getElementById("http-err");
      if (err) err.textContent = "";
    }
  }

  function httpRefresh() { httpLoad(); }

  function httpParseParams(text) {
    const out = {};
    new URLSearchParams(text || "").forEach((v, k) => { if (k) out[k] = v; });
    return out;
  }

  function httpParseHeaders(text) {
    const out = {};
    String(text || "").split("\n").forEach((line) => {
      const i = line.indexOf(":");
      if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    });
    return out;
  }

  function httpSend() {
    const err = document.getElementById("http-err");
    const node = document.getElementById("http-node").value;
    if (!node) { if (err) err.textContent = "This arena has no web-capable target node."; return; }
    const payload = {
      node: node,
      path: document.getElementById("http-path").value || "/",
      method: document.getElementById("http-method").value,
    };
    const params = httpParseParams(document.getElementById("http-params").value);
    if (Object.keys(params).length) payload.params = params;
    const headers = httpParseHeaders(document.getElementById("http-headers").value);
    if (Object.keys(headers).length) payload.headers = headers;
    let url;
    if (httpReplayOf) {
      url = "/api/arenas/" + encodeURIComponent(httpArena) + "/http/transactions/" +
            encodeURIComponent(httpReplayOf) + "/replay";
      payload.body = document.getElementById("http-body").value;
    } else {
      url = "/api/arenas/" + encodeURIComponent(httpArena) + "/http/request";
      const body = document.getElementById("http-body").value;
      if (body) payload.body = body;
    }
    postJson(url, payload).then(({ status, data }) => {
      if (status === 200) {
        httpReplayOf = null;
        if (err) err.textContent = "";
        document.getElementById("http-form").hidden = true;
        httpLoad();
      } else if (err) {
        err.textContent = (data && (data.detail || data.error)) || ("HTTP " + status);
      }
    }).catch(() => { if (err) err.textContent = "request failed"; });
  }

  function httpFillForm(req) {
    document.getElementById("http-node").value = req.node || "";
    document.getElementById("http-method").value = (req.method || "GET").toUpperCase();
    document.getElementById("http-path").value = req.path || "/";
    document.getElementById("http-params").value =
      Object.entries(req.params || {}).map(([k, v]) => k + "=" + v).join("&");
    document.getElementById("http-headers").value =
      Object.entries(req.headers || {}).map(([k, v]) => k + ": " + v).join("\n");
    document.getElementById("http-body").value = req.body || "";
  }

  function httpInspect(digest) {
    fetch("/api/arenas/" + encodeURIComponent(httpArena) +
          "/http/transactions/" + encodeURIComponent(digest))
      .then((r) => r.json())
      .then((d) => {
        const env = d.transaction || {};
        const panel = document.getElementById("http-inspect");
        document.getElementById("http-inspect-title").textContent = digest;
        panel.dataset.digest = digest;
        document.getElementById("http-inspect-request").textContent =
          JSON.stringify(env.request || {}, null, 2);
        document.getElementById("http-inspect-response").textContent =
          JSON.stringify(env.response || {}, null, 2);
        panel.hidden = false;
      })
      .catch(() => {});
  }

  function httpReplay(digest) {
    if (httpReadOnly) return;
    fetch("/api/arenas/" + encodeURIComponent(httpArena) +
          "/http/transactions/" + encodeURIComponent(digest))
      .then((r) => r.json())
      .then((d) => {
        const env = d.transaction || {};
        httpFillForm(env.request || {});
        httpReplayOf = digest;
        const form = document.getElementById("http-form");
        form.hidden = false;
        const err = document.getElementById("http-err");
        if (err) err.textContent = "Replaying " + digest.slice(7, 19) + "… — edits produce a linked copy";
        form.scrollIntoView({ behavior: "smooth", block: "center" });
      })
      .catch(() => {});
  }

  function httpAttach(digest) {
    const input = document.getElementById("mf-transactions");
    if (!input) return;
    const existing = input.value.trim().split(/[\s,]+/).filter(Boolean);
    if (!existing.includes(digest)) existing.push(digest);
    input.value = existing.join(" ");
    const form = document.getElementById("mf-form");
    if (form) {
      form.hidden = false;
      form.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function httpAttachFromInspect() {
    const panel = document.getElementById("http-inspect");
    if (panel && panel.dataset.digest) httpAttach(panel.dataset.digest);
  }

  /* ---- Confined PoC workspace (NV-03) ---------------------------------- */
  let pocArena = null;
  let pocReadOnly = false;
  let pocPollTimer = null;

  function initPocWorkspace() {
    const card = document.getElementById("poc-card");
    if (!card) return;
    pocArena = card.dataset.arena;
    pocReadOnly = card.dataset.readonly === "1";
    pocLoad();
  }

  function pocToggleForm() {
    const form = document.getElementById("poc-form");
    if (form && !pocReadOnly) form.hidden = !form.hidden;
  }

  function pocLoad() {
    const list = document.getElementById("poc-list");
    if (!list || !pocArena) return;
    fetch("/api/arenas/" + encodeURIComponent(pocArena) + "/poc-jobs")
      .then((r) => r.json()).then((data) => {
        const jobs = data.jobs || [];
        if (!jobs.length) {
          list.innerHTML = '<div class="card-pad muted" style="padding:18px">No confined PoC jobs yet.</div>';
          return;
        }
        let active = false;
        const rows = jobs.map((job) => {
          active = active || job.state === "queued" || job.state === "running";
          const canCancel = !pocReadOnly && (job.state === "queued" || job.state === "running");
          return "<tr><td class=\"mono\">" + httpEsc((job.created_at || "").replace("T", " ").slice(0, 19)) +
            "</td><td><span class=\"badge badge--" +
            (job.state === "succeeded" ? "ok" : job.state === "failed" ? "danger" : "idle") + "\">" +
            httpEsc(job.state) + "</span><div class=\"faint mono\" style=\"font-size:11px\">" +
            httpEsc(job.cleanup_state) + " cleanup</div></td><td>" + httpEsc(job.target_node || "networkless") +
            "</td><td class=\"mono\" title=\"" + httpEsc(job.input_digest) + "\">" +
            httpEsc(String(job.input_digest || "").slice(7, 19)) + "…</td><td style=\"white-space:nowrap\">" +
            '<button class="btn btn-sm" onclick="Nidavellir.pocInspect(\'' + httpEsc(job.id) + '\')"><i class="fa-solid fa-magnifying-glass"></i></button> ' +
            (canCancel ? '<button class="btn btn-sm btn-danger" onclick="Nidavellir.pocCancel(\'' + httpEsc(job.id) + '\')"><i class="fa-solid fa-stop"></i></button>' : "") +
            "</td></tr>";
        }).join("");
        list.innerHTML = '<table class="table"><thead><tr><th>Submitted</th><th>State</th><th>Target</th><th>Input</th><th></th></tr></thead><tbody>' + rows + "</tbody></table>";
        if (pocPollTimer) clearTimeout(pocPollTimer);
        if (active) pocPollTimer = setTimeout(pocLoad, 1500);
      }).catch(() => {
        list.innerHTML = '<div class="card-pad muted" style="padding:18px">PoC job store unavailable.</div>';
      });
  }

  function pocSubmit() {
    const err = document.getElementById("poc-err");
    const source = document.getElementById("poc-source").value;
    const files = (document.getElementById("poc-files").value || "")
      .split(",").map((v) => v.trim()).filter(Boolean);
    const payload = {
      source: source,
      target_node: document.getElementById("poc-target").value || null,
      transfer_files: files,
      timeout_seconds: Number(document.getElementById("poc-timeout").value || 30),
      memory_mb: Number(document.getElementById("poc-memory").value || 128),
      pids: Number(document.getElementById("poc-pids").value || 32),
      idempotency_key: "console-" + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())),
    };
    if (err) err.textContent = "Submitting…";
    postJson("/api/arenas/" + encodeURIComponent(pocArena) + "/poc-jobs", payload)
      .then(({ status, data }) => {
        if (status === 202) {
          if (err) err.textContent = "Accepted";
          document.getElementById("poc-form").hidden = true;
          pocLoad();
        } else if (err) err.textContent = data.error || data.detail || ("HTTP " + status);
      }).catch(() => { if (err) err.textContent = "submission failed"; });
  }

  function pocInspect(jobId) {
    fetch("/api/arenas/" + encodeURIComponent(pocArena) + "/poc-jobs/" + encodeURIComponent(jobId))
      .then((r) => r.json()).then((data) => {
        const job = data.job || {};
        const result = job.result || {};
        const artifacts = (result.artifacts || []).map((a) => ({
          path: a.path, bytes: a.bytes, sha256: a.sha256
        }));
        document.getElementById("poc-inspect-title").textContent = job.id || jobId;
        document.getElementById("poc-inspect-output").textContent = [
          "state: " + (job.state || "unknown"),
          "cleanup: " + (job.cleanup_state || "unknown"),
          "input: " + (job.input_digest || ""),
          "stdout sha256: " + (result.stdout_sha256 || ""),
          "stderr sha256: " + (result.stderr_sha256 || ""),
          "\nstdout:\n" + (result.stdout || ""),
          "\nstderr:\n" + (result.stderr || ""),
          "\nartifacts:\n" + JSON.stringify(artifacts, null, 2),
          result.error ? "\nerror: " + result.error : "",
          job.cleanup_error ? "\ncleanup error: " + job.cleanup_error : "",
        ].join("\n");
        document.getElementById("poc-inspect").hidden = false;
      });
  }

  function pocCancel(jobId) {
    postJson("/api/arenas/" + encodeURIComponent(pocArena) + "/poc-jobs/" +
      encodeURIComponent(jobId) + "/cancel", {}).then(() => pocLoad());
  }

  /* ---- Findings card: operator verify + manual add (arena detail) -------- */
  window.copyPoc = function (btn) {
    const pre = btn.parentNode.querySelector("pre");
    if (!pre) return;
    navigator.clipboard.writeText(pre.textContent).then(() => {
      const i = btn.querySelector("i");
      const prev = i ? i.className : null;
      if (i) i.className = "fa-solid fa-check";
      setTimeout(() => { if (i && prev) i.className = prev; }, 1200);
    });
  };
  window.toggleManualFinding = function () {
    const f = document.getElementById("mf-form");
    if (f) f.hidden = !f.hidden;
  };
  window.verifyFinding = function (fid, verdict) {
    const card = document.getElementById("findings-card");
    if (!card) return;
    const evidence = verdict === "confirmed"
      ? prompt("Immutable evidence digest (sha256:…):") : null;
    if (verdict === "confirmed" && !evidence) return;
    postJson("/api/arenas/" + card.dataset.arena + "/findings/" + encodeURIComponent(fid) + "/verify",
      { verdict: verdict, evidence_digest: evidence })
      .then(({ status, data }) => {
        if (status === 200) location.reload();
        else alert(data.error || data.detail || "HTTP " + status);
      });
  };
  window.addManualFinding = function () {
    const card = document.getElementById("findings-card");
    if (!card) return;
    const err = document.getElementById("mf-err");
    const title = (document.getElementById("mf-title").value || "").trim();
    if (!title) { if (err) err.textContent = "Title is required."; return; }
    postJson("/api/arenas/" + card.dataset.arena + "/findings/manual", {
      title: title,
      cwe: (document.getElementById("mf-cwe").value || "").trim(),
      node: (document.getElementById("mf-node").value || "").trim(),
      evidence: (document.getElementById("mf-evidence").value || "").trim(),
      poc: (document.getElementById("mf-poc").value || "").trim(),
      evidence_artifact_digests: (document.getElementById("mf-artifact").value || "").trim()
        ? [(document.getElementById("mf-artifact").value || "").trim()] : [],
      transaction_digests: (document.getElementById("mf-transactions")?.value || "").trim()
        .split(/[\s,]+/).filter(Boolean),
    }).then(({ status, data }) => {
      if (status === 200) location.reload();
      else if (err) err.textContent = data.error || data.detail || "HTTP " + status;
    });
  };

  // device icons — inline 2D line-art (Packet-Tracer flavour). Colour is baked
  // per kind because a Cytoscape background-image can't be tinted by CSS.
  function _icon(body, color) {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" ' +
      'stroke="' + color + '" stroke-width="2.3" stroke-linecap="round" ' +
      'stroke-linejoin="round">' + body + "</svg>";
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
  }
  const HOST_COLOR = "#9aa6bd";
  const EDGE_COLOR = "#46506a";
  const ICON = {
    foothold: _icon('<rect x="9" y="11" width="30" height="19" rx="2"/><path d="M4 37h40l-3.5-7H7.5z"/><path d="M19.5 16.5l-3 3 3 3M28.5 16.5l3 3-3 3"/>', C.danger),
    target: _icon('<rect x="11" y="6" width="26" height="14" rx="2"/><rect x="11" y="24" width="26" height="14" rx="2"/><path d="M16 13h2M16 31h2"/><circle cx="31" cy="13" r="1.5"/><circle cx="31" cy="31" r="1.5"/>', C.warn),
    host: _icon('<rect x="7" y="9" width="34" height="22" rx="2"/><path d="M18.5 36h11M24 31v5M15 40h18"/>', HOST_COLOR),
    switch: _icon('<rect x="4" y="17" width="40" height="13" rx="2"/><path d="M12 30v5M20 30v5M28 30v5M36 30v5"/><path d="M14 23.5h6M28 23.5h6M22 20.5l-4 3 4 3M26 20.5l4 3-4 3"/>', C.accent),
    cloud: _icon('<path d="M14.5 35h18a7.5 7.5 0 0 0 .8-15A9.5 9.5 0 0 0 15 17a6.8 6.8 0 0 0-.5 18z"/>', C.muted),
  };

  const SPEC_STYLE = [
    { selector: "node", style: {
        label: "data(label)", "text-wrap": "wrap", "text-max-width": "108px",
        "text-valign": "bottom", "text-halign": "center", "text-margin-y": 6,
        "font-size": "10.5px", "font-family": "monospace", color: C.text,
        // a faint pill behind every label so a line passing near it never makes
        // the text unreadable (the labels read as chips, not "text on wires").
        "text-background-color": C.bg, "text-background-opacity": 0.82,
        "text-background-padding": "2px", "text-background-shape": "round-rectangle",
        "background-color": "transparent", "background-opacity": 0,
        "background-image": "data(icon)", "background-fit": "contain",
        "background-clip": "none", "border-width": 0, shape: "rectangle",
        width: 44, height: 44,
    }},
    // hubs sit at the TOP of their star with edges fanning DOWN — put their
    // label ABOVE the icon so the (blue) segment/IP text never lies on the lines.
    { selector: "node.switch", style: { width: 58, height: 30, color: C.accent,
        "font-family": "inherit", "font-size": "10px",
        "text-valign": "top", "text-margin-y": -7 } },
    { selector: "node.cloud", style: { width: 58, height: 40, color: C.muted,
        "font-size": "10px", "text-valign": "top", "text-margin-y": -6 } },
    // a foothold that bridges segments sits above the switches (edges go down) →
    // its label goes above too; leaf devices keep their label below.
    { selector: "node.bridge", style: { "text-valign": "top", "text-margin-y": -7 } },
    { selector: "node.foothold", style: { color: C.danger } },
    { selector: "node.target", style: { color: C.warn } },
    { selector: "node.host", style: { color: HOST_COLOR } },
    { selector: "node.dead", style: { opacity: 0.4 } },
    { selector: "edge", style: {
        width: 2, "line-color": EDGE_COLOR, "curve-style": "straight",
        "target-arrow-shape": "none",
    }},
    { selector: "edge.wan", style: { "line-style": "dashed", "line-color": C.muted, opacity: 0.5, width: 1.6 } },
  ];

  // geometry (graph units; Cytoscape fits + zooms to the container)
  const ROW = 4, HOST_GAP = 128, SEG_GAP = 64;
  const SWITCH_Y = 0, HOST_Y = 152, ROW_STEP = 116, BRIDGE_Y = -150, CLOUD_Y = -300;

  function specModel(topo) {
    let segments = (topo.segments || []).slice();
    const segSet = new Set(segments.map((s) => s.name));
    const nodes = (topo.nodes || []).map((n) => ({
      name: n.name, kind: n.kind, entrypoint: n.entrypoint, stance: n.stance,
      ports: n.ports || [], dead: !!n.dead,
      segs: (n.segments || []).filter((s) => segSet.has(s)),
    }));
    if (!segments.length && nodes.length) { // no segments declared → one LAN
      segments = [{ name: "lan", cidr: null }];
      nodes.forEach((n) => { n.segs = ["lan"]; });
    }
    return { segments, nodes };
  }

  function specElements(topo) {
    const { segments, nodes } = specModel(topo);
    const bridge = new Set(nodes.filter((n) => n.segs.length >= 2).map((n) => n.name));
    const leavesBySeg = {};
    segments.forEach((s) => (leavesBySeg[s.name] = []));
    nodes.forEach((n) => {
      if (bridge.has(n.name)) return;
      const seg = n.segs[0] || (segments[0] && segments[0].name);
      if (seg && leavesBySeg[seg]) leavesBySeg[seg].push(n);
    });

    const pos = {}, switchX = {};
    let cursorX = 0;
    segments.forEach((s) => {
      const leaves = leavesBySeg[s.name] || [];
      const perRow = Math.min(Math.max(leaves.length, 1), ROW);
      const cx = cursorX + ((perRow - 1) * HOST_GAP) / 2;
      switchX[s.name] = cx;
      pos["seg_" + s.name] = { x: cx, y: SWITCH_Y };
      leaves.forEach((n, i) => {
        const row = Math.floor(i / ROW);
        const inRow = Math.min(leaves.length - row * ROW, ROW);
        const x = cx - ((inRow - 1) * HOST_GAP) / 2 + (i % ROW) * HOST_GAP;
        pos["node_" + n.name] = { x, y: HOST_Y + row * ROW_STEP };
      });
      cursorX += Math.max(perRow, 1) * HOST_GAP + SEG_GAP;
    });

    const bridges = nodes.filter((n) => bridge.has(n.name));
    bridges.forEach((n, i) => {
      const xs = n.segs.map((s) => switchX[s]).filter((x) => x != null);
      const mx = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
      pos["node_" + n.name] = { x: mx + (i - (bridges.length - 1) / 2) * HOST_GAP, y: BRIDGE_Y };
    });

    const sub = (n) => {
      const s = n.kind === "foothold" ? (n.stance || "attacker")
        : (n.kind === "target" && n.ports.length ? ":" + n.ports.join(",") : "");
      // don't repeat the node name on the second line (e.g. a node literally
      // named "attacker" whose stance is also "attacker" → shown once).
      return s && s.toLowerCase() === String(n.name).toLowerCase() ? "" : s;
    };

    const els = [];
    segments.forEach((s) => els.push({
      group: "nodes", classes: "switch",
      data: { id: "seg_" + s.name, label: s.name + (s.cidr ? "\n" + s.cidr : ""), icon: ICON.switch },
      position: pos["seg_" + s.name], grabbable: false,
    }));
    nodes.forEach((n) => {
      const s = sub(n);
      els.push({
        group: "nodes",
        classes: "device " + n.kind + (bridge.has(n.name) ? " bridge" : "") + (n.dead ? " dead" : ""),
        data: { id: "node_" + n.name, label: n.name + (s ? "\n" + s : ""), icon: ICON[n.kind] || ICON.host },
        position: pos["node_" + n.name], grabbable: false,
      });
      (n.segs.length ? n.segs : [segments[0] && segments[0].name]).forEach((sg) => {
        if (sg) els.push({ group: "edges", data: { source: "node_" + n.name, target: "seg_" + sg } });
      });
    });
    if (topo.egress === "open" && segments.length) {
      const allX = Object.values(switchX);
      const midX = allX.reduce((a, b) => a + b, 0) / allX.length;
      els.push({ group: "nodes", classes: "cloud", grabbable: false,
        data: { id: "inet", label: "internet", icon: ICON.cloud }, position: { x: midX, y: CLOUD_Y } });
      segments.forEach((s) =>
        els.push({ group: "edges", classes: "wan", data: { source: "inet", target: "seg_" + s.name } }));
    }
    return els;
  }

  function renderSpecTopology(containerId, topo) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (typeof cytoscape === "undefined") {
      container.innerHTML = '<div class="topo-empty">topology viewer unavailable</div>';
      return;
    }
    if (specCy[containerId]) { specCy[containerId].destroy(); delete specCy[containerId]; }
    if (!topo || !(topo.nodes || []).length) {
      container.innerHTML = '<div class="topo-empty"><i class="fa-solid fa-diagram-project"></i> Nothing to preview yet</div>';
      return;
    }
    container.innerHTML = "";
    specCy[containerId] = cytoscape({
      container, elements: specElements(topo), style: SPEC_STYLE,
      layout: { name: "preset", padding: 36, fit: true },
      autoungrabify: true, boxSelectionEnabled: false,
      minZoom: 0.3, maxZoom: 2.2, wheelSensitivity: 0.25,
    });
  }

  /* ---- launch page: scenario / custom / import previews --------------- */
  function initScenarioPreview() {
    const selected = (el) => (el ? Array.from(el.selectedOptions).map((o) => o.value) : []);
    const continueWithImportedChallenge = (scenarioId) => {
      const params = new URLSearchParams();
      const purposeInput = document.querySelector('[name="engagement_purpose"]');
      const participantInput = document.querySelector('[name="participant_mode"]');
      const timeBoxInput = document.querySelector('[name="engagement_time_box_seconds"]');
      if (purposeInput && purposeInput.value) params.set("purpose", purposeInput.value);
      if (participantInput && participantInput.value) params.set("participant_mode", participantInput.value);
      if (timeBoxInput && timeBoxInput.value) params.set("engagement_time_box_seconds", timeBoxInput.value);
      if (scenarioId) params.set("scenario", scenarioId);
      window.location.href = "/launch" + (params.toString() ? "?" + params.toString() : "");
    };

    // predefined scenario → topology of the registered scenario
    const sel = document.querySelector('select[name="scenario"]');
    const loadScenario = () => {
      const id = sel && sel.value;
      if (!id) { renderSpecTopology("scenario-preview", null); return; }
      fetch("/api/scenarios/" + encodeURIComponent(id) + "/topology")
        .then((r) => r.json())
        .then((d) => renderSpecTopology("scenario-preview", d && d.topology))
        .catch(() => renderSpecTopology("scenario-preview", null));
    };
    if (sel) { sel.addEventListener("change", loadScenario); loadScenario(); }

    // custom builder → live preview from catalog picks
    const atk = document.querySelector('select[name="attackers"]');
    const vic = document.querySelector('select[name="victims"]');
    const cMsg = document.getElementById("custom-msg");
    const loadCustom = () => {
      const attackers = selected(atk), victims = selected(vic);
      if (!attackers.length || !victims.length) {
        renderSpecTopology("custom-preview", null);
        if (cMsg) cMsg.textContent = "Pick an attacker and at least one target to preview.";
        return;
      }
      postJson("/api/scenarios/preview", { picks: { attackers, victims } }).then(({ data }) => {
        if (data.valid) { renderSpecTopology("custom-preview", data.topology); if (cMsg) cMsg.textContent = ""; }
        else { renderSpecTopology("custom-preview", null); if (cMsg) cMsg.textContent = (data.errors || ["invalid selection"])[0]; }
      });
    };
    if (atk) atk.addEventListener("change", loadCustom);
    if (vic) vic.addEventListener("change", loadCustom);

    // import: paste a v3 spec → validate/preview → persist
    const ta = document.getElementById("import-spec");
    const idIn = document.getElementById("import-id");
    const iMsg = document.getElementById("import-msg");
    const pv = document.getElementById("import-preview-btn");
    const imp = document.getElementById("import-do-btn");
    if (pv) pv.addEventListener("click", () => {
      const spec = ta ? ta.value.trim() : "";
      if (!spec) { if (iMsg) { iMsg.className = "import-msg err"; iMsg.textContent = "Paste a scenario spec (YAML or JSON) first."; } return; }
      postJson("/api/scenarios/preview", { spec }).then(({ data }) => {
        if (data.valid) {
          renderSpecTopology("import-preview", data.topology);
          const w = (data.warnings || []).length ? "  ⚠ " + data.warnings.join("; ") : "";
          if (iMsg) { iMsg.className = "import-msg ok"; iMsg.textContent = "Valid ✓ " + (data.summary ? data.summary.nodes + " node(s)" : "") + w; }
          if (idIn && !idIn.value && data.suggested_id) idIn.value = data.suggested_id;
        } else {
          renderSpecTopology("import-preview", null);
          if (iMsg) { iMsg.className = "import-msg err"; iMsg.textContent = "Invalid: " + (data.errors || ["spec rejected"]).join("; "); }
        }
      });
    });
    if (imp) imp.addEventListener("click", () => {
      const spec = ta ? ta.value.trim() : "";
      if (!spec) return;
      const id = idIn ? idIn.value.trim() : "";
      postJson("/api/scenarios/import", { spec, id: id || null }).then(({ status, data }) => {
        if (status === 200) { continueWithImportedChallenge(data.id || id); }
        else if (iMsg) { iMsg.className = "import-msg err"; iMsg.textContent = "Import failed: " + (data.error || ("HTTP " + status)); }
      });
    });

    // Vulhub: env path → deterministic convert → preview/import
    const vhPath = document.getElementById("vh-path");
    const vhRef = document.getElementById("vh-ref");
    const vhId = document.getElementById("vh-id");
    const vhAtk = document.getElementById("vh-attacker");
    const vhMsg = document.getElementById("vh-msg");
    const vhPv = document.getElementById("vh-preview-btn");
    const vhDo = document.getElementById("vh-do-btn");
    const vhBody = () => ({
      path: vhPath ? vhPath.value.trim() : "",
      ref: vhRef ? vhRef.value.trim() : "",
      include_attacker: vhAtk ? vhAtk.checked : true,
    });
    if (vhPv) vhPv.addEventListener("click", () => {
      const b = vhBody();
      if (!b.path) { if (vhMsg) { vhMsg.className = "import-msg err"; vhMsg.textContent = "Enter a Vulhub environment path first."; } return; }
      if (vhMsg) { vhMsg.className = "import-msg"; vhMsg.textContent = "Fetching from GitHub…"; }
      postJson("/api/scenarios/import/vulhub", Object.assign(b, { dry_run: true })).then(({ status, data }) => {
        if (status === 200 && data.valid) {
          renderSpecTopology("vh-preview", data.topology);
          const w = (data.warnings || []).length ? "  ⚠ " + data.warnings.join("; ") : "";
          if (vhMsg) { vhMsg.className = "import-msg ok"; vhMsg.textContent = "Valid ✓ " + (data.summary ? data.summary.nodes + " node(s)" : "") + w; }
          if (vhId && !vhId.value && data.suggested_id) vhId.value = data.suggested_id;
        } else {
          renderSpecTopology("vh-preview", null);
          if (vhMsg) { vhMsg.className = "import-msg err"; vhMsg.textContent = (data.errors ? data.errors.join("; ") : (data.error || ("HTTP " + status))); }
        }
      });
    });
    if (vhDo) vhDo.addEventListener("click", () => {
      const b = vhBody();
      if (!b.path) return;
      if (vhId && vhId.value.trim()) b.id = vhId.value.trim();
      postJson("/api/scenarios/import/vulhub", b).then(({ status, data }) => {
        if (status === 200) { continueWithImportedChallenge(data.id || (vhId && vhId.value.trim())); }
        else if (vhMsg) { vhMsg.className = "import-msg err"; vhMsg.textContent = "Import failed: " + (data.error || (data.detail) || ("HTTP " + status)); }
      });
    });

    // generate: prompt → operator's connected model → candidate spec → review/import
    const genPrompt = document.getElementById("gen-prompt");
    const genPc = document.getElementById("gen-provider-class");
    const genId = document.getElementById("gen-id");
    const genMsg = document.getElementById("gen-msg");
    const genDo = document.getElementById("gen-do-btn");
    const genSpec = document.getElementById("gen-spec");
    const genSpecWrap = document.getElementById("gen-spec-wrap");
    const genImportRow = document.getElementById("gen-import-row");
    const genReval = document.getElementById("gen-revalidate-btn");
    const genImport = document.getElementById("gen-import-btn");
    const genDiffBtn = document.getElementById("gen-diff-btn");
    const genDiff = document.getElementById("gen-diff");
    let genDraft = "";   // the model's original spec, for the "review edits" diff
    const genShowReview = (show) => {
      if (genSpecWrap) genSpecWrap.hidden = !show;
      if (genImportRow) genImportRow.hidden = !show;
      if (!show && genDiff) genDiff.hidden = true;
    };
    if (genDo) genDo.addEventListener("click", () => {
      const prompt = genPrompt ? genPrompt.value.trim() : "";
      if (!prompt) { if (genMsg) { genMsg.className = "import-msg err"; genMsg.textContent = "Describe the arena you want first."; } return; }
      if (genMsg) { genMsg.className = "import-msg"; genMsg.textContent = "Generating with your connected model…"; }
      genDo.disabled = true;
      const body = { prompt };
      if (genPc && genPc.value) body.provider_class = genPc.value;
      postJson("/api/scenarios/generate", body).then(({ status, data }) => {
        genDo.disabled = false;
        if (status === 409) {
          genShowReview(false); renderSpecTopology("gen-preview", null);
          if (genMsg) { genMsg.className = "import-msg err"; genMsg.textContent = "No model connected — set one up via the model bubble (top-right) first."; }
          return;
        }
        if (status === 200 && data.valid) {
          genDraft = JSON.stringify(data.spec, null, 2);
          if (genSpec) genSpec.value = genDraft;
          genShowReview(true);
          renderSpecTopology("gen-preview", data.topology);
          if (genId && !genId.value && data.suggested_id) genId.value = data.suggested_id;
          const w = (data.warnings || []).length ? "  ⚠ " + data.warnings.join("; ") : "";
          if (genMsg) { genMsg.className = "import-msg ok"; genMsg.textContent = "Generated ✓ " + (data.summary ? data.summary.nodes + " node(s)" : "") + w + " — review below, then import."; }
        } else {
          renderSpecTopology("gen-preview", null);
          // Show the model's raw reply (when it produced no usable spec) so the operator can adjust the prompt.
          if (data.raw && genSpec) { genSpec.value = data.raw; genShowReview(true); }
          else genShowReview(false);
          if (genMsg) { genMsg.className = "import-msg err"; genMsg.textContent = "Couldn't generate a valid spec: " + (data.errors ? data.errors.join("; ") : (data.error || data.detail || ("HTTP " + status))); }
        }
      }).catch(() => {
        genDo.disabled = false;
        if (genMsg) { genMsg.className = "import-msg err"; genMsg.textContent = "Generation request failed (network/timeout)."; }
      });
    });
    if (genReval) genReval.addEventListener("click", () => {
      const spec = genSpec ? genSpec.value.trim() : "";
      if (!spec) return;
      postJson("/api/scenarios/preview", { spec }).then(({ data }) => {
        if (data.valid) {
          renderSpecTopology("gen-preview", data.topology);
          if (genId && !genId.value && data.suggested_id) genId.value = data.suggested_id;
          const w = (data.warnings || []).length ? "  ⚠ " + data.warnings.join("; ") : "";
          if (genMsg) { genMsg.className = "import-msg ok"; genMsg.textContent = "Valid ✓ " + (data.summary ? data.summary.nodes + " node(s)" : "") + w; }
        } else {
          renderSpecTopology("gen-preview", null);
          if (genMsg) { genMsg.className = "import-msg err"; genMsg.textContent = "Invalid: " + (data.errors || ["spec rejected"]).join("; "); }
        }
      });
    });
    if (genImport) genImport.addEventListener("click", () => {
      const spec = genSpec ? genSpec.value.trim() : "";
      if (!spec) return;
      const id = genId ? genId.value.trim() : "";
      postJson("/api/scenarios/import", { spec, id: id || null }).then(({ status, data }) => {
        if (status === 200) { continueWithImportedChallenge(data.id || id); }
        else if (genMsg) { genMsg.className = "import-msg err"; genMsg.textContent = "Import failed: " + (data.error || data.detail || ("HTTP " + status)); }
      });
    });
    // review-gate diff: what the operator changed vs the model's original draft
    if (genDiffBtn) genDiffBtn.addEventListener("click", () => {
      if (!genDiff) return;
      if (!genDiff.hidden) { genDiff.hidden = true; return; }   // toggle off
      const cur = genSpec ? genSpec.value : "";
      const rows = lineDiff(genDraft, cur);
      const changed = rows.some((r) => r.t !== " ");
      genDiff.hidden = false;
      if (!changed) {
        genDiff.textContent = "No edits — importing the model's spec exactly as generated.";
        genDiff.className = "diffview";
        return;
      }
      genDiff.className = "diffview has-changes";
      genDiff.innerHTML = rows.map((r) => {
        const cls = r.t === "+" ? "diff-add" : r.t === "-" ? "diff-del" : "diff-ctx";
        return '<span class="' + cls + '">' + escapeHtml(r.t + " " + r.line) + "</span>";
      }).join("\n");
    });
  }

  /* ---- minimal LCS line diff (model draft vs operator-edited spec) ----- */
  function lineDiff(aText, bText) {
    const a = (aText || "").split("\n"), b = (bText || "").split("\n");
    const n = a.length, m = b.length;
    // LCS length table
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const out = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { out.push({ t: " ", line: a[i] }); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "-", line: a[i] }); i++; }
      else { out.push({ t: "+", line: b[j] }); j++; }
    }
    while (i < n) out.push({ t: "-", line: a[i++] });
    while (j < m) out.push({ t: "+", line: b[j++] });
    return out;
  }

  /* ---- scenarios page: click a row to preview its topology ------------ */
  function initScenariosBrowser() {
    const rows = Array.prototype.slice.call(document.querySelectorAll("[data-scenario-id]"));
    const show = (id, name) => {
      const title = document.getElementById("scenario-topo-title");
      if (title) title.textContent = name || id;
      rows.forEach((r) => r.classList.toggle("is-selected", r.dataset.scenarioId === id));
      fetch("/api/scenarios/" + encodeURIComponent(id) + "/topology")
        .then((r) => r.json())
        .then((d) => renderSpecTopology("scenario-topo", d && d.topology))
        .catch(() => renderSpecTopology("scenario-topo", null));
    };
    rows.forEach((r) => r.addEventListener("click", (e) => {
      if (e.target.closest("[data-del]")) return;
      show(r.dataset.scenarioId, r.dataset.scenarioName);
    }));
    document.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = b.dataset.del;
      if (!window.confirm("Delete imported scenario '" + id + "'?")) return;
      fetch("/api/scenarios/" + encodeURIComponent(id), {
        method: "DELETE", headers: { "X-CSRFToken": csrfToken() },
      }).then((r) => {
        if (r.ok) window.location.reload();
        else r.json().then((d) => window.alert(d.error || "delete failed")).catch(() => {});
      });
    }));
    if (rows.length) show(rows[0].dataset.scenarioId, rows[0].dataset.scenarioName);
  }

  /* ---- row filtering (logs + dashboard feed) -------------------------- */
  function _applyRowFilter(rowSel, src, query, emptyId) {
    const q = (query || "").toLowerCase().trim();
    let shown = 0;
    document.querySelectorAll(rowSel).forEach((r) => {
      const okSrc = !src || src === "all" || r.dataset.src === src;
      const okQ = !q || (r.dataset.search || "").indexOf(q) !== -1;
      const vis = okSrc && okQ;
      r.style.display = vis ? "" : "none";
      if (vis) shown++;
    });
    if (emptyId) { const e = document.getElementById(emptyId); if (e) e.hidden = shown > 0; }
  }
  function _segWire(segId, onPick) {
    const seg = document.getElementById(segId);
    if (!seg) return;
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || b.disabled) return;
      Array.prototype.forEach.call(seg.querySelectorAll("button"), (x) => x.classList.remove("on"));
      b.classList.add("on");
      onPick(b.dataset.f || b.dataset.l, b);
    });
  }

  /* ---- dashboard (system usage + activity filter) --------------------- */
  function initDashboard() {
    fetch("/api/system-usage").then((r) => r.json()).then((u) => {
      const g = (bar, val, pct, label) => {
        const b = document.getElementById(bar), v = document.getElementById(val);
        if (b) b.style.width = (pct == null ? 0 : Math.min(100, pct)) + "%";
        if (v) v.textContent = (pct == null ? "—" : (label || pct + "%"));
      };
      g("sys-cpu-bar", "sys-cpu-val", u.cpu, u.cpu == null ? null : u.cpu + "%");
      const mem = (u.mem_used_gb != null && u.mem_total_gb != null)
        ? (u.mem_used_gb + " / " + u.mem_total_gb + " GB")
        : (u.mem == null ? null : u.mem + "%");
      g("sys-mem-bar", "sys-mem-val", u.mem, mem);
      g("sys-disk-bar", "sys-disk-val", u.disk, u.disk == null ? null : u.disk + "%");
      const set = (id, x) => { const e = document.getElementById(id); if (e) e.textContent = (x == null ? "—" : x); };
      set("sys-containers", u.containers); set("sys-nets", u.networks);
      set("sys-arenas", u.active_arenas); set("sys-uptime", u.uptime);
    }).catch(() => {});
    _segWire("dash-seg", (f) => _applyRowFilter("#dash-feed .log-row", f, null, null));
  }

  /* ---- logs (source filter + search) ---------------------------------- */
  function initLogs() {
    const search = document.getElementById("logs-search");
    let src = "all";
    const apply = () => _applyRowFilter("#logs-feed .log-row", src, search ? search.value : "", "logs-empty");
    _segWire("logs-seg", (f) => { src = f; apply(); });
    if (search) search.addEventListener("input", apply);
  }

  /* ---- activity indexes (Findings / Evidence) ------------------------- */
  // Same facet + search contract as the audit trail, so every index filters alike.
  function initActivityIndex(name) {
    const search = document.getElementById(name + "-search");
    let facet = "all";
    const apply = () => _applyRowFilter(
      "#" + name + "-rows ." + name + "-row", facet,
      search ? search.value : "", name + "-empty");
    _segWire(name + "-seg", (f) => { facet = f; apply(); });
    if (search) search.addEventListener("input", apply);
  }

  /* ---- launch (single-view type selector) ----------------------------- */
  function initLaunch() {
    const panels = Array.prototype.slice.call(document.querySelectorAll(".launch-panel"));
    _segWire("launch-seg", (l) => {
      panels.forEach((p) => { p.hidden = p.dataset.l !== l; });
      // a Cytoscape preview sized while hidden mis-renders — resize/fit on show.
      setTimeout(() => Object.keys(specCy).forEach((k) => {
        try { specCy[k].resize(); specCy[k].fit(null, 36); } catch (e) {}
      }), 40);
    });
    initScenarioPreview();
  }

  /* ---- arena wizard (guided SUT authoring: target -> consent -> review) - */
  function initWizard() {
    const form = document.getElementById("wiz-form");
    if (!form) return;
    const panels = Array.prototype.slice.call(document.querySelectorAll(".wiz-panel"));
    const stepBtns = Array.prototype.slice.call(document.querySelectorAll("#wiz-steps .wiz-step"));
    const back = document.getElementById("wiz-back");
    const next = document.getElementById("wiz-next");
    const launch = document.getElementById("wiz-launch");
    const targetType = document.getElementById("wiz-target-type");
    const gitFields = document.getElementById("wiz-git-fields");
    const ociFields = document.getElementById("wiz-oci-fields");
    const bundleFields = document.getElementById("wiz-bundle-fields");
    const repoInput = document.getElementById("wiz-repo");
    const imageInput = document.getElementById("wiz-image");
    const bundleInput = document.getElementById("wiz-bundle");
    const artifactDigest = document.getElementById("wiz-artifact-digest");
    const setupControls = document.getElementById("wiz-setup-controls");
    const setupHelp = document.getElementById("wiz-setup-help");
    let step = 1;
    const ports = () => (document.getElementById("wiz-ports").value.match(/\d+/g) || []).map(Number).slice(0, 8);
    const isOci = () => targetType.value === "oci";
    const isBundle = () => targetType.value === "bundle";

    function syncTargetType() {
      const oci = isOci();
      const bundle = isBundle();
      gitFields.hidden = oci || bundle;
      ociFields.hidden = !oci;
      bundleFields.hidden = !bundle;
      repoInput.required = !oci && !bundle;
      imageInput.required = oci;
      bundleInput.required = bundle;
      setupControls.hidden = oci;
      setupHelp.textContent = oci
        ? "OCI targets require no configurator: Nidavellir runs the image's native entrypoint exactly as published, then preflight verifies that the target remains healthy."
        : (bundle
          ? "The validated bundle is mounted into a disposable Ubuntu target. Setup runs there—not in the control plane—and is time-boxed, step-budgeted, and fully traced."
          : "Bringing a Git target up needs a configurator session on the victim. Nothing writes/configures the box without it, and it is time-boxed, step-budgeted, and its egress is revoked before the engagement.");
    }

    const show = (n) => {
      step = n;
      panels.forEach((p) => { p.hidden = +p.dataset.step !== n; });
      // Update step indicator: on = current, done = completed (earlier steps)
      stepBtns.forEach((b) => {
        const s = +b.dataset.step;
        b.classList.toggle("on", s === n);
        b.classList.toggle("done", s < n);
      });
      // Update connecting lines between steps
      var lines = Array.prototype.slice.call(document.querySelectorAll(".wiz-step__line"));
      lines.forEach((l, i) => l.classList.toggle("done", i + 1 < n));
      back.hidden = n === 1;
      next.hidden = n === 3;
      launch.hidden = n !== 3;
      if (n === 3) review();
    };

    function review() {
      const msg = document.getElementById("wiz-msg");
      const recap = document.getElementById("wiz-recap");
      launch.disabled = true;
      msg.className = "import-msg"; msg.textContent = "Validating…";
      const body = {
        instance_id: document.getElementById("wiz-name").value.trim() || "wizard-preview",
        engagement_purpose: (document.querySelector('[name="engagement_purpose"]') || {}).value || null,
        participant_mode: (document.querySelector('[name="participant_mode"]') || {}).value || null,
        engagement_time_box_seconds: +(document.querySelector('[name="engagement_time_box_seconds"]') || {}).value || null,
        target_type: targetType.value,
        repo: document.getElementById("wiz-repo").value.trim(),
        ref: document.getElementById("wiz-ref").value.trim() || null,
        image: document.getElementById("wiz-image").value.trim(),
        platform: document.getElementById("wiz-platform").value,
        artifact_digest: artifactDigest.value,
        setup_mode: document.getElementById("wiz-mode").value,
        setup_egress: document.getElementById("wiz-egress").checked,
        time_box_seconds: +document.getElementById("wiz-tb").value,
        command_budget: +document.getElementById("wiz-budget").value,
        ports: ports(),
        include_attacker: document.getElementById("wiz-atk").checked,
        authorization_basis: document.getElementById("wiz-auth-basis").value,
        authorization_confirmed: document.getElementById("wiz-auth-confirmed").checked,
        scope_note: document.getElementById("wiz-scope-note").value.trim() || null,
      };
      const bundleName = bundleInput.files.length ? bundleInput.files[0].name : "no archive";
      const recapRows = [
        ["Purpose", body.engagement_purpose ? body.engagement_purpose.replace(/_/g, " ") : "compatibility path"],
        ["Participants", body.participant_mode ? body.participant_mode.replace(/_/g, " ") : "unspecified"],
        ["Engagement time box", body.engagement_time_box_seconds ? body.engagement_time_box_seconds + "s" : "platform default"],
        ["Target", isOci() ? body.image : (isBundle() ? bundleName :
          body.repo + (body.ref ? " @ " + body.ref : ""))],
        ["Platform", isOci() ? body.platform : "provider native"],
        ["Ports", body.ports.length ? body.ports.join(", ") : "—"],
        ["Attacker foothold", body.include_attacker ? "Kali" : "none"],
        ["Authorization", body.authorization_basis.replace(/_/g, " ") +
          (body.authorization_confirmed ? " · confirmed" : " · NOT CONFIRMED")],
        ["Configured by", isOci() ? "native OCI entrypoint" :
          (document.getElementById("wiz-mode").value === "hitl" ? "HITL (propose → approve)" : "operator shell")],
        ["Setup egress", isOci() ? "not applicable" :
          (document.getElementById("wiz-egress").checked ? "open (revoked before engagement)" : "off")],
        ["Time-box / budget", isOci() ? "not applicable" :
          document.getElementById("wiz-tb").value + "s / " + document.getElementById("wiz-budget").value + " steps"],
      ];
      recap.innerHTML = recapRows.map((r) =>
        '<div class="wiz-recap__row"><dt>' + escapeHtml(r[0]) + '</dt><dd class="mono">' + escapeHtml(String(r[1])) + '</dd></div>').join("");

      function sendPreview() {
        postJson("/api/arenas/sut/preview", body).then(({ status, data }) => {
        if (status === 200 && data.valid) {
          renderSpecTopology("wiz-topo", data.topology);
          const w = (data.warnings || []).length ? "  ⚠ " + data.warnings.join("; ") : "";
          msg.className = "import-msg ok";
          const commit = data.target_manifest && data.target_manifest.resolved_ref;
          msg.textContent = "Valid ✓ " + (data.summary ? data.summary.nodes + " node(s)" : "") +
            (commit ? " · pinned " + commit.slice(0, 12) : "") + w;
          launch.disabled = false;
        } else {
          renderSpecTopology("wiz-topo", null);
          msg.className = "import-msg err";
          msg.textContent = "Invalid: " + (data.errors ? data.errors.join("; ") : (data.error || data.detail || ("HTTP " + status)));
        }
        }).catch(() => {
          msg.className = "import-msg err";
          msg.textContent = "Preview request failed.";
        });
      }

      if (!isBundle() || body.artifact_digest) {
        sendPreview();
        return;
      }
      const selected = bundleInput.files[0];
      if (!selected) {
        msg.className = "import-msg err";
        msg.textContent = "Select a source archive.";
        return;
      }
      msg.textContent = "Uploading and validating source bundle…";
      const formData = new FormData();
      formData.append("file", selected);
      fetch("/api/targets/source-bundles", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        body: formData,
      })
        .then((response) => response.json().then((data) => ({ status: response.status, data })))
        .then(({ status, data }) => {
          if (status !== 200 || !data.artifact) {
            msg.className = "import-msg err";
            msg.textContent = "Bundle rejected: " + (data.error || ("HTTP " + status));
            return;
          }
          body.artifact_digest = data.artifact.digest;
          artifactDigest.value = data.artifact.digest;
          sendPreview();
        })
        .catch(() => {
          msg.className = "import-msg err";
          msg.textContent = "Bundle upload failed.";
        });
    }

    next.addEventListener("click", () => {
      // Step 1 needs a valid name + active target field before advancing.
      if (step === 1) {
        const name = document.getElementById("wiz-name");
        const target = isOci() ? imageInput : (isBundle() ? bundleInput : repoInput);
        const auth = document.getElementById("wiz-auth-confirmed");
        if (!name.reportValidity() || !target.reportValidity() || !auth.reportValidity()) return;
      }
      show(Math.min(step + 1, 3));
    });
    back.addEventListener("click", () => show(Math.max(step - 1, 1)));
    targetType.addEventListener("change", syncTargetType);
    bundleInput.addEventListener("change", () => { artifactDigest.value = ""; });
    syncTargetType();
    show(1);
  }

  /* ---- inventory (per-card machine line-up + topology rail) ----------- */
  function initInventory() {
    const cards = Array.prototype.slice.call(document.querySelectorAll(".inv-card[data-scenario-id]"));
    const DEV = { foothold: "fa-laptop-code", target: "fa-server", host: "fa-display" };
    const cache = {};
    const fetchTopo = (id) => cache[id]
      ? Promise.resolve(cache[id])
      : fetch("/api/scenarios/" + encodeURIComponent(id) + "/topology")
          .then((r) => r.json()).then((d) => (cache[id] = (d && d.topology) || null))
          .catch(() => null);
    const lineup = (thumb, topo) => {
      const nodes = (topo && topo.nodes) || [];
      if (!nodes.length) { thumb.innerHTML = '<span class="inv-more faint">no preview</span>'; return; }
      thumb.innerHTML = nodes.slice(0, 4).map((n) =>
        '<div class="inv-dev ' + (n.kind || "host") + '"><div class="d"><i class="fa-solid ' +
        (DEV[n.kind] || "fa-display") + '"></i></div><div class="t">' + escapeHtml(n.name || "") + "</div></div>"
      ).join("") + (nodes.length > 4 ? '<div class="inv-more">+' + (nodes.length - 4) + "</div>" : "");
    };
    const select = (id, name, card) => {
      const title = document.getElementById("scenario-topo-title");
      if (title) title.textContent = name || id;
      cards.forEach((x) => x.classList.toggle("is-selected", x === card));
      fetchTopo(id).then((t) => renderSpecTopology("scenario-topo", t));
    };
    cards.forEach((c) => {
      const thumb = c.querySelector("[data-lineup]");
      fetchTopo(c.dataset.scenarioId).then((t) => { if (thumb) lineup(thumb, t); });
      c.addEventListener("click", (e) => {
        if (e.target.closest("[data-del]")) return;
        select(c.dataset.scenarioId, c.dataset.scenarioName, c);
      });
    });
    document.querySelectorAll(".inv-card [data-del]").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = b.dataset.del;
      if (!window.confirm("Delete imported scenario '" + id + "'?")) return;
      fetch("/api/scenarios/" + encodeURIComponent(id), { method: "DELETE", headers: { "X-CSRFToken": csrfToken() } })
        .then((r) => { if (r.ok) window.location.reload(); else r.json().then((d) => window.alert(d.error || "delete failed")).catch(() => {}); });
    }));
    const search = document.getElementById("inv-search");
    let filt = "all";
    const apply = () => {
      const q = (search ? search.value : "").toLowerCase().trim();
      cards.forEach((c) => {
        const okF = filt === "all" || c.dataset.source === filt || c.dataset.provider === filt;
        const okQ = !q || (c.dataset.search || "").indexOf(q) !== -1;
        c.style.display = (okF && okQ) ? "" : "none";
      });
    };
    _segWire("inv-filter", (f) => { filt = f; apply(); });
    if (search) search.addEventListener("input", apply);
    if (cards.length) select(cards[0].dataset.scenarioId, cards[0].dataset.scenarioName, cards[0]);
  }

  /* ---- settings (reflect the stored model connection) ----------------- */
  function initSettings() {
    fetch("/api/model-connection").then((r) => r.json()).then((mc) => {
      if (!mc || !mc.configured) return;
      const b = brandOf(mc.provider);
      const logo = document.getElementById("set-model-logo"); if (logo) setBubble(logo, b);
      const name = document.getElementById("set-model-name"); if (name) name.textContent = mc.model || b.name;
      const detail = document.getElementById("set-model-detail");
      if (detail) detail.textContent = b.name + " · key ••••" + (mc.key_last4 || "") + " · encrypted at rest";
      const badge = document.getElementById("set-model-badge");
      if (badge) { badge.className = "badge badge--ok"; badge.textContent = "connected"; }
    }).catch(() => {});
  }

  window.Nidavellir = {
    initArena, initWorkspaceTabs, renderTopology, renderSpecTopology,
    initScenarioPreview, initScenariosBrowser,
    initDashboard, initLogs, initActivityIndex, initLaunch, initWizard, initInventory, initSettings,
    openModelModal, closeModelModal, openModelConfig, saveModel, removeModel, testModel,
    toggleSidebar, closeSidebar, toggleCopilot, sendCopilot,
    openAgentConfig, closeAgentConfig, revokeAgent, pauseAgent, resumeAgent,
    initEngagement, engDecide, openConfigurator, closeConfigurator,
    initAgents,
    initHttpWorkspace, httpToggleForm, httpSend, httpInspect, httpReplay,
    httpAttach, httpAttachFromInspect, httpRefresh,
    initPocWorkspace, pocToggleForm, pocSubmit, pocInspect, pocCancel,
    fit: function () { const cy = specCy["topo"]; if (cy) { cy.resize(); cy.fit(null, 36); } },
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeModelModal();
      closeConfigurator();
      const createMenu = document.getElementById("create-menu");
      if (createMenu) createMenu.open = false;
      if (isCompactNavigation()) closeSidebar();
    }
  });
  document.addEventListener("DOMContentLoaded", function () {
    // Restore the persisted collapsed-sidebar preference (desktop only).
    try {
      if (localStorage.getItem("nav-collapsed") === "1" && !isCompactNavigation()) {
        document.body.classList.add("nav-collapsed");
      }
    } catch (e) {}
    syncSidebarToggle();
    pollHealth();
    buildProviderMenu();
    pollModel();
    const cin = document.getElementById("copilot-input");
    if (cin) cin.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendCopilot(); }
    });
    // Preference toggles (settings/profile) — visual, session-scoped.
    document.addEventListener("click", (e) => {
      const sw = e.target.closest(".switch");
      if (sw) sw.classList.toggle("on");
      const createMenu = document.getElementById("create-menu");
      if (createMenu && createMenu.open && !createMenu.contains(e.target)) {
        createMenu.open = false;
      }
      const navLink = e.target.closest(".nav-item");
      if (navLink && isCompactNavigation()) closeSidebar();
    });
    window.addEventListener("resize", () => {
      if (isCompactNavigation()) {
        document.body.classList.remove("nav-collapsed");
      } else {
        document.getElementById("sidebar").classList.remove("open");
        try {
          document.body.classList.toggle("nav-collapsed", localStorage.getItem("nav-collapsed") === "1");
        } catch (e) {}
      }
      syncSidebarToggle();
    });
    // Per-page init is invoked from each template's {% block scripts %}.
  });
})();
