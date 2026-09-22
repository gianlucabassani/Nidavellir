import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# DETECT ENVIRONMENT (Docker vs Local)
IN_DOCKER = os.path.exists('/.dockerenv')

if IN_DOCKER:
    # Docker paths (absolute). The Dockerfile copies the service code to /app
    # (so scenario templates land at /app/templates) and docker-compose mounts
    # the Terraform templates read-only at /app/terraform.
    BASE_DIR = Path("/app")
    CYBER_RANGE_DIR = BASE_DIR
    TEMPLATES_DIR = BASE_DIR / "templates"
    BASE_TERRAFORM_TEMPLATE = BASE_DIR / "terraform"
    # Generic nodes[] AWS module (ROADMAP P1-2/P5-2); mounted by compose.
    AWS_TERRAFORM_TEMPLATE = BASE_DIR / "terraform-aws"
    # Generic nodes[] local-VM module (libvirt/QEMU); mounted by compose.
    LIBVIRT_TERRAFORM_TEMPLATE = BASE_DIR / "terraform-libvirt"
else:
    # Local development paths (relative)
    # DIRECTORIES - Corrected Path Resolution
    BASE_DIR = Path(__file__).parent.parent.parent.parent  # Goes up to ~/Projects/Nidavellir/
    CYBER_RANGE_DIR = BASE_DIR / "cyber-range"

    # Code directories (inside cyber-range/)
    TEMPLATES_DIR = Path(__file__).parent / "templates"  # scenario-orchestrator/templates/
    BASE_TERRAFORM_TEMPLATE = CYBER_RANGE_DIR / "infra" / "terraform"
    # Generic nodes[] AWS module (ROADMAP P1-2/P5-2).
    AWS_TERRAFORM_TEMPLATE = CYBER_RANGE_DIR / "infra" / "terraform-aws"
    # Generic nodes[] local-VM module (libvirt/QEMU).
    LIBVIRT_TERRAFORM_TEMPLATE = CYBER_RANGE_DIR / "infra" / "terraform-libvirt"

# libvirt/QEMU local-VM provider (ROADMAP local-VM enabler). The hypervisor URI
# and the default cloud image (qcow2 + cloud-init) for nodes with no image map.
LIBVIRT_URI = os.getenv("LIBVIRT_URI", "qemu:///system")
LIBVIRT_BASE_IMAGE = os.getenv(
    "LIBVIRT_BASE_IMAGE",
    "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
)
LIBVIRT_POOL = os.getenv("LIBVIRT_POOL", "default")

# MITM stance (P2-5): the in-path capture sidecar image (host-net tcpdump on the
# arena bridge — needs tcpdump + coreutils `timeout`) and a hard cap on capture
# duration so a tap can never run unbounded.
MITM_CAPTURE_IMAGE = os.getenv("MITM_CAPTURE_IMAGE", "nicolaka/netshoot:latest")
MITM_CAPTURE_MAX_SECONDS = int(os.getenv("MITM_CAPTURE_MAX_SECONDS", "20"))

# Runtime directories (at project root for easy access)
RUNS_DIR = Path(os.getenv("RUNS_DIR", str(BASE_DIR / "runs")))
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
KEYS_DIR = Path(os.getenv("KEYS_DIR", str(BASE_DIR / "keys")))
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(BASE_DIR / "cache")))

# Imported scenario packs (ROADMAP P1-7, Classic-range authoring track). The
# built-in templates live in TEMPLATES_DIR (baked into the image, read-only);
# operator-imported scenarios are persisted here, under the writable DATA_DIR
# volume (mounted + shared between the orchestrator and worker, so an imported
# pack is visible to the worker that deploys it and survives a restart). The
# registry (scenarios.py) discovers both directories.
SCENARIOS_DIR = Path(os.getenv("SCENARIOS_DIR", str(DATA_DIR / "scenarios")))

# Content-addressed local source-bundle intake (ROADMAP M4-B2). Upload bytes and
# expanded archive content are independently bounded; the total store cap keeps
# an operator mistake from filling the control-plane disk indefinitely.
SOURCE_BUNDLES_DIR = Path(
    os.getenv("SOURCE_BUNDLES_DIR", str(DATA_DIR / "source-bundles"))
)
SOURCE_BUNDLE_MAX_UPLOAD_BYTES = int(
    os.getenv("SOURCE_BUNDLE_MAX_UPLOAD_BYTES", str(32 * 1024 * 1024))
)
SOURCE_BUNDLE_MAX_EXPANDED_BYTES = int(
    os.getenv("SOURCE_BUNDLE_MAX_EXPANDED_BYTES", str(128 * 1024 * 1024))
)
SOURCE_BUNDLE_STORE_MAX_BYTES = int(
    os.getenv("SOURCE_BUNDLE_STORE_MAX_BYTES", str(2 * 1024 * 1024 * 1024))
)

# Content-addressed research evidence (ROADMAP M4-A). Artifacts are stored below
# an arena-derived directory, so an identical patch in two arenas never grants
# cross-arena access. Patch payloads and the aggregate store are independently
# bounded; audit events retain only their digest and metadata.
EVIDENCE_ARTIFACTS_DIR = Path(
    os.getenv("EVIDENCE_ARTIFACTS_DIR", str(DATA_DIR / "evidence-artifacts"))
)
EVIDENCE_ARTIFACT_MAX_BYTES = int(
    os.getenv("EVIDENCE_ARTIFACT_MAX_BYTES", str(1024 * 1024))
)
EVIDENCE_UNTRACKED_FILE_MAX_BYTES = int(
    os.getenv("EVIDENCE_UNTRACKED_FILE_MAX_BYTES", str(256 * 1024))
)
EVIDENCE_ARTIFACT_STORE_MAX_BYTES = int(
    os.getenv("EVIDENCE_ARTIFACT_STORE_MAX_BYTES", str(2 * 1024 * 1024 * 1024))
)

# Foothold file transfer (ROADMAP M4). The API accepts only relative paths below
# the provider-owned transfer root and chunks downloads to keep MCP context and
# HTTP memory bounded.
TRANSFER_MAX_FILE_BYTES = int(
    os.getenv("TRANSFER_MAX_FILE_BYTES", str(1024 * 1024))
)
TRANSFER_CHUNK_BYTES = int(
    os.getenv("TRANSFER_CHUNK_BYTES", str(256 * 1024))
)

# Arena-scoped headless browser (ROADMAP M4). The runner is a disposable Chrome
# headless-shell container attached only to the selected arena segment. Output,
# wall time, virtual JS time and container resources are all bounded.
HEADLESS_BROWSER_IMAGE = os.getenv(
    "HEADLESS_BROWSER_IMAGE", "zenika/alpine-chrome:124"
)
HEADLESS_BROWSER_TIMEOUT_SECONDS = int(
    os.getenv("HEADLESS_BROWSER_TIMEOUT_SECONDS", "12")
)
HEADLESS_BROWSER_MAX_OUTPUT_BYTES = int(
    os.getenv("HEADLESS_BROWSER_MAX_OUTPUT_BYTES", str(64 * 1024))
)
HEADLESS_BROWSER_MEMORY = os.getenv("HEADLESS_BROWSER_MEMORY", "512m")

# Arena-bound HTTP research primitive (ROADMAP R1). Like the headless browser,
# the runner is a disposable, capability-dropped container attached only to the
# selected arena segment. Redirects are never followed off the resolved target;
# request/response bodies are bounded before they cross the container boundary.
HTTP_RUNNER_IMAGE = os.getenv("HTTP_RUNNER_IMAGE", "curlimages/curl:8.14.1")
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))
HTTP_MAX_REQUEST_BYTES = int(
    os.getenv("HTTP_MAX_REQUEST_BYTES", str(256 * 1024))
)
HTTP_MAX_RESPONSE_BYTES = int(
    os.getenv("HTTP_MAX_RESPONSE_BYTES", str(1024 * 1024))
)
HTTP_RUNNER_MEMORY = os.getenv("HTTP_RUNNER_MEMORY", "128m")

# Arena HTTP transaction store (R1 slice 3): every primitive transaction is
# recorded content-addressed (the canonical request+response envelope is the
# digest), arena-scoped, and readable after the arena is destroyed. Identical
# re-sends dedup onto one record; a replay links to its parent via `replay_of`.
HTTP_TRANSACTIONS_DIR = Path(
    os.getenv("HTTP_TRANSACTIONS_DIR", str(DATA_DIR / "http-transactions"))
)
HTTP_TRANSACTION_MAX_BYTES = int(
    os.getenv("HTTP_TRANSACTION_MAX_BYTES", str(4 * 1024 * 1024))
)
HTTP_TRANSACTION_STORE_MAX_BYTES = int(
    os.getenv("HTTP_TRANSACTION_STORE_MAX_BYTES", str(512 * 1024 * 1024))
)
HTTP_TRANSACTIONS_LIST_LIMIT = int(
    os.getenv("HTTP_TRANSACTIONS_LIST_LIMIT", "100")
)

# OPENSTACK CREDENTIALS
OS_USERNAME = os.getenv("OS_USERNAME")
OS_PASSWORD = os.getenv("OS_PASSWORD")
OS_PROJECT_ID = os.getenv("OS_PROJECT_ID", os.getenv("OS_TENANT_ID"))
OS_AUTH_URL = os.getenv("OS_AUTH_URL")
OS_REGION_NAME = os.getenv("OS_REGION_NAME", "RegionOne")
OS_USER_DOMAIN_NAME = os.getenv("OS_USER_DOMAIN_NAME", "Default")
OS_PROJECT_DOMAIN_NAME = os.getenv("OS_PROJECT_DOMAIN_NAME", "Default")

# OPENSTACK RESOURCES
KEYPAIR_NAME = os.getenv("KEYPAIR_NAME", "nidavellir-key")
VICTIM_IMAGE_NAME = os.getenv("VICTIM_IMAGE_NAME", "Ubuntu-22.04")
ATTACKER_IMAGE_NAME = os.getenv("ATTACKER_IMAGE_NAME", "Kali-Linux")
SOC_IMAGE_NAME = os.getenv("SOC_IMAGE_NAME", "Ubuntu-22.04")

# Flavor defaults
ATTACKER_FLAVOR = os.getenv("ATTACKER_FLAVOR", "m1.medium")
VICTIM_FLAVOR = os.getenv("VICTIM_FLAVOR", "m1.small")
SOC_FLAVOR = os.getenv("SOC_FLAVOR", "m1.medium")

# CELERY & REDIS
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# DATABASE
DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "deployments.db"))

# TERRAFORM CONFIGURATION
TF_PLUGIN_CACHE_DIR = os.getenv("TF_PLUGIN_CACHE_DIR", str(CACHE_DIR / "terraform-plugins"))

# SECRETS / ENCRYPTION AT REST (audit #14)
# When set to a urlsafe-base64 32-byte Fernet key (generate with
# `python -m crypto`), lab outputs (SOC credentials, SSH commands, IPs) are
# encrypted before they are written to the deployments.outputs column. Unset
# -> plaintext passthrough (fine for the mock/dev demo; production should set
# it). See crypto.py.
SECRETS_ENCRYPTION_KEY = os.getenv("SECRETS_ENCRYPTION_KEY")

# SOFTWARE-UNDER-TEST (SUT) ARENAS — build-from-source execution (P1-6, ADR-0007).
# Building an arbitrary OSS repo executes third-party code at BUILD time (the
# Dockerfile RUN steps). M1 added the guardrails that make enabling this a
# supported operation: the M1-3 verified-build loop (a synthesized Dockerfile is
# only used after it builds green), build-time-egress-only (the arena RUNTIME
# stays egress-locked regardless), version-pinning + arena-labeled image reclaim
# on destroy(), and SSRF-guarded remote/clone contexts. It stays an explicit
# opt-in (not default-on) because build-time RUN still executes as the daemon,
# which is root-equivalent until M8 gets docker.sock off the orchestrator /
# rootless; flip the default only once that sandboxing lands. Covers source AND
# `service.package` builds. SOURCE_BUILD_TIMEOUT bounds the build. See SECURITY.md.
ALLOW_SOURCE_BUILD = os.getenv("NIDAVELLIR_ALLOW_SOURCE_BUILD", "false").lower() in (
    "true", "1", "yes", "on"
)
SOURCE_BUILD_TIMEOUT = int(os.getenv("SOURCE_BUILD_TIMEOUT", "1200"))

# Autonomous SUT configurator (ADR-0007 / P2-10 increment 3) — the most dangerous
# mode: an agent runs write/config commands on the victim WITHOUT per-step operator
# approval. OFF by default behind a DOUBLE LOCK — this platform flag AND explicit
# per-arena operator consent (mode="autonomous" at setup/start). HITL (per-step
# approval) and operator-scripted modes need neither.
ALLOW_AUTONOMOUS_CONFIGURATOR = os.getenv(
    "NIDAVELLIR_ALLOW_AUTONOMOUS_CONFIGURATOR", "false"
).lower() in ("true", "1", "yes", "on")

# API CONFIGURATION
API_HOST = os.getenv("API_HOST", "0.0.0.0")  # nosec B104 - container default, mapped by compose
API_PORT = int(os.getenv("API_PORT", "8000"))
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"

# WORKER CONFIGURATION
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "3"))
WORKER_LOG_LEVEL = os.getenv("WORKER_LOG_LEVEL", "INFO")
# Bound provider calls and Celery lifecycle tasks. A hard worker loss is then
# reconciled by the durable state/reaper path instead of hanging indefinitely.
DOCKER_API_TIMEOUT_SECONDS = int(os.getenv("DOCKER_API_TIMEOUT_SECONDS", "60"))
LAB_DEPLOY_TIMEOUT_SECONDS = int(os.getenv("LAB_DEPLOY_TIMEOUT_SECONDS", "900"))
LAB_DESTROY_TIMEOUT_SECONDS = int(os.getenv("LAB_DESTROY_TIMEOUT_SECONDS", "300"))
LAB_RESET_TIMEOUT_SECONDS = int(os.getenv("LAB_RESET_TIMEOUT_SECONDS", "600"))

# Confined PoC helpers (NV-03 / ADR-0014). The image must already exist on the
# worker's Docker daemon; execution never pulls or builds participant-controlled
# images. Per-job limits are further clamped by the API.
POC_RUNNER_IMAGE = os.getenv("NIDAVELLIR_POC_RUNNER_IMAGE", "nidavellir/poc-runner:py311")
POC_MAX_SOURCE_BYTES = int(os.getenv("NIDAVELLIR_POC_MAX_SOURCE_BYTES", "65536"))
POC_MAX_TRANSFER_FILES = int(os.getenv("NIDAVELLIR_POC_MAX_TRANSFER_FILES", "8"))
POC_MAX_TRANSFER_BYTES = int(os.getenv("NIDAVELLIR_POC_MAX_TRANSFER_BYTES", "1048576"))
POC_MAX_OUTPUT_BYTES = int(os.getenv("NIDAVELLIR_POC_MAX_OUTPUT_BYTES", "65536"))
POC_MAX_ARTIFACT_BYTES = int(os.getenv("NIDAVELLIR_POC_MAX_ARTIFACT_BYTES", "1048576"))
POC_MAX_ARTIFACTS = int(os.getenv("NIDAVELLIR_POC_MAX_ARTIFACTS", "8"))
POC_MAX_TIMEOUT_SECONDS = int(os.getenv("NIDAVELLIR_POC_MAX_TIMEOUT_SECONDS", "120"))
POC_MAX_ARENA_JOBS = int(os.getenv("NIDAVELLIR_POC_MAX_ARENA_JOBS", "2"))
POC_MAX_GLOBAL_JOBS = int(os.getenv("NIDAVELLIR_POC_MAX_GLOBAL_JOBS", "8"))
POC_STALE_SECONDS = max(
    int(os.getenv("NIDAVELLIR_POC_STALE_SECONDS", "180")),
    POC_MAX_TIMEOUT_SECONDS + 60,
)

# LAB LIFECYCLE / REAPER (audit #9)
# Every lab gets an expiry (created_at + LAB_TTL_MINUTES); a Celery-beat reaper
# destroys expired labs and reconciles labs stuck in a transient state (e.g. a
# worker that died mid-deploy leaving a lab 'pending' forever).
LAB_TTL_MINUTES = int(os.getenv("LAB_TTL_MINUTES", "180"))
REAPER_INTERVAL_SECONDS = int(os.getenv("REAPER_INTERVAL_SECONDS", "300"))
# A lab in pending/deploying/destroying that hasn't been touched in this long is
# considered orphaned (no live worker) and reconciled by the reaper.
LAB_STUCK_MINUTES = int(os.getenv("LAB_STUCK_MINUTES", "30"))

# M2 service-under-test monitor (ADR-0009). A Celery-beat task polls each ACTIVE
# arena, collects its SUT nodes' runtime state + log tail, runs the crash oracle
# (`monitor.detect_signals`), and appends NEW signals to the `events` stream.
# The window bounds the dedup fetch (how far back we look to avoid re-recording a
# persistent fault).
MONITOR_INTERVAL_SECONDS = int(os.getenv("NIDAVELLIR_MONITOR_INTERVAL_SECONDS", "30"))
MONITOR_EVENT_WINDOW = int(os.getenv("NIDAVELLIR_MONITOR_EVENT_WINDOW", "500"))

# VALIDATION
def validate_config():
    """Validate required configuration on startup"""
    errors = []
    warnings = []
    
    # OpenStack creds are mandatory only when OpenStack is the *active* default
    # provider. Mirror the precedence in providers.resolve_provider_name():
    # MOCK_MODE=true is a hard override (-> mock), so the no-infra demo needs no
    # OpenStack creds even when the compose default RANGE_PROVIDER=docker-local
    # (or =openstack) is still set. With MOCK_MODE off, RANGE_PROVIDER wins,
    # else openstack — so a container-only stack (RANGE_PROVIDER=docker-local,
    # MOCK_MODE=false) must still boot.
    mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
    range_provider = os.getenv("RANGE_PROVIDER")
    default_provider = "mock" if mock_mode else (range_provider or "openstack")

    if default_provider == "openstack":
        skip = "set MOCK_MODE=true or RANGE_PROVIDER=docker-local to skip"
        if not OS_USERNAME:
            errors.append(f"OS_USERNAME is required ({skip})")
        if not OS_PASSWORD:
            errors.append(f"OS_PASSWORD is required ({skip})")
        if not OS_PROJECT_ID:
            errors.append(f"OS_PROJECT_ID (or OS_TENANT_ID) is required ({skip})")
        if not OS_AUTH_URL:
            errors.append(f"OS_AUTH_URL is required ({skip})")
    if mock_mode:
        warnings.append("Running in MOCK_MODE - no real infrastructure will be created")

    # Encryption at rest for lab outputs (audit #14). Not fatal — the stack
    # still runs storing plaintext — but flag it loudly in a real run.
    if not mock_mode and not SECRETS_ENCRYPTION_KEY:
        warnings.append(
            "SECRETS_ENCRYPTION_KEY not set - lab outputs (incl. credentials) "
            "will be stored in plaintext. Generate one with `python -m crypto`."
        )

    # Check code directories exist
    for dir_name, dir_path in [
        ("TEMPLATES_DIR", TEMPLATES_DIR),
        ("BASE_TERRAFORM_TEMPLATE", BASE_TERRAFORM_TEMPLATE)
    ]:
        if not dir_path.exists():
            errors.append(f"{dir_name} does not exist: {dir_path}")
    
    if errors:
        error_msg = "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)
    
    # Create runtime directories if they don't exist
    for dir_path in [
        RUNS_DIR,
        DATA_DIR,
        KEYS_DIR,
        CACHE_DIR,
        SCENARIOS_DIR,
        SOURCE_BUNDLES_DIR,
    ]:
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"✅ Directory ready: {dir_path}")
    
    # Ensure plugin cache subdir exists
    Path(TF_PLUGIN_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    
    # Print warnings
    for warning in warnings:
        print(f"⚠️  WARNING: {warning}")
    
    print("✅ Configuration validated successfully")
    print(f"   BASE_DIR: {BASE_DIR}")
    print(f"   CYBER_RANGE_DIR: {CYBER_RANGE_DIR}")
    print(f"   TEMPLATES_DIR: {TEMPLATES_DIR}")
    print(f"   TERRAFORM_TEMPLATE: {BASE_TERRAFORM_TEMPLATE}")
    print(f"   RUNS_DIR: {RUNS_DIR}")
    print(f"   DATA_DIR: {DATA_DIR}")

# Deprecated alias for compatibility
TF_DIR = BASE_TERRAFORM_TEMPLATE

if __name__ == "__main__":
    # Test configuration
    try:
        validate_config()
        print("\n✅ All paths configured correctly!")
    except ValueError as e:
        print(f"\n❌ {e}")
