import os
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
# Never hardcode the secret: it signs session cookies/flash messages.
# Set SECRET_KEY in the environment for any non-local deployment.
app.secret_key = os.getenv("SECRET_KEY", "dev-insecure-change-me")
API_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

@app.route('/')
def lobby():
    """Lobby: List all active scenarios"""
    try:
        # Calls the Correct Endpoint /deployments
        resp = requests.get(f"{API_URL}/deployments", timeout=5)
        deployments = resp.json() if resp.status_code == 200 else {}
    except:
        deployments = {}
        flash("Backend Offline", "danger")
        
    return render_template('lobby.html', deployments=deployments)

@app.route('/dashboard/<instance_id>')
def dashboard(instance_id):
    """Specific Mission Control for one lab"""
    try:
        resp = requests.get(f"{API_URL}/status/{instance_id}", timeout=5)
        
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
    except Exception as e:
        print(f"Dashboard Error: {e}")
        return redirect(url_for('lobby'))

@app.route('/create', methods=['POST'])
def create_lab():
    scenario = request.form.get('scenario')
    instance_id = request.form.get('instance_id')
    
    # Calls Correct Endpoint /deploy with Correct Keys
    try:
        requests.post(f"{API_URL}/deploy", json={
            "scenario": scenario, 
            "instance_id": instance_id
        }, timeout=5)
    except Exception as e:
        flash(f"Deploy failed: {e}", "danger")

    return redirect(url_for('lobby'))

@app.route('/api/destroy/<instance_id>', methods=['POST'])
def destroy_lab(instance_id):
    requests.delete(f"{API_URL}/destroy/{instance_id}")
    return jsonify({"status": "ok"})

@app.route('/api/poll/<instance_id>')
def poll_status(instance_id):
    try:
        resp = requests.get(f"{API_URL}/status/{instance_id}", timeout=5)
        return jsonify(resp.json())
    except:
        return jsonify({"status": "offline"})

if __name__ == '__main__':
    # debug=True exposes the Werkzeug interactive debugger (RCE) — gate it behind an env flag.
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host='0.0.0.0', port=5000, debug=debug)