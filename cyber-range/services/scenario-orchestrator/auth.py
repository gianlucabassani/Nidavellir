"""
API-key authentication for the orchestrator API (ADR-0002).

Keys are high-entropy random tokens (`cg_<48 hex chars>`); only their SHA-256
digest is stored, so a database leak does not leak credentials. Each key
carries a role — authorization today is coarse (any valid key may call the
API); roles are recorded now so ownership/RBAC (roadmap Phase 3) and the
Agent Gateway (Phase 5) don't need a second migration.

Key management:
    python auth.py create-key <name> <role>     # prints the key ONCE
    python auth.py revoke-key <name>

Bootstrap (containers): set BOOTSTRAP_API_KEY (and optionally
BOOTSTRAP_API_KEY_ROLE, default "admin") in the environment and the API
registers it at startup — this is how docker-compose gives the WebUI a key.
"""
import hashlib
import logging
import os
import secrets
import sys
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from database import Database

logger = logging.getLogger(__name__)

# Platform roles (enterprise-arena pivot 2026-06-13): admin manages the
# platform/keys, operator authors/runs/observes engagements, agent is the AI
# under test. attacker/MITM/defender are per-session agent *stances* chosen via
# the MCP gateway, not auth roles. (Legacy keys with the old instructor/student
# roles still authenticate — the read path doesn't re-validate stored roles.)
ROLES = ("admin", "operator", "agent")

# Insecure default shared by docker-compose for the out-of-the-box mock demo.
# The API logs a loud warning when it is in use; never keep it in production.
DEV_INSECURE_KEY = "dev-insecure-key"

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller (key name + role) attached to a request."""

    name: str
    role: str


def generate_api_key() -> str:
    return f"cg_{secrets.token_hex(24)}"


def hash_api_key(key: str) -> str:
    # Keys are 192-bit random secrets, not passwords: a fast hash is the
    # correct choice (no brute-forceable structure to slow-hash against).
    return hashlib.sha256(key.encode()).hexdigest()


def require_principal(api_key: str = Security(_api_key_header)) -> Principal:
    """FastAPI dependency: resolve X-API-Key to a Principal or raise 401."""
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key (X-API-Key header)",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    record = Database().get_api_key(hash_api_key(api_key))
    if record is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return Principal(name=record["name"], role=record["role"])


def ensure_bootstrap_key(db: Database) -> None:
    """Register the BOOTSTRAP_API_KEY from the environment, if configured."""
    key = os.getenv("BOOTSTRAP_API_KEY")
    if not key:
        if db.count_api_keys() == 0:
            logger.warning(
                "No API keys exist — the API will reject every request. "
                "Create one with: python auth.py create-key <name> <role>"
            )
        return
    if key == DEV_INSECURE_KEY:
        logger.warning(
            "BOOTSTRAP_API_KEY is the well-known dev default — fine for the "
            "local mock demo, NEVER for a reachable deployment."
        )
    role = os.getenv("BOOTSTRAP_API_KEY_ROLE", "admin")
    if role not in ROLES:
        raise ValueError(f"BOOTSTRAP_API_KEY_ROLE must be one of {ROLES}, got {role!r}")
    if db.get_api_key(hash_api_key(key)) is None:
        db.create_api_key(hash_api_key(key), name="bootstrap", role=role)
        logger.info("Registered bootstrap API key (role=%s)", role)


def _cli() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = sys.argv[1:]
    db = Database()

    if len(args) == 3 and args[0] == "create-key":
        name, role = args[1], args[2]
        if role not in ROLES:
            print(f"role must be one of: {', '.join(ROLES)}")
            return 2
        key = generate_api_key()
        db.create_api_key(hash_api_key(key), name=name, role=role)
        print(f"API key for '{name}' (role={role}) — shown once, store it now:")
        print(key)
        return 0

    if len(args) == 2 and args[0] == "revoke-key":
        revoked = db.revoke_api_keys_by_name(args[1])
        print(f"Revoked {revoked} key(s) named '{args[1]}'")
        return 0 if revoked else 1

    print("Usage: python auth.py create-key <name> <role> | revoke-key <name>")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
