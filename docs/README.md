# 🛡️ CyberGuard — Enterprise Cyber Arena

**Dynamic, multi-machine vulnerable topologies + bring-your-own AI agents
(attacker / MITM / defender) wired in via MCP — runnable locally, on OpenStack,
or on AWS.**

CyberGuard provisions arbitrary N-node arenas on demand and exposes them, through
**MCP gateways**, to bring-your-own agents (agentic Claude Code or a company's
own internal model) placed as **attacker**, **MITM**, or **defender**. Humans
(operators) author and run engagements; the AI is the system under test. It runs
fully on a laptop (Docker), on OpenStack, or on AWS, with async task processing,
per-arena isolation, and full audit/trace.

![Status](https://img.shields.io/badge/Status-Active_Development-yellow)
![Stack](https://img.shields.io/badge/Stack-Python%20%7C%20OpenTofu%20%7C%20Redis%20%7C%20MCP-blue)
![License](https://img.shields.io/badge/License-MIT-green)

> Direction (2026-06): pivoting from the original lab launcher to the arena
> model above — see [`ROADMAP.md`](../ROADMAP.md). Technical inspiration for the
> topology engine: **GOAD**. We also hold ourselves to the product-quality
> (UI/UX & operator-utility) bar of well-executed security products — but those
> are a quality bar only, not a scope or technical model.



## 🐳 Docker Quick Start (Recommended)

The easiest way to run the platform. No manual Python or Redis installation required.

### 1. Configure Environment

Create the configuration file (Simulation Mode is enabled by default).

```bash
cp .env.example .env
```

### 2. Launch the Stack

Build and start the services in the background.

```bash
docker-compose up -d --build
```

### 3. Access

Open your browser at **http://localhost:5000**.

### 4. Stop

To stop and remove containers:

```bash
docker-compose down
```



## 🚀 Quick Start (Simulation Mode)

This manual way of running the project simulates infrastructure provisioning delays and generates realistic mock data.

### 1. Prerequisites
* **Python 3.10+**
* **Redis Server** (required for the message broker).
* **OpenTofu** (optional for Simulation Mode, required for Prod).

### 2. Running the Platform
You need to run the services in separate terminal windows.

**Terminal 1: Redis Broker**
Start the message queue service.
```bash
sudo systemctl start redis-server
```

**Terminal 2: Background Worker**
Processes the deployment tasks. We enable Mock Mode here.

```bash
cd services/scenario-orchestrator
pip install -r requirements.txt
export MOCK_MODE=true
celery -A tasks worker --loglevel=info --concurrency=3
```

**Terminal 3: Orchestrator API**
The REST backend that handles requests.

```bash
cd services/scenario-orchestrator
# If using a virtualenv, ensure it is activated
uvicorn api:app --host 0.0.0.0 --port 8000
```

**Terminal 4: Web Dashboard**
The frontend user interface.

```bash
cd webui
pip install -r requirements.txt
python3 app.py
```

### 3. Access

Open your browser at **http://localhost:5000**.

1. **Launch:** Select a scenario and click "Launch".
2. **Wait:** You will see the status change from "Pending" to "Deploying" (Simulating ~15s delay).
3. **Control:** Once "Active" (Green), click "Enter Control" to view the generated credentials and topology.



## ⚙️ Switching to Production (Real OpenStack)

To deploy actual infrastructure, you must disable Mock Mode and provide valid credentials.

1. Create a `.env` file in `services/scenario-orchestrator/` based on `.env.example`.
2. Update the configuration:

```bash
# .env config
MOCK_MODE=false             # <--- Disables simulation to use Real OpenTofu
OS_AUTH_URL=https://your-openstack:5000/v3
OS_USERNAME=admin
OS_PASSWORD=secret
OS_PROJECT_ID=your_project_id
OS_USER_DOMAIN_NAME=Default

```


## 🏗️ Architecture
```
┌─────────────┐      HTTP       ┌──────────────┐
│  Web UI     │ ──────────────> │ FastAPI      │
│ (Flask)     │ <────────────── │ Backend      │
└─────────────┘                 └──────┬───────┘
                                       │
                                       │ Dispatch Task
                                       ▼
                                ┌──────────────┐
                                │ Redis Queue  │
                                └──────┬───────┘
                                       │
                                       │ Consume
                                       ▼
                                ┌──────────────┐      ┌──────────────┐
                                │ Celery       │─────>│ OpenTofu     │
                                │ Worker       │      │ (Terraform)  │
                                └──────────────┘      └──────┬───────┘
                                                             │
                                                             ▼
                                                      ┌──────────────┐
                                                      │ OpenStack    │
                                                      │ Cloud        │
                                                      └──────────────┘
```

### Key Components

- **WebUI (Flask):** User-facing dashboard with real-time polling
- **API (FastAPI):** REST endpoints for deployment management
- **Worker (Celery):** Background task processor for infrastructure provisioning
- **Database (SQLite):** Persistent state storage
- **Orchestrator:** Terraform/OpenTofu wrapper with workspace isolation
- **Redis:** Message broker for async task queue



## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **Redis Server** (for task queue)
- **OpenTofu or Terraform** (optional for Mock Mode, required for production)


### Installation
```bash
# 1. Clone the repository
git clone https://github.com/gianlucabassani/CyberGuard.git
cd CyberGuard

# 2. Create required directories
mkdir -p data runs cache/terraform-plugins keys

# 3. Install Python dependencies
cd cyber-range/services/scenario-orchestrator
pip install -r requirements.txt

cd ../../webui
pip install -r requirements.txt

# 4. Start Redis (Ubuntu/Debian)
sudo systemctl start redis-server

# Or via Docker
docker run -d -p 6379:6379 redis:alpine
```

### Running in Mock Mode (Testing)

Test the full platform **without** requiring OpenStack:
```bash
# Terminal 1: Start Celery Worker
cd cyber-range/services/scenario-orchestrator
export MOCK_MODE=true
export DATABASE_PATH="$(pwd)/../../../data/deployments.db"
celery -A tasks worker --loglevel=info --concurrency=3

# Terminal 2: Start API Backend
cd cyber-range/services/scenario-orchestrator
export MOCK_MODE=true
uvicorn api:app --host 0.0.0.0 --port 8000

# Terminal 3: Start Web Dashboard
cd cyber-range/webui
export ORCHESTRATOR_URL="http://localhost:8000"
python3 app.py
```

### Access the Dashboard

Open your browser at **http://localhost:5000**

1. **Create an Arena:**
   - Enter an instance name (e.g., `arena-1`)
   - Select a scenario from the registry
   - Click **LAUNCH**

2. **Monitor Deployment:**
   - Status changes: `Pending` → `Deploying` → `Active`
   - Real-time status badge in navbar

3. **Access Lab:**
   - Click **ENTER CONTROL** when status is `Active`
   - View topology, IPs, and SSH commands
   - Copy credentials for Wazuh dashboard

4. **Destroy Lab:**
   - Click **DESTROY** button
   - Confirms deletion and cleans up workspace



## 🔧 Prod Deployment

### 1. Install OpenTofu
```bash
# Download OpenTofu
wget https://github.com/opentofu/opentofu/releases/download/v1.6.0/tofu_1.6.0_linux_amd64.zip
unzip tofu_1.6.0_linux_amd64.zip
sudo mv tofu /usr/local/bin/
tofu version
```

### 2. Configure OpenStack Credentials

Create a `.env` file in `cyber-range/services/scenario-orchestrator/`:
```bash
# OpenStack Configuration
MOCK_MODE=false
OS_AUTH_URL=https://your-openstack:5000/v3
OS_USERNAME=your_username
OS_PASSWORD=your_password
OS_PROJECT_ID=your_project_id
OS_REGION_NAME=RegionOne
OS_USER_DOMAIN_NAME=Default
OS_PROJECT_DOMAIN_NAME=Default

# Paths
DATABASE_PATH=/absolute/path/to/CyberGuard/data/deployments.db
RUNS_DIR=/absolute/path/to/CyberGuard/runs
TF_PLUGIN_CACHE_DIR=/absolute/path/to/CyberGuard/cache/terraform-plugins

# Redis
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### 3. Update Terraform Variables

Edit `cyber-range/infra/terraform/terraform.tfvars`:
```hcl
# OpenStack Credentials
os_user_name        = "your_username"
os_password         = "your_password"
os_tenant_id        = "your_project_id"
os_auth_url         = "https://your-openstack:5000/v3"

# Images (must exist in Glance)
image_name          = "kali-linux-2025-cloud"
victim_image_name   = "victim-web"
log_image_name      = "ubuntu_cloud"

# Network
external_network_name = "public"
```

### 4. Start Production Services
```bash
# Remove MOCK_MODE environment variable
unset MOCK_MODE

# Start Worker
cd cyber-range/services/scenario-orchestrator
celery -A tasks worker --loglevel=info --concurrency=3

# Start API
uvicorn api:app --host 0.0.0.0 --port 8000

# Start WebUI
cd ../../webui
python3 app.py
```



## 📁 Project Structure
```
CyberGuard/
├── cache/                          # Terraform plugin cache
│   └── terraform-plugins/
├── data/                           # SQLite database
│   └── deployments.db
├── runs/                           # Active workspace directories
│   ├── lab-1/                      # Isolated Terraform state
│   ├── lab-2/
│   └── lab-3/
├── keys/                           # SSH keys (generated)
├── cyber-range/
│   ├── infra/terraform/            # Base Terraform templates
│   ├── services/
│   │   ├── scenario-orchestrator/  # Backend API + Worker
│   │   │   ├── api.py              # FastAPI endpoints
│   │   │   ├── tasks.py            # Celery tasks
│   │   │   ├── orchestrator.py     # Terraform wrapper
│   │   │   ├── database.py         # SQLite ORM
│   │   │   └── config.py           # Configuration loader
│   │   └── vulnhub-importer/       # Image import tools
│   └── webui/                      # Flask dashboard
│       ├── app.py
│       ├── templates/              # Jinja2 templates
│       └── static/                 # CSS, JS, assets
└── docs/                           # Documentation
```


## 🧩 Scenarios

A scenario is the authored, provider-agnostic spec for an arena: arbitrary
`nodes[]` on named network `segments[]`, plus `objectives` and optional
`agents[]` stance bindings (GOAD-style, not a fixed victim/attacker/monitor
trio). The shipped specs are now **schema v3** — see
[SCENARIOS.md](SCENARIOS.md) for the authoring guide and
[scenario.schema.json](scenario.schema.json) for the machine-readable contract.
The generic per-provider compiler (`nodes[]` → container project / Terraform
module) is ROADMAP Phase 1 **P1-2**.

### 1. basic_pentest

**Nodes:** a vulnerable web victim, a Kali foothold, and a Wazuh + Suricata
sensor node.

**Objectives:** web-app exploitation; the foothold node is the attacker
stance's entry point; the sensor node feeds defender-stance scoring.

### 2. random_vulnhub

**Nodes:** a catalog-selected vulnerable image + a Kali foothold. Wiring the
VulnHub importer to make this real is a Phase-1 item (audit #10).



## 🔍 Troubleshooting

### Worker Not Processing Tasks
```bash
# Check Redis connection
redis-cli ping
# Expected: PONG

# Check Celery worker logs
cd cyber-range/services/scenario-orchestrator
celery -A tasks worker --loglevel=debug
```

### Database Locked
```bash
# Check for stale connections
lsof cyber-range/data/deployments.db

# Reset database (WARNING: destroys all records)
rm cyber-range/data/deployments.db
```

### Terraform State Conflicts
```bash
# Each lab should have its own directory
ls runs/
# Expected: lab-1/ lab-2/ lab-3/

# Check for state locks
find runs/ -name ".terraform.lock.hcl"
```

### Frontend Not Updating
```bash
# Check browser console (F12)
# Look for polling errors

# Verify API endpoint
curl http://localhost:8000/deployments
```



## 🛠️ Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_MODE` | `false` | Enable simulation mode |
| `DATABASE_PATH` | `data/deployments.db` | SQLite database location |
| `RUNS_DIR` | `runs/` | Terraform workspace directory |
| `TF_PLUGIN_CACHE_DIR` | `cache/terraform-plugins/` | Provider plugin cache |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis connection string |
| `WORKER_CONCURRENCY` | `3` | Max concurrent deployments |
| `API_PORT` | `8000` | Backend API port |

### Terraform Variables

See `cyber-range/infra/terraform/variables.tf` for complete list.

Key variables:
- `flavor_name`: VM size (default: `t3.small`)
- `soc_flavor_name`: SOC VM size (default: `t3.medium`)
- `private_cidr`: Internal network CIDR
- `keypair_name`: SSH key name in OpenStack



## 🚧 Roadmap

The full phased plan — with a code-audit punch list, acceptance criteria, and
sequencing — lives in **[ROADMAP.md](../ROADMAP.md)**. Highlights:

Shipped substrate:
- [x] Docker Compose stack; test suite + CI (SQLite + Postgres)
- [x] API-key auth + roles; input validation; CSRF + API rate limiting
- [x] Provider abstraction (`mock` / `docker-local` / `openstack`); per-request provider
- [x] PostgreSQL + SQLAlchemy + Alembic; lab state machine + `events` audit; TTL reaper
- [x] Secrets hygiene (log redaction + Fernet-encrypted outputs at rest)

The pivot (re-sequenced around the three pillars):
- [ ] **Phase 0** — repositioning & role rename (admin/operator/agent)
- [ ] **Phase 1** — dynamic N-node topology engine (GOAD-style)
- [ ] **Phase 2** — MCP agent gateway: attacker / MITM / defender stances *(priority)*
- [ ] **Phase 3** — zero-to-prompt scenario generation (bring-your-own key)
- [ ] **Phase 4** — scoring, eval & trace datasets
- [ ] **Phase 5** — hardening + AWS hosting · **Phase 6** — observability · **Phase 7** — console redesign

> **Security note:** API-key auth and rate limiting are in place, but the build
> still ships demo defaults and lacks per-owner authorization — see
> [docs/SECURITY.md](SECURITY.md). Do not expose it to an untrusted network
> without overriding the demo credentials and completing the hardening checklist.


