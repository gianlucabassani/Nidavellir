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

  window.CyberGuard = {
    initArena, renderTopology,
    fit: function () { if (topoCy) topoCy.fit(null, 30); },
  };
  document.addEventListener("DOMContentLoaded", pollHealth);
})();
