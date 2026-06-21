/* CyberGuard console — client behavior (vanilla JS, no build step). */
(function () {
  "use strict";

  let topoCy = null; // Cytoscape instance (NOT window.cy — an #id creates a global)

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
        text.textContent = ok ? "Orchestrator online" : "Orchestrator offline";
      })
      .catch(() => {
        badge.className = "badge badge--danger";
        if (dot) dot.className = "dot dot--failed";
        if (text) text.textContent = "Orchestrator offline";
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
    gemini: { name: "Google · Gemini", color: "#4285f4", model: "gemini-2.0-flash",
      svg: '<svg viewBox="0 0 24 24"><path d="M12 2c.6 5.3 3.1 7.8 8.4 8.4-5.3.6-7.8 3.1-8.4 8.4-.6-5.3-3.1-7.8-8.4-8.4C8.9 9.8 11.4 7.3 12 2z" fill="currentColor"/></svg>' },
    deepseek: { name: "DeepSeek", color: "#4d6bfe", model: "deepseek-chat",
      svg: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M7 13c2 2.2 8 2.2 10-1.2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' },
    ollama: { name: "Ollama · local", color: "#414959", model: "llama3",
      svg: '<svg viewBox="0 0 24 24"><path d="M8.5 3v4M15.5 3v4M6 10a6 6 0 0112 0v4a6 6 0 01-12 0z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' },
    local: { name: "Local model", color: "#22d3ee", model: "",
      svg: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' },
  };
  const FALLBACK = { name: "AI model", color: "#6b7280",
    svg: '<svg viewBox="0 0 24 24"><rect x="5" y="8" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 4v4M9.5 13h.01M14.5 13h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' };
  const brandOf = (p) => BRANDS[(p || "").toLowerCase()] || FALLBACK;

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  const PROVIDERS = ["anthropic", "openai", "gemini", "deepseek", "ollama", "local"];
  const KEYLESS = ["local", "ollama"]; // local runtimes may run without a key

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
    if (!model) { setFormError("Enter a model id."); return false; }
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
      body: JSON.stringify({ provider: provider, model: model, api_key: key }),
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
    const body = key ? { provider: pickProvider, model: model, api_key: key } : {};
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

  function buildElements(o) {
    const { nodes, nets } = parseTopology(o);
    const els = [];
    const primary = nets[0];
    nets.forEach((net, i) =>
      els.push({ data: { id: "net_" + i, label: net, kind: "net" } })
    );
    let anyWeb = false;
    nodes.forEach((nd, i) => {
      const role = nd.ssh ? "foothold" : nd.url ? "target" : "host";
      if (nd.url) anyWeb = true;
      const dead = nd.state && nd.state !== "running";
      els.push({
        data: {
          id: "n_" + i, kind: role, dead: dead ? "1" : "0",
          label: nd.key + (nd.ip ? "\n" + nd.ip : ""),
        },
      });
      els.push({ data: { source: "net_0", target: "n_" + i } });
    });
    if (anyWeb && primary) {
      els.push({ data: { id: "inet", label: "host", kind: "inet" } });
      els.push({ data: { source: "inet", target: "net_0" } });
    }
    return els;
  }

  const CY_STYLE = [
    { selector: "node", style: {
        label: "data(label)", "text-wrap": "wrap", "text-valign": "bottom",
        "text-margin-y": 7, "font-size": "10px", "font-family": "monospace",
        color: C.text, "background-color": C.bg, "border-width": 2,
        "border-color": C.border, width: 38, height: 38, shape: "round-rectangle",
    }},
    { selector: 'node[kind="net"]', style: {
        shape: "ellipse", "background-color": "#0f1117", "border-color": C.accent,
        color: C.accent, width: 30, height: 30, "font-size": "9px",
    }},
    { selector: 'node[kind="inet"]', style: {
        shape: "diamond", "border-color": C.muted, color: C.muted, "background-color": "#0f1117",
    }},
    { selector: 'node[kind="foothold"]', style: { "border-color": C.danger, color: C.danger } },
    { selector: 'node[kind="target"]', style: { "border-color": C.warn, color: C.warn } },
    { selector: 'node[dead="1"]', style: { "border-color": C.muted, opacity: 0.5 } },
    { selector: "edge", style: {
        width: 1.5, "line-color": C.border, "curve-style": "bezier", "target-arrow-shape": "none",
    }},
  ];

  function renderTopology(o) {
    const container = document.getElementById("topo");
    if (!container || typeof cytoscape === "undefined") return;
    const els = buildElements(o);
    if (topoCy) {
      topoCy.elements().remove();
      topoCy.add(els);
      topoCy.layout({ name: "cose", padding: 30, animate: false }).run();
    } else {
      topoCy = cytoscape({
        container, elements: els, style: CY_STYLE,
        layout: { name: "cose", padding: 30, animate: false, nodeRepulsion: 8000 },
      });
    }
  }

  /* ---- arena detail page ---------------------------------------------- */
  function initArena() {
    const id = document.body.dataset.instanceId;
    let last = {};
    try { last = JSON.parse(document.getElementById("lab-data").textContent || "{}"); } catch (e) {}
    renderTopology(last);

    let prevStatus = null, delay = 3000;
    const poll = () => {
      fetch("/api/poll/" + id)
        .then((r) => r.json())
        .then((d) => {
          const badge = document.getElementById("lab-status");
          if (badge) badge.innerHTML = statusBadge(d.status);
          // Reaching 'active' for the first time → reload to populate the node table.
          if (d.status === "active" && prevStatus && prevStatus !== "active") {
            window.location.reload(); return;
          }
          prevStatus = d.status;
          if (d.outputs && JSON.stringify(d.outputs) !== JSON.stringify(last)) {
            last = d.outputs; renderTopology(last);
          }
          delay = d.status === "active" ? 6000 : 3000;
          setTimeout(poll, delay);
        })
        .catch(() => setTimeout(poll, 8000));
    };
    poll();
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
        if (r.ok) { window.location.href = "/arenas"; return; }
        return r.json().catch(() => ({})).then((b) => {
          throw new Error(b.error || "Destroy failed (HTTP " + r.status + ")");
        });
      })
      .catch((e) => alert("Error: " + e.message));
  };

  /* ---- co-pilot chat (connected model + arena context) ---------------- */
  let copilotHistory = [];
  let copilotBusy = false;
  const currentArena = () => window.CYBERGUARD_ARENA || null;

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

  /* ---- configurator setup-phase panel (arena detail) ------------------ */
  let cfgArena = null;
  let cfgTimer = null;
  let cfgSig = null; // structural signature of the last full render

  function cfgApi(path, method, body) {
    const opts = { method: method || "GET", headers: {} };
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    if (method && method !== "GET") opts.headers["X-CSRFToken"] = csrfToken();
    return fetch("/api/setup/" + cfgArena + path, opts).then((r) => r.json());
  }

  function initConfigurator(arena) {
    cfgArena = arena;
    cfgSig = null; // force a full render on (re)init
    refreshConfigurator();
    if (cfgTimer) clearInterval(cfgTimer);
    cfgTimer = setInterval(refreshConfigurator, 5000);
  }
  function refreshConfigurator() { cfgApi("").then(renderConfigurator).catch(() => {}); }

  function cfgErr(msg) {
    const e = document.getElementById("cfg-err");
    if (e) { e.textContent = msg || ""; e.hidden = !msg; }
  }

  // The panel's structural shape. A full innerHTML rebuild happens ONLY when this
  // changes (idle⇄open, mode switch, scope change); within one shape we patch the
  // live counters/proposal list in place — so a half-typed command, its focus,
  // and the last step's output survive the 5s poll instead of being wiped.
  function cfgSignature(s) {
    if (!s || !s.open) return "idle";
    return "open|" + (s.mode || "") + "|" + (s.nodes || []).join(",");
  }

  function renderConfigurator(s) {
    const body = document.getElementById("cfg-body");
    const state = document.getElementById("cfg-state");
    if (!body) return;
    // The status badge lives outside #cfg-body and holds no input — safe to set
    // on every poll so expiry/mode changes still show promptly.
    if (state) {
      if (!s || !s.open) { state.className = "badge badge--idle"; state.textContent = "idle"; }
      else {
        state.className = "badge " + (s.expired ? "badge--danger" : "badge--ok");
        state.textContent = (s.mode || "setup") + (s.expired ? " · expired" : " · open");
      }
    }
    const sig = cfgSignature(s);
    if (sig === cfgSig) { patchConfigurator(s); return; } // same shape → patch, don't rebuild
    cfgSig = sig;
    body.innerHTML = buildConfigurator(s);
  }

  function buildConfigurator(s) {
    if (!s || !s.open) {
      return '<div class="cfg-note">No setup session. Start one to bring the service up on the victim ' +
        'before the engagement — under a consented, time-boxed, victim-scoped session.</div>' +
        '<div class="cfg-start">' +
        '<label class="cfg-fld"><span>Mode</span><select class="select" id="cfg-mode">' +
        '<option value="operator">operator-scripted (you run steps)</option>' +
        '<option value="hitl">HITL (agent proposes, you approve)</option>' +
        '<option value="autonomous">autonomous (agent runs directly — needs platform flag)</option>' +
        '</select></label>' +
        '<label class="cfg-fld"><span>Time-box (s)</span><input class="input" id="cfg-tb" type="number" value="1800" min="60"></label>' +
        '<label class="cfg-fld"><span>Step budget</span><input class="input" id="cfg-budget" type="number" value="50" min="1"></label>' +
        '<label class="cfg-check"><input type="checkbox" id="cfg-egress"> open setup egress (victim can fetch dependencies)</label>' +
        '<button class="btn btn-primary btn-sm" onclick="CyberGuard.cfgStart()">Start setup</button>' +
        '</div><div class="cfg-err" id="cfg-err" hidden></div>';
    }
    let html =
      '<div class="cfg-meta">' +
      '<span><b>mode</b> ' + escapeHtml(s.mode) + '</span>' +
      '<span><b>scope</b> ' + escapeHtml((s.nodes || []).join(", ")) + '</span>' +
      '<span><b>steps</b> <span id="cfg-steps">' + s.steps_run + '/' + s.command_budget + '</span></span>' +
      '<span><b>egress</b> <span id="cfg-egress-v">' + (s.egress_enforced ? "open" : "off") + '</span></span>' +
      '</div>';
    // SUT/setup: how to shell into the box and run the project's README steps.
    const conn = s.connect || {};
    const connKeys = Object.keys(conn);
    if (connKeys.length) {
      html += '<div class="cfg-note" style="margin-bottom:8px"><b>Connect to set up the box:</b> ' +
        connKeys.map((n) => escapeHtml(n) + ' → <span class="mono">' + escapeHtml(conn[n]) + '</span>').join(" · ") +
        '</div>';
    }
    if (s.mode === "operator") {
      const opts = (s.nodes || []).map((n) => '<option value="' + escapeHtml(n) + '">' + escapeHtml(n) + '</option>').join("");
      html +=
        '<div class="cfg-step"><select class="select" id="cfg-node" style="max-width:150px">' + opts + '</select>' +
        '<input class="input mono" id="cfg-cmd" placeholder="setup command, e.g. apt-get install -y nginx">' +
        '<button class="btn btn-sm" onclick="CyberGuard.cfgRunStep()">Run</button></div>' +
        '<pre class="cfg-out" id="cfg-out" hidden></pre>';
    } else if (s.mode === "hitl") {
      html += '<div id="cfg-props-wrap">' + renderProposals(s) + '</div>';
    } else if (s.mode === "autonomous") {
      html += '<div class="cfg-note">Autonomous: the connected agent runs setup steps directly through the gateway (double-locked). Watch progress in Activity below.</div>';
    }
    html += '<div class="cfg-actions"><button class="btn btn-danger btn-sm" onclick="CyberGuard.cfgFinish()">Finish setup</button></div>' +
            '<div class="cfg-err" id="cfg-err" hidden></div>';
    return html;
  }

  function renderProposals(s) {
    const pend = s.pending_proposals || [];
    return pend.length
      ? '<div class="cfg-props">' + pend.map((p) =>
          '<div class="cfg-prop"><div class="mono">' + escapeHtml(p.command) + '</div>' +
          (p.rationale ? '<div class="muted" style="font-size:12px;margin-top:3px">' + escapeHtml(p.rationale) + '</div>' : '') +
          '<div class="cfg-prop__act"><span class="muted" style="font-size:12px">' + escapeHtml(p.node) + '</span>' +
          '<button class="btn btn-primary btn-sm" onclick="CyberGuard.cfgDecide(\'' + p.step_id + '\',\'approve\')">Approve</button>' +
          '<button class="btn btn-danger btn-sm" onclick="CyberGuard.cfgDecide(\'' + p.step_id + '\',\'reject\')">Reject</button>' +
          '</div></div>').join("") + '</div>'
      : '<div class="cfg-note">No pending proposals. The connected agent (configurator stance) proposes steps via the gateway; approve them here.</div>';
  }

  // Patch only the live bits within the current shape — never touches the command
  // input or its output (preserving typing/focus), and skips the proposal list
  // while the operator is interacting with it.
  function patchConfigurator(s) {
    if (!s || !s.open) return;
    const steps = document.getElementById("cfg-steps");
    if (steps) steps.textContent = s.steps_run + "/" + s.command_budget;
    const egr = document.getElementById("cfg-egress-v");
    if (egr) egr.textContent = s.egress_enforced ? "open" : "off";
    if (s.mode === "hitl") {
      const wrap = document.getElementById("cfg-props-wrap");
      if (wrap && !(document.activeElement && wrap.contains(document.activeElement))) {
        wrap.innerHTML = renderProposals(s);
      }
    }
  }

  function cfgStart() {
    cfgApi("/start", "POST", {
      mode: document.getElementById("cfg-mode").value,
      time_box_seconds: +document.getElementById("cfg-tb").value || 1800,
      command_budget: +document.getElementById("cfg-budget").value || 50,
      setup_egress: document.getElementById("cfg-egress").checked,
    }).then((r) => { if (r.error) cfgErr(r.error); else refreshConfigurator(); });
  }
  function cfgRunStep() {
    const command = document.getElementById("cfg-cmd").value.trim();
    if (!command) return;
    cfgApi("/step", "POST", { node: document.getElementById("cfg-node").value, command }).then((r) => {
      if (r.error) { cfgErr(r.error); return; }
      cfgErr("");
      const out = document.getElementById("cfg-out");
      if (out) { out.hidden = false; out.textContent = "$ " + command + "\n" + (r.stdout || "") + (r.stderr || ""); }
      document.getElementById("cfg-cmd").value = "";
      refreshConfigurator();
    });
  }
  function cfgDecide(stepId, decision) {
    cfgApi("/proposals/" + stepId + "/" + decision, "POST").then((r) => { if (r.error) cfgErr(r.error); refreshConfigurator(); });
  }
  function cfgFinish() {
    if (!confirm("Finish setup and revoke the configurator capability?")) return;
    cfgApi("/finish", "POST").then(() => refreshConfigurator());
  }

  window.CyberGuard = {
    initArena, renderTopology,
    openModelModal, closeModelModal, openModelConfig, saveModel, removeModel, testModel,
    toggleCopilot, sendCopilot,
    initConfigurator, cfgStart, cfgRunStep, cfgDecide, cfgFinish,
    fit: function () { if (topoCy) topoCy.fit(null, 30); },
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeModelModal(); }
  });
  document.addEventListener("DOMContentLoaded", function () {
    pollHealth();
    buildProviderMenu();
    pollModel();
    const cin = document.getElementById("copilot-input");
    if (cin) cin.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendCopilot(); }
    });
  });
})();
