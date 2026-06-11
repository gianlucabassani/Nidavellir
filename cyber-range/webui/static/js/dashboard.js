// Shared page script: keeps the nav-bar "Orchestrator Status" badge honest
// by polling the WebUI's /api/health proxy on every page.
//
// Lab-specific logic (status polling, topology graph, destroy button) lives
// inline in dashboard.html. Do NOT redeclare its globals here: this file
// loads after the inline script, and a top-level `let`/`var` collision
// throws a SyntaxError that silently kills this whole file.

(function () {
    const HEALTH_POLL_MS = 10000;

    function setOrchestratorBadge(online) {
        const badge = document.getElementById('nav-status-badge');
        const text = document.getElementById('status-text');
        if (!badge || !text) return;
        if (online) {
            badge.className = "badge rounded-pill bg-success border border-success shadow-sm";
            text.innerText = "ONLINE";
        } else {
            badge.className = "badge rounded-pill bg-danger border border-danger shadow-sm";
            text.innerText = "OFFLINE";
        }
    }

    function checkHealth() {
        fetch('/api/health')
            .then(resp => resp.json())
            .then(data => setOrchestratorBadge(data.status === 'ok'))
            .catch(() => setOrchestratorBadge(false));
    }

    document.addEventListener('DOMContentLoaded', function () {
        checkHealth();
        setInterval(checkHealth, HEALTH_POLL_MS);
    });
})();
