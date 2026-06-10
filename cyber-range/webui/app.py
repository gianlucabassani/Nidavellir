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

app = Flask(__name__)
# Never hardcode the secret: it signs session cookies/flash messages.
# Set SECRET_KEY in the environment for any non-local deployment.
app.secret_key = os.getenv("SECRET_KEY", "dev-insecure-change-me")
API_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

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
    """Every route except the login page and static assets needs a session."""
    if request.endpoint in ("login", "static"):
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
    deployments, scenarios = {}, []
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
    except requests.RequestException:
        flash("Backend Offline", "danger")

    return render_template('lobby.html', deployments=deployments, scenarios=scenarios)


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
                             state=data.get('status', 'unknown'))
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


@app.route('/api/destroy/<instance_id>', methods=['POST'])
def destroy_lab(instance_id):
    requests.delete(
        f"{API_URL}/destroy/{instance_id}", headers=API_HEADERS, timeout=10
    )
    return jsonify({"status": "ok"})


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
