import hmac
import os
import re

import requests
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from flask_wtf import CSRFProtect

app = Flask(__name__)
# Never hardcode the secret: it signs session cookies/flash messages.
app.secret_key = os.getenv("SECRET_KEY", "dev-insecure-change-me")
csrf = CSRFProtect(app)
API_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

# Key the WebUI uses to authenticate against the orchestrator API (ADR-0002).
API_KEY = os.getenv("ORCHESTRATOR_API_KEY", "dev-insecure-key")
API_HEADERS = {"X-API-Key": API_KEY}

# Operator login for the dashboard itself.
WEBUI_USERNAME = os.getenv("WEBUI_USERNAME", "admin")
WEBUI_PASSWORD = os.getenv("WEBUI_PASSWORD", "cyberguard")

if WEBUI_PASSWORD == "cyberguard":  # noqa: S105 - detecting the default, not setting it
    app.logger.warning(
        "WEBUI_PASSWORD is the well-known default — fine for the local demo, "
        "NEVER for a reachable deployment."
    )

_TRANSIENT = ("pending", "deploying", "destroying")


# --- orchestrator API helpers ------------------------------------------------
def _api_error(resp):
    """Best-effort human message from a non-200 orchestrator response. FastAPI
    returns {"detail": "..."} or {"detail": [validation errors]}; fall back to
    the status code."""
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, list):  # pydantic validation errors
        detail = "; ".join(e.get("msg", "invalid") for e in detail)
    return detail or f"HTTP {resp.status_code}"


def _api_post(path, payload=None, timeout=15):
    """POST JSON to the orchestrator; returns (json, status_code). On a non-200
    the json is normalized to {"error": <message>}."""
    try:
        resp = requests.post(
            f"{API_URL}{path}", json=payload or {}, headers=API_HEADERS, timeout=timeout
        )
    except requests.RequestException:
        return {"error": "orchestrator unreachable"}, 502
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200:
        data = {"error": _api_error(resp)}
    return data, resp.status_code


def _api_get(path, timeout=5):
    """GET {API_URL}{path}; returns (json_or_None, ok)."""
    try:
        resp = requests.get(f"{API_URL}{path}", headers=API_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.json(), True
        if resp.status_code == 401:
            flash("Backend rejected the WebUI API key (check ORCHESTRATOR_API_KEY)", "danger")
        return None, False
    except requests.RequestException:
        return None, False


def _deployments():
    data, ok = _api_get("/deployments")
    return (data or {}), ok


def _scenarios():
    data, _ = _api_get("/scenarios")
    return (data or {}).get("scenarios", [])


def _catalog():
    data, _ = _api_get("/catalog")
    images = (data or {}).get("images", [])
    attackers = [i for i in images if i["kind"] == "attacker" and i["available"]]
    victims = [i for i in images if i["kind"] == "victim" and i["available"]]
    return images, attackers, victims


def _events(instance_id=None, limit=100):
    path = f"/deployments/{instance_id}/events" if instance_id else "/events"
    data, _ = _api_get(f"{path}?limit={int(limit)}")
    return (data or {}).get("events", [])


def _current_agent():
    """The most recently connected BYO agent's model + provider, from the latest
    `agent_session` event (events are newest-first). None when no agent has
    announced itself. Powers the topbar 'connected model' chip."""
    for e in _events(limit=100):
        if e.get("type") == "agent_session":
            p = e.get("payload") or {}
            if not p.get("model"):
                continue
            return {
                "model": p.get("model"),
                "provider": (p.get("provider") or "").lower(),
                "stance": p.get("stance"),
                "arena_id": e.get("lab_id"),
                "ts": e.get("ts"),
                "actor": p.get("actor") or e.get("actor"),
            }
    return None


def _score(instance_id):
    """The arena's benchmark scorecard (known-vuln manifest + found/missed).
    Operator-only on the API; the WebUI key is operator/admin. Returns None when
    the scenario has no manifest (so the panel hides itself)."""
    data, ok = _api_get(f"/arenas/{instance_id}/score")
    if not ok or not data or not data.get("manifest"):
        return None
    return data


def _default_infra():
    """Infra class ('container'|'vm'|'any') of the orchestrator's default provider
    — lets the UI flag scenarios the default backend can't run."""
    data, _ = _api_get("/providers")
    if not data:
        return "any"
    infra = {p["name"]: p["infra_class"] for p in data.get("providers", [])}
    return infra.get(data.get("default"), "any")


def _parse_nodes(outputs):
    """Flatten the provider's per-node outputs into a render-friendly list."""
    nodes = []
    for key in outputs:
        m = re.match(r"^node_(.+)_name$", key)
        if not m:
            continue
        n = m.group(1)
        ssh = outputs.get(f"node_{n}_ssh_command")
        url = outputs.get(f"node_{n}_url")
        nodes.append({
            "name": n,
            "ip": outputs.get(f"node_{n}_private_ip", ""),
            "state": outputs.get(f"node_{n}_state", "running"),
            "url": url,
            "ssh": ssh,
            "foothold": bool(ssh),
        })
    return sorted(nodes, key=lambda x: (not x["foothold"], x["name"]))


# --- auth --------------------------------------------------------------------
@app.before_request
def require_login():
    if request.endpoint in ("login", "static", "orchestrator_health"):
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if hmac.compare_digest(username, WEBUI_USERNAME) and hmac.compare_digest(password, WEBUI_PASSWORD):
            session["logged_in"] = True
            session["username"] = username
            target = request.args.get("next") or url_for("overview")
            # Same-site relative paths only. `startswith("/")` alone still admits
            # protocol-relative ("//evil.com") and backslash-tricked ("/\evil.com")
            # URLs that browsers resolve as absolute → open redirect after login.
            if not target.startswith("/") or target[1:2] in ("/", "\\"):
                target = url_for("overview")
            return redirect(target)
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# --- pages -------------------------------------------------------------------
@app.route("/")
def overview():
    deployments, ok = _deployments()
    scenarios = _scenarios()
    images, _, _ = _catalog()

    by = {}
    for v in deployments.values():
        by[v.get("status")] = by.get(v.get("status"), 0) + 1
    stats = {
        "total": len(deployments),
        "active": by.get("active", 0),
        "transient": sum(by.get(s, 0) for s in _TRANSIENT),
        "failed": by.get("failed", 0) + by.get("error_destroying", 0),
        "scenarios": len(scenarios),
        "images": len(images),
    }
    current = [(k, v) for k, v in deployments.items() if v.get("status") != "destroyed"]
    archived = [(k, v) for k, v in deployments.items() if v.get("status") == "destroyed"]
    recent = (current + archived)[:6]

    return render_template("overview.html", active="overview", stats=stats,
                           recent=recent, backend_ok=ok)


@app.route("/arenas")
def arenas():
    deployments, _ = _deployments()
    current = {k: v for k, v in deployments.items() if v.get("status") != "destroyed"}
    archived = {k: v for k, v in deployments.items() if v.get("status") == "destroyed"}
    return render_template("arenas.html", active="arenas", current=current, archived=archived)


@app.route("/launch")
def launch():
    _, attackers, victims = _catalog()
    default_infra = _default_infra()
    scenarios = _scenarios()
    # Compatible scenarios first, so the (auto-selected) first option is runnable.
    scenarios.sort(key=lambda s: default_infra not in ("any", s.get("provider_class")))
    return render_template("launch.html", active="launch", scenarios=scenarios,
                           attackers=attackers, victims=victims, default_infra=default_infra)


@app.route("/scenarios")
def scenarios():
    _, attackers, victims = _catalog()
    return render_template("scenarios.html", active="scenarios",
                           scenarios=_scenarios(), attackers=attackers, victims=victims)


@app.route("/arena/<instance_id>")
def arena_detail(instance_id):
    data, ok = _api_get(f"/status/{instance_id}")
    if not ok or data is None:
        flash(f"Arena {instance_id} not found.", "warning")
        return redirect(url_for("arenas"))
    outputs = data.get("outputs", {}) or {}
    return render_template(
        "arena_detail.html", active="arenas",
        instance_id=instance_id,
        instance_name=data.get("user_id", instance_id),
        state=data.get("status", "unknown"),
        outputs=outputs,
        nodes=_parse_nodes(outputs),
        unhealthy=outputs.get("unhealthy_nodes"),
        provider=outputs.get("provider") or data.get("provider"),
        events=_events(instance_id, limit=30),
        score=_score(instance_id),
    )


# --- planned (TODO) sections -------------------------------------------------
_STUBS = {
    "agents": {
        "feature": "Agents", "icon": "fa-robot",
        "summary": "Connect and observe bring-your-own AI agents through the MCP gateway.",
        "blurb": "Agents reach an arena only through the MCP gateway, wired in as "
                 "attacker, MITM, or defender. This page will manage those connections "
                 "and replay what each agent did, step by step.",
        "todo": [
            {"title": "Gateway connections", "note": "attacker / MITM / defender stances"},
            {"title": "Live agent traces", "note": "per-step command + output timeline"},
            {"title": "Budgets & kill switch", "note": "step / time / token limits per agent"},
        ],
        "roadmap": "Phase 2 — MCP agent gateway & stances",
    },
    "settings": {
        "feature": "Settings", "icon": "fa-gear",
        "summary": "Operator profile, API keys and console preferences.",
        "blurb": "Manage your operator identity, issue and revoke API keys for agents "
                 "and operators, and set console defaults.",
        "todo": [
            {"title": "Profile", "note": "display name, password"},
            {"title": "API keys", "note": "issue / revoke agent + operator keys"},
            {"title": "Preferences", "note": "default provider, arena TTL"},
        ],
        "roadmap": "Phase 5 — ownership / RBAC & quotas",
    },
}


@app.route("/agents")
def agents():
    return render_template("stub.html", active="agents", **_STUBS["agents"])


@app.route("/audit")
def audit():
    return render_template("audit.html", active="audit", events=_events(limit=150))


@app.route("/settings")
def settings():
    return render_template("stub.html", active="settings", **_STUBS["settings"])


# --- actions -----------------------------------------------------------------
@app.route("/create", methods=["POST"])
def create_lab():
    try:
        resp = requests.post(f"{API_URL}/deploy", json={
            "scenario": request.form.get("scenario"),
            "instance_id": request.form.get("instance_id"),
        }, headers=API_HEADERS, timeout=5)
        if resp.status_code == 422:
            try:
                detail = resp.json()["detail"][0]["msg"]
            except (ValueError, LookupError):
                detail = "invalid input"
            flash(f"Launch rejected: {detail}", "warning")
        elif resp.status_code != 200:
            flash(f"Deploy failed (HTTP {resp.status_code})", "danger")
        else:
            flash(f"Launching '{request.form.get('instance_id')}'…", "info")
    except requests.RequestException as e:
        flash(f"Deploy failed: {e}", "danger")
    return redirect(url_for("arenas"))


@app.route("/build-custom", methods=["POST"])
def build_custom():
    instance_id = request.form.get("instance_id")
    attacker = request.form.get("attacker")
    victims = request.form.getlist("victims")
    try:
        resp = requests.post(f"{API_URL}/arenas/custom", json={
            "instance_id": instance_id, "attacker": attacker, "victims": victims,
        }, headers=API_HEADERS, timeout=10)
        if resp.status_code == 200:
            flash(f"Building '{instance_id}': {attacker} vs {', '.join(victims)} "
                  "(images pulled on first use)", "info")
        elif resp.status_code == 422:
            try:
                detail = resp.json()["detail"]
                if isinstance(detail, list):
                    detail = detail[0].get("msg", "invalid input")
            except (ValueError, LookupError, AttributeError):
                detail = "invalid selection"
            flash(f"Build rejected: {detail}", "warning")
        else:
            flash(f"Build failed (HTTP {resp.status_code})", "danger")
    except requests.RequestException as e:
        flash(f"Build failed: {e}", "danger")
    return redirect(url_for("arenas"))


@app.route("/build-sut", methods=["POST"])
def build_sut():
    """Launch a software-under-test arena from the wizard (proxies POST
    /arenas/sut). Clone a GitHub repo onto a fresh Ubuntu box; the service is
    brought up during the setup phase by you or a HITL agent."""
    f = request.form
    ports = [int(p) for p in re.findall(r"\d+", f.get("ports", ""))][:8]
    payload = {
        "instance_id": f.get("instance_id"),
        "repo": (f.get("repo") or "").strip(),
        "ref": (f.get("ref") or "").strip() or None,
        "ports": ports,
        "include_attacker": f.get("include_attacker") == "on",
        "setup_mode": f.get("setup_mode", "operator"),
        "setup_egress": f.get("setup_egress") == "on",
    }
    try:
        resp = requests.post(
            f"{API_URL}/arenas/sut", json=payload, headers=API_HEADERS, timeout=10
        )
        if resp.status_code == 200:
            flash(
                f"Building SUT arena '{payload['instance_id']}' from {payload['repo']} — "
                "setup opens automatically once it's active.", "info",
            )
        else:
            flash(f"SUT launch rejected: {_api_error(resp)}", "warning")
    except requests.RequestException as e:
        flash(f"SUT launch failed: {e}", "danger")
    return redirect(url_for("arenas"))


def _request_destroy(instance_id):
    try:
        resp = requests.delete(f"{API_URL}/destroy/{instance_id}", headers=API_HEADERS, timeout=10)
    except requests.RequestException:
        return False, "Backend offline"
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "")
        except ValueError:
            detail = ""
        return False, detail or f"Destroy rejected (HTTP {resp.status_code})"
    return True, "Destroy started"


@app.route("/api/destroy/<instance_id>", methods=["POST"])
def destroy_lab(instance_id):
    ok, message = _request_destroy(instance_id)
    if not ok:
        return jsonify({"error": message}), 502
    return jsonify({"status": "ok"})


@app.route("/destroy/<instance_id>", methods=["POST"])
def destroy_lab_form(instance_id):
    ok, message = _request_destroy(instance_id)
    flash(message, "info" if ok else "danger")
    return redirect(url_for("arenas"))


@app.route("/archive/delete/<instance_id>", methods=["POST"])
def archive_delete(instance_id):
    try:
        resp = requests.delete(f"{API_URL}/deployments/{instance_id}", headers=API_HEADERS, timeout=10)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", "")
            except ValueError:
                detail = ""
            flash(detail or f"Delete failed (HTTP {resp.status_code})", "danger")
    except requests.RequestException:
        flash("Backend offline", "danger")
    return redirect(url_for("arenas"))


@app.route("/archive/clear", methods=["POST"])
def archive_clear():
    try:
        resp = requests.delete(f"{API_URL}/deployments", headers=API_HEADERS, timeout=10)
        if resp.status_code == 200:
            flash(f"Archive cleared ({resp.json().get('deleted', 0)} record(s))", "info")
        else:
            flash(f"Clear failed (HTTP {resp.status_code})", "danger")
    except requests.RequestException:
        flash("Backend offline", "danger")
    return redirect(url_for("arenas"))


@app.route("/api/health")
def orchestrator_health():
    try:
        resp = requests.get(f"{API_URL}/health", timeout=3)
        ok = resp.status_code == 200
    except requests.RequestException:
        ok = False
    return jsonify({"status": "ok" if ok else "offline"})


@app.route("/api/current-agent")
def current_agent():
    """JSON for the topbar 'connected model' chip (polled by app.js)."""
    agent = _current_agent()
    if not agent:
        return jsonify({"connected": False})
    return jsonify({"connected": True, **agent})


@app.route("/api/model-connection", methods=["GET"])
def model_connection_get():
    """Masked model-connection status for the topbar bubble (proxies the
    orchestrator's GET /agent/model). Never carries the key."""
    data, _ = _api_get("/agent/model")
    return jsonify(data or {"configured": False})


@app.route("/api/model-connection", methods=["PUT"])
def model_connection_set():
    """Store the operator's bring-your-own model key (proxies orchestrator
    PUT /agent/model). The key transits webui→orchestrator over the internal
    network and is encrypted at rest there; the webui never stores or logs it.
    CSRF-protected (the JS sends X-CSRFToken)."""
    body = request.get_json(silent=True) or {}
    payload = {
        "provider": (body.get("provider") or "").strip().lower(),
        "model": (body.get("model") or "").strip(),
        "api_key": body.get("api_key") or "",
    }
    try:
        resp = requests.put(
            f"{API_URL}/agent/model", json=payload, headers=API_HEADERS, timeout=5
        )
    except requests.RequestException:
        return jsonify({"error": "orchestrator unreachable"}), 502
    if resp.status_code == 200:
        return jsonify(resp.json())
    return jsonify({"error": _api_error(resp)}), resp.status_code


@app.route("/api/model-connection", methods=["DELETE"])
def model_connection_delete():
    """Forget the operator's stored model credential (proxies DELETE
    /agent/model). CSRF-protected."""
    try:
        resp = requests.delete(
            f"{API_URL}/agent/model", headers=API_HEADERS, timeout=5
        )
    except requests.RequestException:
        return jsonify({"error": "orchestrator unreachable"}), 502
    if resp.status_code == 200:
        return jsonify(resp.json())
    return jsonify({"error": _api_error(resp)}), resp.status_code


@app.route("/api/model-connection/verify", methods=["POST"])
def model_connection_verify():
    """Best-effort 'test connection' for the operator's model key (proxies
    POST /agent/model/verify). With provider+api_key in the body, tests the
    supplied key (pre-save); otherwise tests the stored one. CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {
        "provider": (body.get("provider") or "").strip().lower() or None,
        "model": (body.get("model") or "").strip() or None,
        "api_key": body.get("api_key") or None,
    }
    try:
        resp = requests.post(
            f"{API_URL}/agent/model/verify", json=payload, headers=API_HEADERS, timeout=8
        )
    except requests.RequestException:
        return jsonify({"verified": False, "checked": False, "detail": "orchestrator unreachable"}), 502
    if resp.status_code == 200:
        return jsonify(resp.json())
    return jsonify({"verified": False, "checked": False, "detail": _api_error(resp)}), resp.status_code


@app.route("/api/copilot", methods=["POST"])
def copilot():
    """Stream a co-pilot reply (proxies the orchestrator's streaming /agent/chat).
    The model + key live in the orchestrator's custody; the webui only relays the
    text stream. CSRF-protected (the JS sends X-CSRFToken)."""
    body = request.get_json(silent=True) or {}
    payload = {"arena_id": body.get("arena_id"), "messages": body.get("messages") or []}

    def generate():
        try:
            with requests.post(
                f"{API_URL}/agent/chat", json=payload, headers=API_HEADERS,
                stream=True, timeout=125,
            ) as r:
                if r.status_code != 200:
                    yield f"[co-pilot] {_api_error(r)}".encode()
                    return
                for chunk in r.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
        except requests.RequestException:
            yield b"[co-pilot] orchestrator unreachable"

    return Response(stream_with_context(generate()), mimetype="text/plain; charset=utf-8")


@app.route("/api/setup/<instance_id>", methods=["GET"])
def setup_status_proxy(instance_id):
    """Configurator setup-session status for the arena-detail panel."""
    data, _ = _api_get(f"/arenas/{instance_id}/setup")
    return jsonify(data or {"open": False})


@app.route("/api/setup/<instance_id>/start", methods=["POST"])
def setup_start_proxy(instance_id):
    body = request.get_json(silent=True) or {}
    payload = {
        "mode": body.get("mode", "operator"),
        "time_box_seconds": int(body.get("time_box_seconds", 1800)),
        "command_budget": int(body.get("command_budget", 50)),
        "setup_egress": bool(body.get("setup_egress", False)),
    }
    data, code = _api_post(f"/arenas/{instance_id}/setup/start", payload)
    return jsonify(data), code


@app.route("/api/setup/<instance_id>/step", methods=["POST"])
def setup_step_proxy(instance_id):
    body = request.get_json(silent=True) or {}
    data, code = _api_post(
        f"/arenas/{instance_id}/setup/step",
        {"node": body.get("node", ""), "command": body.get("command", "")},
    )
    return jsonify(data), code


@app.route("/api/setup/<instance_id>/finish", methods=["POST"])
def setup_finish_proxy(instance_id):
    data, code = _api_post(f"/arenas/{instance_id}/setup/finish")
    return jsonify(data), code


@app.route("/api/setup/<instance_id>/proposals/<step_id>/<decision>", methods=["POST"])
def setup_decision_proxy(instance_id, step_id, decision):
    if decision not in ("approve", "reject"):
        return jsonify({"error": "bad decision"}), 400
    data, code = _api_post(f"/arenas/{instance_id}/setup/proposals/{step_id}/{decision}")
    return jsonify(data), code


@app.route("/api/poll/<instance_id>")
def poll_status(instance_id):
    try:
        resp = requests.get(f"{API_URL}/status/{instance_id}", headers=API_HEADERS, timeout=5)
        return jsonify(resp.json())
    except requests.RequestException:
        return jsonify({"status": "offline"})


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)  # nosec B104
