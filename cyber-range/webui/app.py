import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

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
app.config["MAX_CONTENT_LENGTH"] = int(
    os.getenv("WEBUI_MAX_UPLOAD_BYTES", str(34 * 1024 * 1024))
)
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
    if isinstance(detail, list):  # pydantic validation errors — name the field
        parts = []
        for e in detail:
            loc = [str(x) for x in (e.get("loc") or []) if x != "body"]
            field = loc[-1] if loc else None
            msg = e.get("msg", "invalid")
            parts.append(f"{field}: {msg}" if field else msg)
        detail = "; ".join(parts)
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
    if resp.status_code not in (200, 202):
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
    """The arena's structured scorecard (ADR-0009): benchmark manifest view AND
    the discovery-mode view (crash-oracle fault sites + confirmed findings +
    progress). Operator-only on the API; the WebUI key is operator/admin. Returns
    None only when the API has no score at all — NOT merely when there's no
    manifest, so discovery arenas render their result too."""
    data, ok = _api_get(f"/arenas/{instance_id}/score")
    if not ok or not data:
        return None
    return data


def _findings(instance_id):
    """The arena's reported findings (operator view — includes the manifest match
    and the verification verdict). Merges the newest operator verify verdict onto
    each finding (a human confirm/refute overrides any auto-verdict). Newest
    first. Fetches untyped so `finding` + `finding_verification` come together."""
    events = _events(instance_id, limit=200)
    verdicts = {}
    for e in events:  # newest-first → first seen per finding wins
        if e.get("type") == "finding_verification":
            p = e.get("payload") or {}
            fid = p.get("finding_id")
            if fid and fid not in verdicts:
                verdicts[fid] = p
    out = []
    for e in events:
        if e.get("type") != "finding":
            continue
        p = {**(e.get("payload") or {}), "ts": e.get("ts")}
        v = verdicts.get(p.get("finding_id"))
        if v:
            p["operator_verdict"] = v.get("verdict")
            p["validation"] = {
                "confirmed": v.get("verdict") == "confirmed",
                "method": "operator", "by": v.get("actor"), "note": v.get("note"),
            }
        out.append(p)
    return out


def _setup_steps(instance_id):
    """Executed configurator steps (command + real stdout/stderr) for the setup
    console — the live feedback an operator was missing on agent-proposed steps.
    Returned oldest→newest so the console reads top-to-bottom like a terminal."""
    steps = []
    for e in _events(instance_id, limit=100, type="setup_step"):
        p = e.get("payload") or {}
        steps.append({**p, "ts": e.get("ts")})
    steps.reverse()  # events are newest-first
    return steps


def _arena_names():
    """arena id → the operator-facing engagement name, for cross-arena indexes."""
    deployments, _ = _deployments()
    return {k: (v.get("user_id") or k) for k, v in deployments.items()}


def _finding_verdict(finding):
    confirmed = (finding.get("validation") or {}).get("confirmed")
    if confirmed is True:
        return "confirmed"
    if confirmed is False:
        return "refuted"
    return "unverified"


def _all_findings(limit=200, names=None):
    """Findings across every engagement, newest first, with the operator verdict merged.

    `_findings` answers the same question for one arena; the Activity index needs it
    globally, so it folds the two type-filtered event streams together and tags each
    finding with the engagement it belongs to.
    """
    names = _arena_names() if names is None else names
    verdicts = {}
    for event in _events(limit=limit, type="finding_verification"):
        payload = event.get("payload") or {}
        finding_id = payload.get("finding_id")
        if finding_id and finding_id not in verdicts:  # newest-first: first wins
            verdicts[finding_id] = payload
    out = []
    for event in _events(limit=limit, type="finding"):
        finding = {**(event.get("payload") or {}), "ts": event.get("ts")}
        arena_id = event.get("lab_id")
        finding["arena_id"] = arena_id
        finding["arena_name"] = names.get(arena_id, (arena_id or "")[:8])
        # An engagement record can be pruned while its finding events remain; say so
        # rather than offering a link or a download that cannot resolve.
        finding["arena_known"] = arena_id in names
        verdict = verdicts.get(finding.get("finding_id"))
        if verdict:  # a human verdict overrides any automatic one
            finding["validation"] = {
                "confirmed": verdict.get("verdict") == "confirmed",
                "method": "operator",
                "by": verdict.get("actor"),
            }
        finding["verdict"] = _finding_verdict(finding)
        out.append(finding)
    return out


def _all_evidence(limit=200, names=None, findings=None):
    """Cross-engagement evidence: content-addressed artifacts and monitor signals.

    Artifacts are reached through the findings that reference them, so provenance
    stays attached; signals come from the monitor's own append-only events.
    """
    names = _arena_names() if names is None else names
    findings = _all_findings(limit, names) if findings is None else findings
    artifacts = [
        {
            **artifact,
            "arena_id": finding.get("arena_id"),
            "arena_name": finding.get("arena_name"),
            "finding_id": finding.get("finding_id"),
            "finding_title": finding.get("title"),
            "arena_known": finding.get("arena_known"),
            "ts": finding.get("ts"),
        }
        for finding in findings
        for artifact in (finding.get("evidence_artifacts") or [])
    ]
    signals = []
    for event in _events(limit=limit, type="monitor_signal"):
        arena_id = event.get("lab_id")
        signals.append({
            **(event.get("payload") or {}),
            "arena_id": arena_id,
            "arena_name": names.get(arena_id, (arena_id or "")[:8]),
            "arena_known": arena_id in names,
            "ts": event.get("ts"),
        })
    return artifacts, signals


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
    if request.endpoint in ("login", "static", "favicon", "orchestrator_health"):
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/favicon.ico")
def favicon():
    """Browsers request this path even when <link rel="icon"> names another file."""
    return redirect(url_for("static", filename="anvil_logo.png"))


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
    """Home, composed from the product objects an operator actually acts on:
    live engagements, findings waiting on a verdict, and anything needing attention."""
    deployments, ok = _deployments()
    scenarios = _scenarios()
    names = {k: (v.get("user_id") or k) for k, v in deployments.items()}
    findings = _all_findings(limit=120, names=names)

    by = {}
    for v in deployments.values():
        by[v.get("status")] = by.get(v.get("status"), 0) + 1

    live = [
        (k, v) for k, v in deployments.items()
        if v.get("status") not in ("destroyed", "failed", "error_destroying")
    ]
    review_queue = [f for f in findings if f["verdict"] == "unverified"]

    # Attention: a run that broke, and a live arena that can reach the internet.
    # Both are operator decisions, so Home states them instead of burying them.
    attention = []
    for arena_id, record in deployments.items():
        status = record.get("status")
        if status in ("failed", "error_destroying"):
            attention.append({
                "kind": "failed", "arena_id": arena_id,
                "name": names.get(arena_id, arena_id), "status": status,
                "detail": "The run stopped before it could finish.",
            })
        elif status == "active" and (record.get("outputs") or {}).get("egress") == "open":
            attention.append({
                "kind": "containment", "arena_id": arena_id,
                "name": names.get(arena_id, arena_id), "status": status,
                "detail": "This arena can reach the internet — containment is relaxed.",
            })

    stats = {
        "live": len(live),
        "total": len(deployments),
        "transient": sum(by.get(s, 0) for s in _TRANSIENT),
        "review": len(review_queue),
        "attention": len(attention),
        "scenarios": len(scenarios),
    }

    archived = [(k, v) for k, v in deployments.items() if v.get("status") == "destroyed"]
    return render_template(
        "overview.html", active="overview", stats=stats,
        live=live[:6], recent=archived[:4], attention=attention[:5],
        review_queue=review_queue[:6], backend_ok=ok,
        events=_annotate_source(_events(limit=12)),
    )


@app.route("/arenas")
def arenas():
    deployments, _ = _deployments()
    current = {k: v for k, v in deployments.items() if v.get("status") != "destroyed"}
    archived = {k: v for k, v in deployments.items() if v.get("status") == "destroyed"}
    return render_template("arenas.html", active="arenas", current=current, archived=archived)


@app.route("/engagements")
def engagements():
    """Target-language alias while the arena list remains the backing view."""
    return arenas()


_ENGAGEMENT_PURPOSES = (
    {
        "id": "benchmark",
        "label": "Benchmark",
        "icon": "fa-chart-line",
        "description": "Measure an agent or workflow against known objectives.",
    },
    {
        "id": "discovery",
        "label": "Discovery",
        "icon": "fa-magnifying-glass",
        "description": "Find unknown weaknesses or regressions in a target.",
    },
    {
        "id": "calibration",
        "label": "Calibration",
        "icon": "fa-sliders",
        "description": "Validate tools, policies, containment, and scoring behavior.",
    },
    {
        "id": "research",
        "label": "Manual research",
        "icon": "fa-flask",
        "description": "Run an operator-led investigation without comparison semantics.",
    },
)
_ENGAGEMENT_PURPOSE_BY_ID = {item["id"]: item for item in _ENGAGEMENT_PURPOSES}
_ENGAGEMENT_SOURCES = {"challenge", "target"}
_ENGAGEMENT_PARTICIPANTS = (
    {"id": "operator", "label": "Operator-led", "description": "A human drives the engagement; agents may be connected later."},
    {"id": "agent", "label": "Agent-led", "description": "A bound autonomous agent is the primary participant."},
    {"id": "mixed", "label": "Mixed", "description": "Human and bound agents collaborate in the same engagement."},
)
_ENGAGEMENT_PARTICIPANT_BY_ID = {
    item["id"]: item for item in _ENGAGEMENT_PARTICIPANTS
}
_ENGAGEMENT_TIME_BOXES = {1800: "30 minutes", 3600: "1 hour", 7200: "2 hours", 14400: "4 hours"}


def _engagement_purpose(value):
    return _ENGAGEMENT_PURPOSE_BY_ID.get(value)


def _engagement_participant(value):
    return _ENGAGEMENT_PARTICIPANT_BY_ID.get(value)


def _engagement_time_box(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds in _ENGAGEMENT_TIME_BOXES else None


@app.route("/engagements/new", methods=["GET", "POST"])
def new_engagement():
    """Choose engagement intent and source before entering an existing builder."""
    selected_purpose = request.values.get("purpose", "")
    selected_source = request.values.get("source", "")
    selected_participant = request.values.get("participant_mode", "operator")
    selected_time_box = _engagement_time_box(
        request.values.get("engagement_time_box_seconds", 3600)
    )
    if request.method == "POST":
        if selected_purpose not in _ENGAGEMENT_PURPOSE_BY_ID:
            flash("Choose the engagement purpose.", "warning")
        elif selected_source not in _ENGAGEMENT_SOURCES:
            flash("Choose a challenge or target source.", "warning")
        elif selected_participant not in _ENGAGEMENT_PARTICIPANT_BY_ID:
            flash("Choose who will drive the engagement.", "warning")
        elif selected_time_box is None:
            flash("Choose a supported engagement time box.", "warning")
        else:
            endpoint = "launch" if selected_source == "challenge" else "wizard"
            return redirect(
                url_for(
                    endpoint,
                    purpose=selected_purpose,
                    participant_mode=selected_participant,
                    engagement_time_box_seconds=selected_time_box,
                )
            )
    return render_template(
        "engagement_new.html",
        active="engagement_new",
        purposes=_ENGAGEMENT_PURPOSES,
        participants=_ENGAGEMENT_PARTICIPANTS,
        time_boxes=_ENGAGEMENT_TIME_BOXES,
        selected_purpose=selected_purpose,
        selected_source=selected_source,
        selected_participant=selected_participant,
        selected_time_box=selected_time_box,
    )


@app.route("/launch")
def launch():
    _, attackers, victims = _catalog()
    default_infra = _default_infra()
    scenarios = _scenarios()
    # Compatible scenarios first, so the (auto-selected) first option is runnable.
    scenarios.sort(key=lambda s: default_infra not in ("any", s.get("provider_class")))
    return render_template("launch.html", active="launch", scenarios=scenarios,
                           attackers=attackers, victims=victims, default_infra=default_infra,
                           engagement_purpose=_engagement_purpose(request.args.get("purpose")),
                           engagement_participant=_engagement_participant(request.args.get("participant_mode")),
                           engagement_time_box=_engagement_time_box(request.args.get("engagement_time_box_seconds")),
                           engagement_time_box_label=_ENGAGEMENT_TIME_BOXES.get(_engagement_time_box(request.args.get("engagement_time_box_seconds"))),
                           engagement_source="Challenge",
                           selected_scenario=request.args.get("scenario", ""))


@app.route("/wizard")
def wizard():
    """Guided arena authoring (P3-3): a step-by-step SUT flow — target → setup
    consent → review (no-deploy topology) → launch."""
    return render_template(
        "wizard.html",
        active="wizard",
        engagement_purpose=_engagement_purpose(request.args.get("purpose")),
        engagement_participant=_engagement_participant(request.args.get("participant_mode")),
        engagement_time_box=_engagement_time_box(request.args.get("engagement_time_box_seconds")),
        engagement_time_box_label=_ENGAGEMENT_TIME_BOXES.get(_engagement_time_box(request.args.get("engagement_time_box_seconds"))),
        engagement_source="Target",
    )


@app.route("/api/arenas/sut/preview", methods=["POST"])
def sut_preview_proxy():
    """No-deploy review for Git or OCI targets in the research wizard."""
    body = request.get_json(silent=True) or {}
    target_type = body.get("target_type") or "git"
    payload = {
        "instance_id": (body.get("instance_id") or "wizard-preview").strip() or "wizard-preview",
        "engagement_purpose": body.get("engagement_purpose") or None,
        "participant_mode": body.get("participant_mode") or None,
        "engagement_time_box_seconds": body.get("engagement_time_box_seconds") or None,
        "ports": body.get("ports") or [],
        "include_attacker": bool(body.get("include_attacker", True)),
        "authorization_basis": body.get("authorization_basis") or "public_oss",
        "authorization_confirmed": bool(body.get("authorization_confirmed")),
        "scope_note": (body.get("scope_note") or "").strip() or None,
    }
    if target_type == "oci":
        payload["image"] = (body.get("image") or "").strip()
        payload["platform"] = body.get("platform") or "linux/amd64"
        endpoint = "/arenas/oci/preview"
    elif target_type == "bundle":
        payload["artifact_digest"] = (body.get("artifact_digest") or "").strip()
        payload["setup_mode"] = body.get("setup_mode") or "operator"
        payload["setup_egress"] = bool(body.get("setup_egress", True))
        payload["time_box_seconds"] = body.get("time_box_seconds") or 1800
        payload["command_budget"] = body.get("command_budget") or 50
        endpoint = "/arenas/source-bundle/preview"
    else:
        payload["repo"] = (body.get("repo") or "").strip()
        payload["ref"] = (body.get("ref") or "").strip() or None
        endpoint = "/arenas/sut/preview"
    data, code = _api_post(endpoint, payload)
    return jsonify(data), code


@app.route("/api/targets/source-bundles", methods=["POST"])
def source_bundle_upload_proxy():
    """Stream one local bundle to the orchestrator's bounded intake endpoint."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "select a .tar, .tar.gz, or .tgz source bundle"}), 422
    try:
        response = requests.post(
            f"{API_URL}/targets/source-bundles",
            files={
                "file": (
                    upload.filename,
                    upload.stream,
                    upload.mimetype or "application/octet-stream",
                )
            },
            headers=API_HEADERS,
            timeout=60,
        )
    except requests.RequestException:
        return jsonify({"error": "orchestrator unreachable"}), 502
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200:
        return jsonify({"error": _api_error(response)}), response.status_code
    return jsonify(data), 200


@app.route("/scenarios")
def scenarios():
    _, attackers, victims = _catalog()
    return render_template("scenarios.html", active="scenarios",
                           scenarios=_scenarios(), attackers=attackers, victims=victims)


@app.route("/library/challenges")
def challenge_library():
    """Target-language alias for the current scenario catalog."""
    return scenarios()


# The engagement/run workspace (ROADMAP C3, ADR-0012). One contextual surface per
# concern, in the order an operator works through them; only applicable tabs render.
_WORKSPACE_TABS = (
    ("overview", "Overview", "fa-gauge-high"),
    ("live", "Live", "fa-wave-square"),
    ("target", "Target", "fa-bullseye"),
    ("http", "HTTP", "fa-paper-plane"),
    ("poc", "PoC", "fa-terminal"),
    ("findings", "Findings", "fa-bug"),
    ("evidence", "Evidence", "fa-box-archive"),
    ("changes", "Changes", "fa-code-compare"),
    ("agent", "Agent", "fa-chess"),
    ("trace", "Trace", "fa-route"),
    ("score", "Score", "fa-flag-checkered"),
    ("infrastructure", "Infrastructure", "fa-server"),
)


def _workspace_tabs(applicable, counts=None):
    """Ordered tab descriptors for the tabs that actually have something to show.

    A count rides beside the label so an operator can see where the substance is —
    how many findings, artifacts, or changed workspaces — without opening each tab.
    """
    counts = counts or {}
    return [
        {"id": tab, "label": label, "icon": icon, "count": counts.get(tab)}
        for tab, label, icon in _WORKSPACE_TABS
        if applicable.get(tab)
    ]


@app.route("/arena/<instance_id>")
def arena_detail(instance_id):
    data, ok = _api_get(f"/status/{instance_id}")
    if not ok or data is None:
        flash(f"Arena {instance_id} not found.", "warning")
        return redirect(url_for("engagements"))
    outputs = data.get("outputs", {}) or {}
    events = _events(instance_id, limit=30)
    engagement_intent = next(
        (
            event.get("payload") or {}
            for event in events
            if event.get("type") == "engagement_intent"
        ),
        None,
    )
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
    state = data.get("status", "unknown")
    score = _score(instance_id)
    findings = _findings(instance_id)
    setup_steps = _setup_steps(instance_id)

    # A destroyed arena is a read-only record: its evidence stays readable, but
    # nothing may be launched, granted, or changed against infrastructure that is gone.
    read_only = state == "destroyed"

    monitor_signals = [
        {**(e.get("payload") or {}), "ts": e.get("ts")}
        for e in events
        if e.get("type") == "monitor_signal"
    ]
    evidence_artifacts = [
        {**artifact, "finding_id": f.get("finding_id"), "finding_title": f.get("title")}
        for f in findings
        for artifact in (f.get("evidence_artifacts") or [])
    ]
    preflight, preflight_ok = _api_get(f"/arenas/{instance_id}/preflight")
    lifecycle, lifecycle_ok = _api_get(f"/arenas/{instance_id}/lifecycle")
    if not isinstance(lifecycle, dict) or not isinstance(lifecycle.get("classification"), dict):
        lifecycle = None
        lifecycle_ok = False
    workspaces_data, _ = _api_get(f"/arenas/{instance_id}/workspaces")
    workspaces = (workspaces_data or {}).get("workspaces") or []
    # Trace/attribution only exists once a BYO agent has actually worked the arena.
    has_agent_activity = bool(
        ev_types & {"agent_session", "agent_exec", "agent_binding", "agent_setup_step"}
    )
    trace = _api_get(f"/arenas/{instance_id}/eval-export")[0] if has_agent_activity else None

    # HTTP research tab (R1 slice 6): present wherever the arena has (or had)
    # a web-capable target, or any stored transaction — so a destroyed arena's
    # records stay reviewable. Driving is refused server-side when read-only.
    http_total = (_api_get(f"/arenas/{instance_id}/http/transactions?limit=1")[0] or {}).get("total", 0)
    poc_jobs = (_api_get(f"/arenas/{instance_id}/poc-jobs")[0] or {}).get("jobs", [])
    budget = _api_get(f"/arenas/{instance_id}/budget")[0] or {}
    capabilities = _api_get(f"/arenas/{instance_id}/capabilities")[0] or {}
    forwards = (_api_get(f"/arenas/{instance_id}/forwards")[0] or {}).get("forwards", [])
    web_capable = any(
        (n.get("ports") or n.get("url")) and not n.get("foothold")
        for n in _parse_nodes(outputs)
    )

    tabs = _workspace_tabs({
        "overview": True,
        "live": True,
        "target": is_sut or bool(preflight_ok and preflight),
        "http": bool(http_total) or web_capable,
        "poc": bool(poc_jobs) or (state == "active" and web_capable),
        "findings": True,
        "evidence": bool(evidence_artifacts or monitor_signals),
        "changes": bool(workspaces),
        "agent": True,
        "trace": bool(trace),
        "score": bool(score),
        "infrastructure": True,
    }, counts={
        "findings": len(findings),
        "evidence": len(evidence_artifacts) + len(monitor_signals),
        "changes": len(workspaces),
        "http": http_total,
        "poc": len(poc_jobs),
    })

    return render_template(
        "arena_detail.html", active="arenas",
        instance_id=instance_id,
        instance_name=data.get("user_id", instance_id),
        state=state,
        outputs=outputs,
        nodes=_parse_nodes(outputs),
        unhealthy=outputs.get("unhealthy_nodes"),
        provider=outputs.get("provider") or data.get("provider"),
        events=events,
        engagement_intent=engagement_intent,
        score=score,
        findings=findings,
        setup_steps=setup_steps,
        scenario=scenario,
        is_sut=is_sut,
        gateway_url=GATEWAY_PUBLIC_URL,
        tabs=tabs,
        read_only=read_only,
        monitor_signals=monitor_signals,
        evidence_artifacts=evidence_artifacts,
        trace=trace,
        created_at=data.get("created_at"),
        expires_at=data.get("expires_at"),
        lifecycle=lifecycle if lifecycle_ok else None,
        poc_jobs=poc_jobs,
        budget=budget,
        capabilities=capabilities,
        forwards=forwards,
    )


@app.route("/arena/<instance_id>/forwards", methods=["POST"])
def arena_forward_form(instance_id):
    selection = request.form.get("service") or ""
    if ":" not in selection:
        flash("Choose a declared service", "danger")
        return redirect(url_for("arena_detail", instance_id=instance_id))
    target, service_id = selection.split(":", 1)
    data, code = _api_post(f"/arenas/{instance_id}/forwards", {
        "foothold": request.form.get("foothold") or "",
        "target": target,
        "service_id": service_id,
        "lifetime_seconds": 120,
        "idempotency_key": uuid.uuid4().hex,
    })
    flash("Forward lease opened" if code == 200 else data.get("error", "Forward failed"),
          "success" if code == 200 else "danger")
    return redirect(url_for("arena_detail", instance_id=instance_id))


@app.route("/arena/<instance_id>/forwards/<forward_id>/revoke", methods=["POST"])
def arena_forward_revoke_form(instance_id, forward_id):
    data, code = _api_post(f"/arenas/{instance_id}/forwards/{forward_id}/revoke")
    flash("Forward lease revoked" if code == 200 else data.get("error", "Revoke failed"),
          "success" if code == 200 else "danger")
    return redirect(url_for("arena_detail", instance_id=instance_id))


@app.route("/arena/<instance_id>/stop", methods=["POST"])
def arena_stop_form(instance_id):
    data, code = _api_post(f"/arenas/{instance_id}/stop", {
        "reason": (request.form.get("reason") or "Operator stopped research")[:500],
        "idempotency_key": uuid.uuid4().hex,
    })
    flash("Arena research stopped" if code == 200 else data.get("error", "Stop failed"),
          "success" if code == 200 else "danger")
    return redirect(url_for("arena_detail", instance_id=instance_id))


@app.route("/arena/<instance_id>/resume", methods=["POST"])
def arena_resume_form(instance_id):
    data, code = _api_post(f"/arenas/{instance_id}/resume", {
        "reason": (request.form.get("reason") or "Operator resumed research")[:500],
        "idempotency_key": uuid.uuid4().hex,
    })
    flash("Arena research resumed" if code == 200 else data.get("error", "Resume failed"),
          "success" if code == 200 else "danger")
    return redirect(url_for("arena_detail", instance_id=instance_id))


@app.route("/agents")
def agents():
    return render_template("agents.html", active="agents", overview=_agent_overview())


@app.route("/activity/agents")
def agent_activity():
    """Target-language alias for live agent attribution and connections."""
    return agents()


@app.route("/audit")
def audit():
    return render_template("audit.html", active="audit",
                           events=_annotate_source(_events(limit=150)))


@app.route("/activity/audit")
def audit_trail():
    """Target-language alias for the append-only audit view."""
    return audit()


@app.route("/settings")
def settings():
    system_stop = _api_get("/system/emergency-stop")[0] or {}
    return render_template("settings.html", active="settings", system_stop=system_stop)


@app.route("/settings/emergency-stop", methods=["POST"])
def system_stop_form():
    reason = (request.form.get("reason") or "Operator emergency stop")[:500]
    data, code = _api_post("/system/emergency-stop", {
        "reason": reason, "idempotency_key": uuid.uuid4().hex,
    })
    flash("System research stopped" if code == 200 else data.get("error", "Stop failed"),
          "success" if code == 200 else "danger")
    return redirect(url_for("settings"))


@app.route("/settings/emergency-stop/clear", methods=["POST"])
def system_stop_clear_form():
    reason = (request.form.get("reason") or "Operator cleared emergency stop")[:500]
    data, code = _api_post("/system/emergency-stop/clear", {
        "reason": reason, "idempotency_key": uuid.uuid4().hex,
    })
    flash("System research resumed" if code == 200 else data.get("error", "Clear failed"),
          "success" if code == 200 else "danger")
    return redirect(url_for("settings"))


@app.route("/administration/settings")
def administration_settings():
    """Target-language alias for the current console settings."""
    return settings()


_FOUNDATION_PAGES = {
    "evaluations": {
        "group": "Evaluations",
        "title": "Evaluation workbench",
        "icon": "fa-chart-column",
        "description": "Suites, repeated runs, and baseline-versus-candidate comparisons will live here.",
        "current": "The scoring engine works per arena today; durable experiments and paired comparisons are the next benchmark layer.",
        "link_endpoint": "engagements",
        "link_label": "View current engagements",
    },
    "targets": {
        "group": "Library",
        "title": "Targets",
        "icon": "fa-bullseye",
        "description": "Reusable Git, OCI, and source-bundle identities will live here.",
        "current": "Target intake is available now when creating a target-based engagement.",
        "link_endpoint": "new_engagement",
        "link_label": "Create from a target",
    },
    "agent_library": {
        "group": "Library",
        "title": "Agents",
        "icon": "fa-robot",
        "description": "Versioned agent builds, adapters, capabilities, and execution policy will live here.",
        "current": "Live connections and attribution remain available in Activity until the build registry is implemented.",
        "link_endpoint": "agent_activity",
        "link_label": "Open agent activity",
    },
    "providers": {
        "group": "Administration",
        "title": "Providers & capacity",
        "icon": "fa-server",
        "description": "Provider health, capacity, quotas, and placement policy will be managed here.",
        "current": "Current host capacity and orchestrator health remain visible on Home.",
        "link_endpoint": "overview",
        "link_label": "Open Home",
    },
    "security": {
        "group": "Administration",
        "title": "Security",
        "icon": "fa-shield-halved",
        "description": "Ownership, roles, credentials, and containment policy will be managed here.",
        "current": "The current access posture and model connection are documented in Settings.",
        "link_endpoint": "administration_settings",
        "link_label": "Open Settings",
    },
}


def _foundation_page(page_key):
    page = _FOUNDATION_PAGES[page_key]
    return render_template("foundation.html", active=page_key, page=page)


@app.route("/evaluations")
def evaluations():
    return _foundation_page("evaluations")


@app.route("/library/targets")
def target_library():
    return _foundation_page("targets")


@app.route("/library/agents")
def agent_library():
    return _foundation_page("agent_library")


@app.route("/activity/findings")
def findings_index():
    """Every finding, across engagements, with the operator verdict that decides it."""
    findings = _all_findings()
    counts = {
        "all": len(findings),
        "unverified": sum(1 for f in findings if f["verdict"] == "unverified"),
        "confirmed": sum(1 for f in findings if f["verdict"] == "confirmed"),
        "refuted": sum(1 for f in findings if f["verdict"] == "refuted"),
    }
    return render_template(
        "findings_index.html", active="findings", findings=findings, counts=counts
    )


@app.route("/activity/evidence")
def evidence_index():
    """Artifacts and observed signals across engagements, each linking back to its own."""
    names = _arena_names()
    findings = _all_findings(names=names)
    artifacts, signals = _all_evidence(names=names, findings=findings)
    return render_template(
        "evidence_index.html", active="evidence",
        artifacts=artifacts, signals=signals,
    )


@app.route("/administration/providers")
def providers_capacity():
    return _foundation_page("providers")


@app.route("/administration/security")
def security():
    return _foundation_page("security")


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
            "engagement_purpose": request.form.get("engagement_purpose") or None,
            "participant_mode": request.form.get("participant_mode") or None,
            "engagement_time_box_seconds": _engagement_time_box(request.form.get("engagement_time_box_seconds")),
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
    return redirect(url_for("engagements"))


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
            "engagement_purpose": request.form.get("engagement_purpose") or None,
            "participant_mode": request.form.get("participant_mode") or None,
            "engagement_time_box_seconds": _engagement_time_box(request.form.get("engagement_time_box_seconds")),
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
    return redirect(url_for("engagements"))


@app.route("/build-sut", methods=["POST"])
def build_sut():
    """Launch a Git checkout or immutable OCI software-under-test arena."""
    f = request.form
    engagement_purpose = f.get("engagement_purpose", "")
    participant_mode = f.get("participant_mode", "")
    engagement_time_box = _engagement_time_box(f.get("engagement_time_box_seconds"))
    wizard_args = {}
    if _engagement_purpose(engagement_purpose):
        wizard_args["purpose"] = engagement_purpose
    if _engagement_participant(participant_mode):
        wizard_args["participant_mode"] = participant_mode
    if engagement_time_box:
        wizard_args["engagement_time_box_seconds"] = engagement_time_box
    wizard_url = url_for(
        "wizard",
        **wizard_args,
    )
    target_type = f.get("target_type", "git")
    ports = [int(p) for p in re.findall(r"\d+", f.get("ports", ""))][:8]
    payload = {
        "instance_id": f.get("instance_id"),
        "engagement_purpose": engagement_purpose or None,
        "participant_mode": f.get("participant_mode") or None,
        "engagement_time_box_seconds": _engagement_time_box(f.get("engagement_time_box_seconds")),
        "ports": ports,
        "include_attacker": f.get("include_attacker") == "on",
        "authorization_basis": f.get("authorization_basis", "public_oss"),
        "authorization_confirmed": f.get("authorization_confirmed") == "on",
        "scope_note": (f.get("scope_note") or "").strip() or None,
    }
    if target_type == "oci":
        payload["image"] = (f.get("image") or "").strip()
        payload["platform"] = f.get("platform") or "linux/amd64"
        endpoint = "/arenas/oci"
        source = payload["image"]
    elif target_type == "bundle":
        artifact_digest = (f.get("artifact_digest") or "").strip()
        if not artifact_digest:
            upload = request.files.get("file")
            if upload is None or not upload.filename:
                flash("Source-bundle launch rejected: select an archive.", "warning")
                return redirect(wizard_url)
            try:
                intake_response = requests.post(
                    f"{API_URL}/targets/source-bundles",
                    files={
                        "file": (
                            upload.filename,
                            upload.stream,
                            upload.mimetype or "application/octet-stream",
                        )
                    },
                    headers=API_HEADERS,
                    timeout=60,
                )
            except requests.RequestException as exc:
                flash(f"Source-bundle upload failed: {exc}", "danger")
                return redirect(wizard_url)
            if intake_response.status_code != 200:
                flash(
                    f"Source-bundle upload rejected: {_api_error(intake_response)}",
                    "warning",
                )
                return redirect(wizard_url)
            artifact_digest = intake_response.json()["artifact"]["digest"]
        payload["artifact_digest"] = artifact_digest
        payload["setup_mode"] = f.get("setup_mode", "operator")
        payload["setup_egress"] = f.get("setup_egress") == "on"
        if f.get("time_box_seconds"):
            payload["time_box_seconds"] = int(
                re.sub(r"\D", "", f["time_box_seconds"]) or 0
            )
        if f.get("command_budget"):
            payload["command_budget"] = int(
                re.sub(r"\D", "", f["command_budget"]) or 0
            )
        endpoint = "/arenas/source-bundle"
        source = request.files.get("file").filename if request.files.get("file") else artifact_digest
    else:
        payload["repo"] = (f.get("repo") or "").strip()
        payload["ref"] = (f.get("ref") or "").strip() or None
        payload["setup_mode"] = f.get("setup_mode", "operator")
        payload["setup_egress"] = f.get("setup_egress") == "on"
        if f.get("time_box_seconds"):
            payload["time_box_seconds"] = int(
                re.sub(r"\D", "", f["time_box_seconds"]) or 0
            )
        if f.get("command_budget"):
            payload["command_budget"] = int(
                re.sub(r"\D", "", f["command_budget"]) or 0
            )
        endpoint = "/arenas/sut"
        source = payload["repo"]
    try:
        resp = requests.post(
            f"{API_URL}{endpoint}", json=payload, headers=API_HEADERS, timeout=15
        )
        if resp.status_code == 200:
            suffix = (
                "native image startup will be verified by preflight."
                if target_type == "oci"
                else "setup opens automatically once it's active."
            )
            flash(f"Building SUT arena '{payload['instance_id']}' from {source} — {suffix}", "info")
        else:
            flash(f"SUT launch rejected: {_api_error(resp)}", "warning")
    except requests.RequestException as e:
        flash(f"SUT launch failed: {e}", "danger")
    return redirect(url_for("engagements"))


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
    return redirect(url_for("engagements"))


@app.route("/reset/<instance_id>", methods=["POST"])
def reset_lab_form(instance_id):
    data, status = _api_post(
        f"/arenas/{instance_id}/reset",
        {"idempotency_key": f"webui-{uuid.uuid4()}"},
        timeout=15,
    )
    if status not in (200, 202):
        flash(data.get("error", "Reset rejected"), "danger")
    else:
        flash(
            f"Reset started; replacement arena {data.get('replacement_id')}",
            "info",
        )
    return redirect(url_for("arena_detail", instance_id=instance_id))


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
    return redirect(url_for("engagements"))


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
    return redirect(url_for("engagements"))


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
        "base_url": (body.get("base_url") or "").strip() or None,  # P3-4
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
        "base_url": (body.get("base_url") or "").strip() or None,  # P3-4
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


# Workspace live stream (ROADMAP C3). The browser holds one connection instead of
# three timers; the console still only presents — it derives frames from orchestrator
# reads. When the orchestrator grows its own change feed, this generator can consume
# it without changing the contract the workspace already speaks.
_STREAM_INTERVAL_SECONDS = float(os.getenv("WEBUI_STREAM_INTERVAL_SECONDS", "2"))
_STREAM_MAX_SECONDS = float(os.getenv("WEBUI_STREAM_MAX_SECONDS", "1800"))
_STREAM_BACKFILL = 40


def _sse(name, payload, event_id=None):
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {name}\ndata: {json.dumps(payload)}\n\n"


@app.route("/api/arenas/<instance_id>/stream")
def arena_stream(instance_id):
    """Server-sent workspace updates: arena state, outputs, and new audit events.

    Audit events carry a monotonic id, so a reconnecting browser resumes exactly
    where it stopped via the standard `Last-Event-ID` header — no duplicates, no gap.
    """
    try:
        cursor = int(request.headers.get("Last-Event-ID", ""))
    except ValueError:
        cursor = None

    def generate(cursor):
        deadline = time.monotonic() + _STREAM_MAX_SECONDS
        previous = None
        while time.monotonic() < deadline:
            status, ok = _api_get(f"/status/{instance_id}")
            if ok and status:
                state = {
                    "status": status.get("status", "unknown"),
                    "outputs": status.get("outputs") or {},
                }
                if state != previous:
                    previous = state
                    yield _sse("state", state)

            events = list(reversed(_events(instance_id, limit=_STREAM_BACKFILL)))
            if cursor is None:
                fresh = events                       # first connection: recent context
            else:
                fresh = [e for e in events if (e.get("id") or 0) > cursor]
            if fresh:
                cursor = max((e.get("id") or 0) for e in fresh)
                yield _sse("activity", {"events": fresh}, event_id=cursor)
            else:
                yield ": keepalive\n\n"            # keeps proxies from idling us out
            time.sleep(_STREAM_INTERVAL_SECONDS)

    return Response(
        stream_with_context(generate(cursor)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # never buffer a stream behind a reverse proxy
        },
    )


@app.route("/api/arenas/<instance_id>/eval-export", methods=["GET"])
def arena_eval_export_proxy(instance_id):
    """The run's eval-dataset row (ADR-0010) for download from the Trace tab."""
    data, ok = _api_get(f"/arenas/{instance_id}/eval-export")
    if not ok or data is None:
        return jsonify({"error": "eval export unavailable"}), 502
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{instance_id}-eval.json"'
        },
    )


@app.route("/api/arenas/<instance_id>/workspaces", methods=["GET"])
def arena_workspaces_proxy(instance_id):
    """Source workspaces visible to the operator for the change viewer."""
    data, ok = _api_get(f"/arenas/{instance_id}/workspaces")
    return jsonify(data or {"workspaces": []}), (200 if ok else 502)


# HTTP research primitive (R1 slice 6): the console only presents and forwards —
# scope resolution, binding checks, bounding and hashing stay orchestrator-side.

@app.route("/api/arenas/<instance_id>/http/transactions", methods=["GET"])
def http_transactions_proxy(instance_id):
    """Stored HTTP transactions for this arena, newest first."""
    params = {
        key: request.args[key]
        for key in ("limit", "offset")
        if key in request.args
    }
    query = f"?{urlencode(params)}" if params else ""
    data, ok = _api_get(f"/arenas/{instance_id}/http/transactions{query}")
    return jsonify(data or {"total": 0, "transactions": []}), (200 if ok else 502)


@app.route("/api/arenas/<instance_id>/http/transactions/<digest>", methods=["GET"])
def http_transaction_proxy(instance_id, digest):
    """One stored HTTP transaction envelope by digest."""
    data, ok = _api_get(
        f"/arenas/{instance_id}/http/transactions/{quote(digest, safe='')}"
    )
    return jsonify(data or {"error": "not found"}), (200 if ok else 404)


@app.route("/api/arenas/<instance_id>/http/request", methods=["POST"])
def http_request_proxy(instance_id):
    """Drive one arena-target HTTP transaction from the workspace."""
    body = request.get_json(silent=True) or {}
    data, code = _api_post(f"/arenas/{instance_id}/http/request", body)
    return jsonify(data), code


@app.route(
    "/api/arenas/<instance_id>/http/transactions/<digest>/replay",
    methods=["POST"],
)
def http_replay_proxy(instance_id, digest):
    """Re-send a stored transaction with edits; the original stays immutable."""
    body = request.get_json(silent=True) or {}
    data, code = _api_post(
        f"/arenas/{instance_id}/http/transactions/"
        f"{quote(digest, safe='')}/replay",
        body,
    )
    return jsonify(data), code


@app.route("/api/arenas/<instance_id>/poc-jobs", methods=["GET", "POST"])
def poc_jobs_proxy(instance_id):
    """Thin console proxy; confinement and authorization remain in the API."""
    if request.method == "GET":
        data, ok = _api_get(f"/arenas/{instance_id}/poc-jobs")
        return jsonify(data or {"jobs": []}), (200 if ok else 502)
    body = request.get_json(silent=True) or {}
    data, code = _api_post(f"/arenas/{instance_id}/poc-jobs", body)
    return jsonify(data), code


@app.route("/api/arenas/<instance_id>/poc-jobs/<job_id>", methods=["GET"])
def poc_job_proxy(instance_id, job_id):
    data, ok = _api_get(f"/arenas/{instance_id}/poc-jobs/{quote(job_id, safe='')}")
    return jsonify(data or {"error": "not found"}), (200 if ok else 404)


@app.route("/api/arenas/<instance_id>/poc-jobs/<job_id>/cancel", methods=["POST"])
def poc_job_cancel_proxy(instance_id, job_id):
    data, code = _api_post(
        f"/arenas/{instance_id}/poc-jobs/{quote(job_id, safe='')}/cancel", {}
    )
    return jsonify(data), code


@app.route("/api/arenas/<instance_id>/preflight", methods=["GET"])
def arena_preflight_proxy(instance_id):
    """Immutable target identity and infrastructure readiness for the arena."""
    data, ok = _api_get(f"/arenas/{instance_id}/preflight")
    return jsonify(data or {"status": "unavailable"}), (200 if ok else 404)


@app.route(
    "/api/arenas/<instance_id>/workspaces/<workspace_node>/diff",
    methods=["GET"],
)
def arena_workspace_diff_proxy(instance_id, workspace_node):
    """Proxy a bounded change page; only the orchestrator chooses the source path."""
    params = {
        key: request.args[key]
        for key in ("base", "path", "context_lines", "start_line", "max_lines")
        if key in request.args
    }
    try:
        resp = requests.get(
            f"{API_URL}/arenas/{instance_id}/workspaces/"
            f"{requests.utils.quote(workspace_node, safe='')}/diff",
            params=params,
            headers=API_HEADERS,
            timeout=10,
        )
    except requests.RequestException:
        return jsonify({"error": "orchestrator unreachable"}), 502
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200:
        return jsonify({"error": _api_error(resp)}), resp.status_code
    return jsonify(data), 200


@app.route(
    "/api/arenas/<instance_id>/workspaces/<workspace_node>/patch-artifacts",
    methods=["POST"],
)
def arena_workspace_patch_proxy(instance_id, workspace_node):
    """Create a content-addressed patch through the shared workspace primitive."""
    body = request.get_json(silent=True) or {}
    payload = {
        "base": body.get("base") or "HEAD",
        "path": body.get("path") or None,
        "context_lines": body.get("context_lines", 3),
        "include_untracked_paths": body.get("include_untracked_paths") or [],
    }
    data, code = _api_post(
        f"/arenas/{instance_id}/workspaces/"
        f"{requests.utils.quote(workspace_node, safe='')}/patch-artifacts",
        payload,
    )
    return jsonify(data), code


@app.route("/api/arenas/<instance_id>/evidence-artifacts/<digest>", methods=["GET"])
def evidence_artifact_proxy(instance_id, digest):
    """Stream a verified arena-scoped artifact without exposing the API key."""
    try:
        resp = requests.get(
            f"{API_URL}/arenas/{instance_id}/evidence-artifacts/"
            f"{requests.utils.quote(digest, safe=':')}",
            headers=API_HEADERS,
            timeout=10,
        )
    except requests.RequestException:
        return jsonify({"error": "orchestrator unreachable"}), 502
    if resp.status_code != 200:
        return jsonify({"error": _api_error(resp)}), resp.status_code
    return Response(
        resp.content,
        status=200,
        content_type=resp.headers.get("Content-Type", "text/x-diff"),
        headers={
            "Content-Disposition": resp.headers.get(
                "Content-Disposition", "attachment; filename=evidence.patch"
            ),
            "ETag": resp.headers.get("ETag", ""),
        },
    )


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


@app.route("/api/arenas/<instance_id>/findings/manual", methods=["POST"])
def manual_finding_proxy(instance_id):
    """Operator-entered finding (proxies POST /arenas/<id>/findings/manual).
    CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {
        "title": (body.get("title") or "").strip(),
        "cwe": (body.get("cwe") or "").strip() or None,
        "node": (body.get("node") or "").strip() or None,
        "evidence": (body.get("evidence") or "").strip() or None,
        "poc": (body.get("poc") or "").strip() or None,
        "evidence_artifact_digests": body.get("evidence_artifact_digests") or [],
        "transaction_digests": body.get("transaction_digests") or [],
    }
    data, code = _api_post(f"/arenas/{instance_id}/findings/manual", payload)
    return jsonify(data), code


@app.route("/api/arenas/<instance_id>/findings/<finding_id>/verify", methods=["POST"])
def verify_finding_proxy(instance_id, finding_id):
    """Operator verdict on a finding (proxies POST …/verify). CSRF-protected."""
    body = request.get_json(silent=True) or {}
    payload = {
        "verdict": (body.get("verdict") or "").strip(),
        "note": (body.get("note") or "").strip() or None,
    }
    data, code = _api_post(f"/arenas/{instance_id}/findings/{finding_id}/verify", payload)
    return jsonify(data), code


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
