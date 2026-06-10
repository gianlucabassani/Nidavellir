"""
Shared test fixtures and environment setup.

CRITICAL: this module runs BEFORE any application module is imported, so it is
the only safe place to redirect all runtime state (database, workspaces, keys)
at a throwaway temp directory and force MOCK_MODE. Several app modules capture
configuration into module-level constants at import time, so the environment
must be set here, not inside individual tests.
"""
import os
import sys
import tempfile
from pathlib import Path

# --- 1. Redirect runtime state to a throwaway dir, force mock mode ---------
_TMP = Path(tempfile.mkdtemp(prefix="cyberguard-tests-"))
os.environ.setdefault("MOCK_MODE", "true")
os.environ["DATABASE_PATH"] = str(_TMP / "deployments.db")
os.environ["RUNS_DIR"] = str(_TMP / "runs")
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["KEYS_DIR"] = str(_TMP / "keys")
os.environ["CACHE_DIR"] = str(_TMP / "cache")
os.environ["TF_PLUGIN_CACHE_DIR"] = str(_TMP / "cache" / "terraform-plugins")
# Rate limiting would trip on the suite's rapid-fire requests; the dedicated
# rate-limit test re-enables it explicitly.
os.environ["RATE_LIMIT_ENABLED"] = "false"

# --- 2. Make the orchestrator package importable ---------------------------
# The service uses flat imports (`from database import Database`), so its
# directory must be on sys.path. pytest.ini also sets `pythonpath`, this is a
# belt-and-suspenders guarantee.
_ORCH = (
    Path(__file__).resolve().parent.parent
    / "cyber-range"
    / "services"
    / "scenario-orchestrator"
)
sys.path.insert(0, str(_ORCH))


def pytest_report_header(config):
    return f"cyberguard: MOCK_MODE={os.environ['MOCK_MODE']}  state={_TMP}"
