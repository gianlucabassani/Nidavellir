import hmac
import os

import requests
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf import CSRFProtect

app = Flask(__name__)
# Never hardcode the secret: it signs session cookies/flash messages.
# Set SECRET_KEY in the environment for any non-local deployment.
app.secret_key = os.getenv("SECRET_KEY", "dev-insecure-change-me")
# CSRF on every state-changing route (SECURITY #3). Forms embed the token via
# {{ csrf_token() }}; JS fetches send it as the X-CSRFToken header.
csrf = CSRFProtect(app)
API_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

# Surfaced in the UI so users know lab links/credentials are simulated.
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

# Key the WebUI uses to authenticate against the orchestrator API (ADR-0002).
# The default matches the compose-stack bootstrap key for the mock demo only.
API_KEY = os.getenv("ORCHESTRATOR_API_KEY", "dev-insecure-key")
API_HEADERS = {"X-API-Key": API_KEY}

# Operator login for the dashboard itself. Defaults are for the local mock
# demo; any reachable deployment must override both (see docs/SECURITY.md).
WEBUI_USERNAME = os.getenv("WEBUI_USERNAME", "admin")
WEBUI_PASSWORD = os.getenv("WEBUI_PASSWORD", "cyberguard")

if WEBUI_PASSWORD == "cyberguard":  # noqa: S105 - detecting the default, not setting it
    app.logger.warning(
        "WEBUI_PASSWORD is the well-known default — fine for the local mock "
        "demo, NEVER for a reachable deployment."
    )


@app.before_request
def require_login():
    """Every route except the login page and static assets needs a session.

    /api/health is also open: it only mirrors the orchestrator's own
    unauthenticated liveness probe, and the nav badge needs it pre-login.
    """
    if request.endpoint in ("login", "static", "orchestrator_health"):
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        user_ok = hmac.compare_digest(username, WEBUI_USERNAME)
        pass_ok = hmac.compare_digest(password, WEBUI_PASSWORD)
        if user_ok and pass_ok:
            session['logged_in'] = True
            session['username'] = username
            target = request.args.get('next') or url_for('lobby')
            # Only follow relative targets — never an absolute/external URL.
            if not target.startswith('/'):
                target = url_for('lobby')
            return redirect(target)
        flash("Invalid credentials", "danger")
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def lobby():
    """Lobby: List all active scenarios"""
    deployments, scenarios, catalog_images = {}, [], []
    try:
        # Calls the Correct Endpoint /deployments
        resp = requests.get(f"{API_URL}/deployments", headers=API_HEADERS, timeout=5)
        deployments = resp.json() if resp.status_code == 200 else {}
        if resp.status_code == 401:
            flash("Backend rejected the WebUI API key (check ORCHESTRATOR_API_KEY)", "danger")

        # Scenario registry drives the launch dropdown (no hardcoded list)
        reg = requests.get(f"{API_URL}/scenarios", headers=API_HEADERS, timeout=5)
        if reg.status_code == 200:
            scenarios = reg.json().get("scenarios", [])

        # Curated image catalog drives the manual "build a custom arena" form.
        cat = requests.get(f"{API_URL}/catalog", headers=API_HEADERS, timeout=5)
        if cat.status_code == 200:
            catalog_images = cat.json().get("images", [])
    except requests.RequestException:
        flash("Backend Offline", "danger")

    attackers = [i for i in catalog_images if i["kind"] == "attacker" and i["available"]]
    victims = [i for i in catalog_images if i["kind"] == "victim" and i["available"]]

    # Destroyed labs are history, not missions: keep the main view clean and
    # park them in a collapsed archive section.
    current = {k: v for k, v in deployments.items() if v.get('status') != 'destroyed'}
    archived = {k: v for k, v in deployments.items() if v.get('status') == 'destroyed'}

    return render_template(
        'lobby.html',
        deployments=current,
        archived=archived,
        scenarios=scenarios,
        attackers=attackers,
        victims=victims,
        mock_mode=MOCK_MODE,
    )


@app.route('/dashboard/<instance_id>')
def dashboard(instance_id):
    """Specific Mission Control for one lab"""
    try:
        resp = requests.get(
            f"{API_URL}/status/{instance_id}", headers=API_HEADERS, timeout=5
        )

        if resp.status_code != 200:
            flash(f"Instance {instance_id} not found.", "warning")
            return redirect(url_for('lobby'))

        data = resp.json()

        # Passes Dict to template (Fixed "str object" error)
        return render_template('dashboard.html',
                             instance_id=instance_id,
                             instance_name=data.get('user_id', 'Unknown'),
                             status=data.get('outputs', {}),
                             state=data.get('status', 'unknown'),
                             mock_mode=MOCK_MODE)
    except requests.RequestException as e:
        app.logger.error(f"Dashboard error for {instance_id}: {e}")
        return redirect(url_for('lobby'))


@app.route('/create', methods=['POST'])
def create_lab():
    scenario = request.form.get('scenario')
    instance_id = request.form.get('instance_id')

    # Calls Correct Endpoint /deploy with Correct Keys
    try:
        resp = requests.post(f"{API_URL}/deploy", json={
            "scenario": scenario,
            "instance_id": instance_id
        }, headers=API_HEADERS, timeout=5)
        if resp.status_code == 422:
            # Surface the API's validation message (e.g. bad name, unknown scenario)
            try:
                detail = resp.json()["detail"][0]["msg"]
            except (ValueError, LookupError):
                detail = "invalid input"
            flash(f"Launch rejected: {detail}", "warning")
        elif resp.status_code != 200:
            flash(f"Deploy failed (HTTP {resp.status_code})", "danger")
    except requests.RequestException as e:
        flash(f"Deploy failed: {e}", "danger")

    return redirect(url_for('lobby'))


@app.route('/build-custom', methods=['POST'])
def build_custom():
    """Manual scenario creator: build a custom arena from catalog picks."""
    instance_id = request.form.get('instance_id')
    attacker = request.form.get('attacker')
    victims = request.form.getlist('victims')

    try:
        resp = requests.post(f"{API_URL}/arenas/custom", json={
            "instance_id": instance_id,
            "attacker": attacker,
            "victims": victims,
        }, headers=API_HEADERS, timeout=10)
        if resp.status_code == 200:
            flash(
                f"Building arena '{instance_id}': {attacker} vs "
                f"{', '.join(victims)} (images are pulled on first use)",
                "info",
            )
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

    return redirect(url_for('lobby'))


def _request_destroy(instance_id):
    """Ask the orchestrator to destroy a lab. Returns (ok, message)."""
    try:
        resp = requests.delete(
            f"{API_URL}/destroy/{instance_id}", headers=API_HEADERS, timeout=10
        )
    except requests.RequestException:
        return False, "Backend offline"
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "")
        except ValueError:
            detail = ""
        return False, detail or f"Destroy rejected (HTTP {resp.status_code})"
    return True, "Destroy started"


@app.route('/api/destroy/<instance_id>', methods=['POST'])
def destroy_lab(instance_id):
    """JSON destroy (dashboard JS). Relays the orchestrator's verdict."""
    ok, message = _request_destroy(instance_id)
    if not ok:
        return jsonify({"error": message}), 502
    return jsonify({"status": "ok"})


@app.route('/destroy/<instance_id>', methods=['POST'])
def destroy_lab_form(instance_id):
    """Form destroy (lobby buttons): flash the outcome and return to lobby."""
    ok, message = _request_destroy(instance_id)
    flash(message, "info" if ok else "danger")
    return redirect(url_for('lobby'))


@app.route('/archive/delete/<instance_id>', methods=['POST'])
def archive_delete(instance_id):
    """Remove one destroyed/failed lab record from the archive."""
    try:
        resp = requests.delete(
            f"{API_URL}/deployments/{instance_id}", headers=API_HEADERS, timeout=10
        )
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", "")
            except ValueError:
                detail = ""
            flash(detail or f"Delete failed (HTTP {resp.status_code})", "danger")
    except requests.RequestException:
        flash("Backend offline", "danger")
    return redirect(url_for('lobby'))


@app.route('/archive/clear', methods=['POST'])
def archive_clear():
    """Remove every destroyed/failed lab record from the archive."""
    try:
        resp = requests.delete(
            f"{API_URL}/deployments", headers=API_HEADERS, timeout=10
        )
        if resp.status_code == 200:
            deleted = resp.json().get("deleted", 0)
            flash(f"Archive cleared ({deleted} record(s) removed)", "info")
        else:
            flash(f"Clear failed (HTTP {resp.status_code})", "danger")
    except requests.RequestException:
        flash("Backend offline", "danger")
    return redirect(url_for('lobby'))


@app.route('/api/health')
def orchestrator_health():
    """Backend reachability for the nav-bar status badge (no auth state)."""
    try:
        resp = requests.get(f"{API_URL}/health", timeout=3)
        ok = resp.status_code == 200
    except requests.RequestException:
        ok = False
    return jsonify({"status": "ok" if ok else "offline"})


@app.route('/api/poll/<instance_id>')
def poll_status(instance_id):
    try:
        resp = requests.get(
            f"{API_URL}/status/{instance_id}", headers=API_HEADERS, timeout=5
        )
        return jsonify(resp.json())
    except requests.RequestException:
        return jsonify({"status": "offline"})


if __name__ == '__main__':
    # debug=True exposes the Werkzeug interactive debugger (RCE) — gate it behind an env flag.
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    # Containerized service: bind-all is intentional; compose maps the port.
    app.run(host='0.0.0.0', port=5000, debug=debug)  # nosec B104
