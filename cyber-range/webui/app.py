import hmac
import os
import re
from datetime import datetime, timedelta

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

# Public URL a BYO agent app (Claude Code, etc.) points its MCP client at to reach
# the agent gateway. Shown in the in-arena "connect recipe" — override per host.
GATEWAY_PUBLIC_URL = os.getenv("GATEWAY_PUBLIC_URL", "http://localhost:9000/mcp")

# Operator login for the dashboard itself.
WEBUI_USERNAME = os.getenv("WEBUI_USERNAME", "admin")
WEBUI_PASSWORD = os.getenv("WEBUI_PASSWORD", "nidavellir")

if WEBUI_PASSWORD == "nidavellir":  # noqa: S105 - detecting the default, not setting it
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
    # .get(), not bare subscript: a catalog item missing 'kind'/'available' must
    # not 500 the Overview/Launch/Scenarios pages (they all call _catalog).
    attackers = [i for i in images if i.get("kind") == "attacker" and i.get("available")]
    victims = [i for i in images if i.get("kind") == "victim" and i.get("available")]
    return images, attackers, victims


def _events(instance_id=None, limit=100, type=None):
    path = f"/deployments/{instance_id}/events" if instance_id else "/events"
    q = f"?limit={int(limit)}" + (f"&type={type}" if type else "")
    data, _ = _api_get(f"{path}{q}")
    return (data or {}).get("events", [])


def _current_agent():
    """The most recently connected BYO agent's model + provider, from the latest
    `agent_session` event (events are newest-first). None when no agent has
    announced itself. Powers the topbar 'connected model' chip."""
    for e in _events(limit=50, type="agent_session"):  # type-filtered: survives activity floods
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


# --- agents overview (the Agents console) -----------------------------------
# Bring-your-own agents reach an arena through the MCP gateway and surface in the
# append-only audit stream: an `agent_session` event = a connection (model /
# provider / stance) and agent_exec / setup_* / finding events are its per-step
# trace. This aggregates them into live connections + a recent activity timeline
# (an attribution view over `events`, not a live socket).
_AGENT_EVENT_TYPES = (
    "agent_session", "agent_exec", "setup_step", "setup_proposal",
    "setup_proposal_decision", "setup_finished", "finding",
)


def _ev_dt(ts):
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        try:
            return datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None


def _agent_summary(e):
    """A short human line for one agent-trace event (so the JS view stays dumb)."""
    p = e.get("payload") or {}
    t = e.get("type")
    cmd = (p.get("command") or "")[:80]
    if t == "agent_session":
        return f"connected · {p.get('model') or '?'} ({p.get('provider') or '?'})"
    if t in ("agent_exec", "setup_step"):
        return f"{p.get('node', '?')} · exit {p.get('exit_code')} · {cmd}"
    if t == "setup_proposal":
        return f"proposed on {p.get('node', '?')} · {cmd}"
    if t == "setup_proposal_decision":
        ex = p.get("exit_code")
        return p.get("decision", "decided") + (f" · exit {ex}" if ex is not None else "")
    if t == "setup_finished":
        return f"setup finished ({p.get('reason', '')})"
    if t == "finding":
        matched = " · ✓ matched" if p.get("matched_vuln_id") else ""
        return f"{(p.get('title') or '')[:60]} · {p.get('cwe') or '—'} · {p.get('node') or 'any'}{matched}"
    return ""


def _agent_overview(limit=200):
    """Connections + activity timeline aggregated from the audit stream."""
    events = _events(limit=limit)            # newest-first across all arenas (timeline + counts)
    # Connections come from `agent_session` events — fetched type-filtered so a
    # burst of activity events can't flood the connection cards out of the window.
    sessions = _events(limit=100, type="agent_session")
    deployments, _ = _deployments()
    name_of = {k: (v.get("user_id") or k) for k, v in deployments.items()}
    status_of = {k: v.get("status") for k, v in deployments.items()}
    now = datetime.now()

    cmds, finds, last_act = {}, {}, {}
    for e in events:
        a, t = e.get("lab_id"), e.get("type")
        if t in _AGENT_EVENT_TYPES and a not in last_act:
            last_act[a] = e.get("ts")        # newest agent event per arena
        if t in ("agent_exec", "setup_step"):
            cmds[a] = cmds.get(a, 0) + 1
        elif t == "finding":
            finds[a] = finds.get(a, 0) + 1

    conns = {}
    for e in sessions:                        # newest-first → first per (arena, stance) wins
        if e.get("type") != "agent_session":
            continue
        p = e.get("payload") or {}
        a = e.get("lab_id")
        stance = p.get("stance") or "agent"
        if (a, stance) in conns:
            continue
        seen = last_act.get(a)
        dt = _ev_dt(seen)
        active = bool(
            status_of.get(a) == "active" and dt and (now - dt) < timedelta(minutes=10)
        )
        conns[(a, stance)] = {
            "arena_id": a, "arena_name": name_of.get(a, (a or "")[:8]),
            "status": status_of.get(a), "stance": stance,
            "model": p.get("model"), "provider": (p.get("provider") or "").lower(),
            "actor": p.get("actor") or e.get("actor"),
            "last_seen": seen, "active": active,
            "commands": cmds.get(a, 0), "findings": finds.get(a, 0),
        }

    timeline = [
        {
            "ts": e.get("ts"), "arena_id": e.get("lab_id"),
            "arena_name": name_of.get(e.get("lab_id"), (e.get("lab_id") or "")[:8]),
            "type": e.get("type"), "actor": e.get("actor"),
            "stance": (e.get("payload") or {}).get("stance"),
            "summary": _agent_summary(e),
        }
        for e in events if e.get("type") in _AGENT_EVENT_TYPES
    ][:80]

    connections = sorted(conns.values(), key=lambda c: (not c["active"], c["arena_name"] or ""))
    return {"connections": connections, "timeline": timeline, "total": len(connections)}


def _score(instance_id):
    """The arena's benchmark scorecard (known-vuln manifest + found/missed).
    Operator-only on the API; the WebUI key is operator/admin. Returns None when
    the scenario has no manifest (so the panel hides itself)."""
    data, ok = _api_get(f"/arenas/{instance_id}/score")
    if not ok or not data or not data.get("manifest"):
        return None
    return data


# Which actor a log line belongs to — the Logs page and the Dashboard feed group
# events into agents (the AI under test), human (operator actions), and system
# (lifecycle/automation). Computed server-side so the templates/JS stay dumb.
_AGENT_SRC = ("agent_session", "agent_exec", "setup_step", "setup_proposal", "finding")
_HUMAN_SRC = ("created", "record_deleted", "setup_proposal_decision")


def _event_source(e):
    t = e.get("type")
    if t in _AGENT_SRC:
        return "agent"
    if t in _HUMAN_SRC:
        return "human"
    return "system"


def _annotate_source(events):
    for e in events:
        e["source"] = _event_source(e)
    return events


def _read_first(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return ""


def _host_metrics():
    """Best-effort host capacity from /proc (no extra dependency). Returns
    percentages (0-100) and uptime; any unreadable metric is None so the panel
    degrades gracefully off-Linux."""
    cpu = mem = disk = uptime = None
    try:
        load1 = float(_read_first("/proc/loadavg").split()[0])
        ncpu = os.cpu_count() or 1
        cpu = min(100, round(load1 / ncpu * 100))
    except (ValueError, IndexError):
        pass
    meminfo = {}
    for line in _read_first("/proc/meminfo").splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            meminfo[parts[0]] = parts[1].strip()
    try:
        total_kb = int(meminfo.get("MemTotal", "0").split()[0])
        avail_kb = int(meminfo.get("MemAvailable", "0").split()[0])
        if total_kb:
            mem = round((total_kb - avail_kb) / total_kb * 100)
            mem_used_gb = round((total_kb - avail_kb) / 1048576, 1)
            mem_total_gb = round(total_kb / 1048576, 1)
    except (ValueError, IndexError):
        mem_used_gb = mem_total_gb = None
    try:
        st = os.statvfs("/")
        if st.f_blocks:
            disk = round((st.f_blocks - st.f_bfree) / st.f_blocks * 100)
    except OSError:
        pass
    try:
        secs = int(float(_read_first("/proc/uptime").split()[0]))
        d, rem = divmod(secs, 86400)
        h = rem // 3600
        uptime = f"{d}d {h}h" if d else f"{h}h"
    except (ValueError, IndexError):
        pass
    return {
        "cpu": cpu, "mem": mem, "disk": disk, "uptime": uptime,
        "mem_used_gb": mem_used_gb, "mem_total_gb": mem_total_gb,
    }


def _system_usage():
    """Host capacity + arena footprint for the Dashboard gauges. Container and
    network counts are aggregated from the live deployments' provider outputs
    (the webui has no Docker socket); host CPU/mem/disk come from /proc."""
    deployments, ok = _deployments()
    active = [v for v in deployments.values()
              if v.get("status") not in ("destroyed", "failed", "error_destroying")]
    containers = nets = 0
    for v in active:
        o = v.get("outputs") or {}
        containers += sum(1 for k in o if re.match(r"^node_(.+)_name$", k))
        labnets = o.get("lab_networks") or ([o["lab_network"]] if o.get("lab_network") else [])
        nets += len(labnets) if isinstance(labnets, list) else 0
    m = _host_metrics()
    m.update({
        "ok": ok,
        "containers": containers,
        "networks": nets,
        "active_arenas": len(active),
    })
    return m


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
            # All published container→host port mappings, so the operator can reach
            # non-web services on a multi-port box (not just the web Open button).
            "ports": outputs.get(f"node_{n}_ports") or {},
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
                           recent=recent, backend_ok=ok,
                           events=_annotate_source(_events(limit=12)))


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


@app.route("/wizard")
def wizard():
    """Guided arena authoring (P3-3): a step-by-step SUT flow — target → setup
    consent → review (no-deploy topology) → launch."""
    return render_template("wizard.html", active="wizard")


@app.route("/api/arenas/sut/preview", methods=["POST"])
def sut_preview_proxy():
    """No-deploy review for the wizard (proxies POST /arenas/sut/preview)."""
    body = request.get_json(silent=True) or {}
    payload = {
        "instance_id": (body.get("instance_id") or "wizard-preview").strip() or "wizard-preview",
        "repo": (body.get("repo") or "").strip(),
        "ref": (body.get("ref") or "").strip() or None,
        "ports": body.get("ports") or [],
        "include_attacker": bool(body.get("include_attacker", True)),
    }
    data, code = _api_post("/arenas/sut/preview", payload)
    return jsonify(data), code


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
    events = _events(instance_id, limit=30)
    scenario = data.get("scenario", "") or ""
    # A "configurable" (software-under-test) arena is one whose victim must be
    # brought up before the engagement — the wizard (`sut:<repo>`), a clone/source
    # node (`*_setup_shell` / `*_sut_source`), or one with a recorded setup phase.
    # Predefined vulnerable labs are already armed, so the configurator is hidden
    # for them; only agent positioning applies.
    ev_types = {e.get("type") for e in events}
    is_sut = (
        scenario.startswith("sut:")
        or any(k.endswith(("_setup_shell", "_sut_source")) for k in outputs)
        or bool(ev_types & {"setup_prearm", "setup_session", "setup_step"})
    )
    return render_template(
        "arena_detail.html", active="arenas",
        instance_id=instance_id,
        instance_name=data.get("user_id", instance_id),
        state=data.get("status", "unknown"),
        outputs=outputs,
        nodes=_parse_nodes(outputs),
        unhealthy=outputs.get("unhealthy_nodes"),
        provider=outputs.get("provider") or data.get("provider"),
        events=events,
        score=_score(instance_id),
        scenario=scenario,
        is_sut=is_sut,
        gateway_url=GATEWAY_PUBLIC_URL,
    )


@app.route("/agents")
def agents():
    return render_template("agents.html", active="agents", overview=_agent_overview())


@app.route("/audit")
def audit():
    return render_template("audit.html", active="audit",
                           events=_annotate_source(_events(limit=150)))


@app.route("/settings")
def settings():
    return render_template("settings.html", active="settings")


@app.route("/profile")
def profile():
    return render_template("profile.html", active="profile",
                           username=session.get("username", "operator"))


@app.route("/api/system-usage")
def system_usage():
    """Host capacity + arena footprint for the Dashboard gauges."""
    return jsonify(_system_usage())


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
    # Multiple attack machines (P1-7): the form sends `attackers` (multi-select);
    # fall back to a single `attacker` for older markup.
    attackers = request.form.getlist("attackers") or (
        [request.form.get("attacker")] if request.form.get("attacker") else []
    )
    victims = request.form.getlist("victims")
    try:
        resp = requests.post(f"{API_URL}/arenas/custom", json={
            "instance_id": instance_id, "attackers": attackers, "victims": victims,
        }, headers=API_HEADERS, timeout=10)
        if resp.status_code == 200:
            flash(f"Building '{instance_id}': {' + '.join(attackers)} vs "
                  f"{', '.join(victims)} (images pulled on first use)", "info")
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
    # The wizard surfaces the time-box + step budget; pass them through when given.
    if f.get("time_box_seconds"):
        payload["time_box_seconds"] = int(re.sub(r"\D", "", f["time_box_seconds"]) or 0)
    if f.get("command_budget"):
        payload["command_budget"] = int(re.sub(r"\D", "", f["command_budget"]) or 0)
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


@app.route("/api/agents")
def api_agents():
    """JSON for the Agents console poller — connections + activity trace."""
    return jsonify(_agent_overview())


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


@app.route("/api/setup/<instance_id>/generate-proposals", methods=["POST"])
def setup_generate_proposals_proxy(instance_id):
    """Have the operator's connected model draft HITL setup proposals (Field-C).
    The model call can be slow, so allow a longer timeout. CSRF-protected."""
    data, code = _api_post(f"/arenas/{instance_id}/setup/generate-proposals", timeout=120)
    return jsonify(data), code


# --- scenario authoring & import (P1-7) + topology preview (P7-9) -----------
@app.route("/api/scenarios/preview", methods=["POST"])
def scenario_preview_proxy():
    """Dry-run validate + topology for the launch / import previews (proxies
    POST /scenarios/preview). CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {}
    if body.get("picks") is not None:
        payload["picks"] = body.get("picks")
    if body.get("spec") is not None:
        payload["spec"] = body.get("spec")
    data, code = _api_post("/scenarios/preview", payload)
    return jsonify(data), code


@app.route("/api/scenarios/generate", methods=["POST"])
def scenario_generate_proxy():
    """Generate a candidate v3 spec from a prompt using the operator's connected
    model (proxies POST /scenarios/generate). Returns the spec + topology for
    review — never deploys/saves. The model call can be slow, so allow a longer
    timeout. CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {"prompt": (body.get("prompt") or "").strip()}
    if body.get("provider_class"):
        payload["provider_class"] = str(body["provider_class"]).strip()
    data, code = _api_post("/scenarios/generate", payload, timeout=120)
    return jsonify(data), code


@app.route("/api/scenarios/import", methods=["POST"])
def scenario_import_proxy():
    """Persist an operator-pasted scenario as a reusable pack (proxies
    POST /scenarios). CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {
        "spec": body.get("spec"),
        "id": body.get("id") or None,
        "overwrite": bool(body.get("overwrite")),
    }
    data, code = _api_post("/scenarios", payload)
    return jsonify(data), code


@app.route("/api/scenarios/import/vulhub", methods=["POST"])
def scenario_import_vulhub_proxy():
    """Convert a Vulhub environment into a v3 pack (proxies
    POST /scenarios/import/vulhub). ``dry_run`` previews; otherwise it saves.
    CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {
        "ref": (body.get("ref") or "").strip() or "master",
        "include_attacker": body.get("include_attacker", True),
        "dry_run": bool(body.get("dry_run")),
        "overwrite": bool(body.get("overwrite")),
    }
    if body.get("path"):
        payload["path"] = str(body["path"]).strip()
    if body.get("compose") is not None:
        payload["compose"] = body.get("compose")
    if body.get("id"):
        payload["id"] = body.get("id")
    if body.get("name"):
        payload["name"] = body.get("name")
    data, code = _api_post("/scenarios/import/vulhub", payload)
    return jsonify(data), code


@app.route("/api/scenarios/<scenario_id>/topology", methods=["GET"])
def scenario_topology_proxy(scenario_id):
    """Topology graph of a registered scenario for the pre-deploy preview."""
    data, ok = _api_get(f"/scenarios/{scenario_id}/topology")
    return jsonify(data or {"topology": None}), (200 if ok else 404)


@app.route("/api/arenas/<instance_id>/events", methods=["GET"])
def arena_events_proxy(instance_id):
    """Recent audit events for this arena — feeds the in-arena live activity log
    (every agent tool call, finding, connection, setup step). Read-only."""
    limit = request.args.get("limit", 40)
    return jsonify({"events": _events(instance_id, limit=limit)}), 200


@app.route("/api/arenas/<instance_id>/bindings", methods=["GET"])
def list_bindings_proxy(instance_id):
    """Active agent↔arena bindings (D1) for the operator console."""
    data, ok = _api_get(f"/arenas/{instance_id}/bindings")
    return jsonify(data or {"bindings": []}), (200 if ok else 502)


@app.route("/api/arenas/<instance_id>/bindings", methods=["POST"])
def grant_binding_proxy(instance_id):
    """Authorize a BYO agent key to drive this arena in a stance (proxies
    POST /arenas/<id>/bindings). CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {
        "agent_name": (body.get("agent_name") or "").strip(),
        "stance": (body.get("stance") or "").strip() or None,
    }
    data, code = _api_post(f"/arenas/{instance_id}/bindings", payload)
    return jsonify(data), code


@app.route("/api/arenas/<instance_id>/bindings/<agent_name>", methods=["DELETE"])
def revoke_binding_proxy(instance_id, agent_name):
    """Revoke an agent's binding (proxies DELETE). CSRF-protected."""
    try:
        resp = requests.delete(
            f"{API_URL}/arenas/{instance_id}/bindings/{agent_name}",
            headers=API_HEADERS, timeout=10,
        )
    except requests.RequestException:
        return jsonify({"error": "orchestrator unreachable"}), 502
    if resp.status_code == 200:
        return jsonify(resp.json())
    return jsonify({"error": _api_error(resp)}), resp.status_code


@app.route("/api/arenas/<instance_id>/bindings/<agent_name>/pause", methods=["POST"])
def pause_binding_proxy(instance_id, agent_name):
    """Pause (kill-switch) an agent's binding (proxies POST …/pause). CSRF-protected."""
    data, code = _api_post(f"/arenas/{instance_id}/bindings/{agent_name}/pause")
    return jsonify(data), code


@app.route("/api/arenas/<instance_id>/bindings/<agent_name>/resume", methods=["POST"])
def resume_binding_proxy(instance_id, agent_name):
    """Resume a paused binding (proxies POST …/resume). CSRF-protected."""
    data, code = _api_post(f"/arenas/{instance_id}/bindings/{agent_name}/resume")
    return jsonify(data), code


@app.route("/api/scenarios/<scenario_id>", methods=["DELETE"])
def scenario_delete_proxy(scenario_id):
    """Delete an imported scenario pack (proxies DELETE /scenarios/<id>).
    CSRF-protected."""
    try:
        resp = requests.delete(
            f"{API_URL}/scenarios/{scenario_id}", headers=API_HEADERS, timeout=10
        )
    except requests.RequestException:
        return jsonify({"error": "orchestrator unreachable"}), 502
    if resp.status_code == 200:
        return jsonify(resp.json())
    return jsonify({"error": _api_error(resp)}), resp.status_code


@app.route("/api/poll/<instance_id>")
def poll_status(instance_id):
    try:
        resp = requests.get(f"{API_URL}/status/{instance_id}", headers=API_HEADERS, timeout=5)
        data = resp.json()
    except (requests.RequestException, ValueError):
        return jsonify({"status": "offline"})
    # A non-200 (404 destroyed/unknown, 5xx) carries no `status` key — the poller
    # reads d.status, so normalize it instead of handing back {"detail": ...} that
    # would render a permanent UNKNOWN and stall the active-state transition.
    if resp.status_code != 200:
        return jsonify({"status": data.get("status", "unknown")})
    return jsonify(data)


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)  # nosec B104
