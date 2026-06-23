/* CyberGuard console — client behavior (vanilla JS, no build step). */
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

  /* ---- agents console (live connections + activity trace) ------------- */
  let agentsTimer = null;

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
    const tl = d.timeline || [];
    const count = document.getElementById("agents-count");
    if (count) count.textContent = conns.length + " connection" + (conns.length === 1 ? "" : "s");

    const cw = document.getElementById("agents-connections");
    if (cw) {
      cw.innerHTML = conns.length
        ? '<div class="agent-grid">' + conns.map(agentCard).join("") + "</div>"
        : '<div class="muted" style="font-size:13px">No agents connected yet. Connect a bring-your-own agent through the MCP gateway (stance <b>attacker</b> or <b>configurator</b>); it appears here once it announces itself or runs a command.</div>';
    }
    const tw = document.getElementById("agents-timeline");
    if (tw) {
      tw.innerHTML = tl.length
        ? agentTimeline(tl)
        : '<div class="empty" style="padding:24px">No agent activity yet.</div>';
    }
  }

  function agentCard(c) {
    const b = brandOf(c.provider);
    const dot = c.active ? "dot--active" : "dot--standby";
    const arena = encodeURIComponent(c.arena_id || "");
    return '<div class="agent-card">' +
      '<div class="agent-card__top">' +
        '<span class="badge badge--accent">' + escapeHtml(c.stance || "agent") + "</span>" +
        '<span class="dot ' + dot + '" title="' + (c.active ? "recent activity" : "idle") + '"></span>' +
      "</div>" +
      '<div class="agent-card__model">' +
        '<span class="agent-card__logo" style="background:' + b.color + '">' + b.svg + "</span>" +
        '<span class="mono">' + escapeHtml(c.model || b.name) + "</span></div>" +
      '<div class="muted" style="font-size:12px;margin:2px 0 8px">' + escapeHtml(b.name) + "</div>" +
      '<a class="agent-card__arena mono" href="/arena/' + arena + '">' +
        escapeHtml(c.arena_name || "") + ' <span class="faint">' + escapeHtml((c.arena_id || "").slice(0, 8)) + "</span></a>" +
      '<div class="agent-card__stats">' +
        "<span><b>" + (c.commands || 0) + "</b> cmds</span>" +
        "<span><b>" + (c.findings || 0) + "</b> findings</span>" +
        '<span class="faint" title="last seen">' + escapeHtml(c.last_seen || "—") + "</span>" +
      "</div></div>";
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

    const sub = (n) =>
      n.kind === "foothold" ? (n.stance || "attacker")
      : (n.kind === "target" && n.ports.length ? ":" + n.ports.join(",") : "");

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
        if (status === 200) { window.location.href = "/scenarios"; }
        else if (iMsg) { iMsg.className = "import-msg err"; iMsg.textContent = "Import failed: " + (data.error || ("HTTP " + status)); }
      });
    });
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

  window.CyberGuard = {
    initArena, renderTopology, renderSpecTopology,
    initScenarioPreview, initScenariosBrowser,
    openModelModal, closeModelModal, openModelConfig, saveModel, removeModel, testModel,
    toggleCopilot, sendCopilot,
    initConfigurator, cfgStart, cfgRunStep, cfgDecide, cfgFinish,
    initAgents,
    fit: function () { const cy = specCy["topo"]; if (cy) cy.fit(null, 36); },
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
    // Per-page wiring (topology previews live on launch + scenarios).
    const page = document.body.dataset.page;
    if (page === "launch") initScenarioPreview();
    if (page === "scenarios") initScenariosBrowser();
  });
})();
