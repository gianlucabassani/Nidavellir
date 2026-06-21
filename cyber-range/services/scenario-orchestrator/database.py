"""
Persistence facade (ADR-0004): SQLAlchemy under the same `Database` API the
rest of the codebase has always used.

Backend selection:
  DATABASE_URL  — full SQLAlchemy URL (postgresql+psycopg://..., sqlite:///...)
  DATABASE_PATH — legacy SQLite file path (compose stacks set this)
  default       — sqlite file under ../../data/, zero external services.

Status writes are validated against the lifecycle graph in `states.py`
(IllegalTransition on violation), and every create / transition / record
deletion appends to the `events` audit table with the acting principal.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import sessionmaker

from crypto import decrypt_secret, encrypt_secret
from models import ApiKey, Base, Deployment, Event, ModelConnection
from states import LabStatus, validate_transition

# Labs in these states are still "live" (have or may have real infrastructure)
# and are candidates for TTL expiry.
LIVE_STATES = (
    LabStatus.PENDING,
    LabStatus.DEPLOYING,
    LabStatus.ACTIVE,
    LabStatus.ERROR_DESTROYING,
)
# Transient states a healthy worker moves through quickly; if a lab sits here
# untouched it means the worker driving it is gone (the "stuck pending" bug).
STUCK_STATES = (LabStatus.PENDING, LabStatus.DEPLOYING, LabStatus.DESTROYING)

# Legacy SQLite location (kept for compose stacks that set DATABASE_PATH)
DB_PATH = os.getenv(
    "DATABASE_PATH",
    str(Path(__file__).parent.parent.parent / "data" / "deployments.db"),
)


def database_url() -> str:
    """Resolve the SQLAlchemy URL: DATABASE_URL > DATABASE_PATH > default."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return f"sqlite:///{DB_PATH}"


def _stringify(value):
    # sqlite3.Row used to hand timestamps back as plain strings; keep that
    # contract so API responses and templates don't change shape.
    return str(value) if isinstance(value, datetime) else value


def _read_outputs(stored):
    """Decrypt the stored outputs blob back to JSON text (audit #14).

    `decrypt_secret` returns the value unchanged for legacy plaintext rows and
    when encryption is disabled. It returns None only when an encrypted value
    can't be recovered (key missing/rotated) — fall back to empty JSON so the
    status endpoint degrades to "no outputs" instead of erroring.
    """
    if stored is None:
        return stored
    plaintext = decrypt_secret(stored)
    return plaintext if plaintext is not None else "{}"


class Database:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        url = database_url()
        connect_args = {}
        if url.startswith("sqlite"):
            db_file = url.removeprefix("sqlite:///")
            if db_file:
                Path(db_file).parent.mkdir(parents=True, exist_ok=True)
            # The API serves requests from multiple threads over one engine
            connect_args["check_same_thread"] = False
        self._engine = create_engine(url, connect_args=connect_args)
        self._session = sessionmaker(bind=self._engine, expire_on_commit=False)
        # Idempotent bootstrap for fresh/dev databases: creates only missing
        # tables. Deployed databases evolve via `alembic upgrade head` — the
        # baseline migration matches this exact schema.
        Base.metadata.create_all(self._engine)

    @staticmethod
    def _row_to_dict(dep: Deployment) -> dict:
        return {
            "id": dep.id,
            "user_id": dep.user_id,
            "scenario": dep.scenario,
            "status": dep.status,
            "created_at": _stringify(dep.created_at),
            "updated_at": _stringify(dep.updated_at),
            "outputs": _read_outputs(dep.outputs),
            "error": dep.error,
            "provider": dep.provider,
            "expires_at": _stringify(dep.expires_at),
        }

    @staticmethod
    def _append_event(session, lab_id, actor, type_, payload=None):
        session.add(
            Event(
                lab_id=lab_id,
                ts=datetime.now(),
                actor=actor,
                type=type_,
                payload=json.dumps(payload) if payload is not None else None,
            )
        )

    # --- deployments ---------------------------------------------------------

    def create_deployment(
        self, deployment_id, user_id, scenario, provider=None, actor="system",
        expires_at=None,
    ):
        with self._session() as session:
            session.add(
                Deployment(
                    id=deployment_id,
                    user_id=user_id,
                    scenario=scenario,
                    status=LabStatus.PENDING,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    outputs="{}",
                    provider=provider,
                    expires_at=expires_at,
                )
            )
            self._append_event(
                session,
                deployment_id,
                actor,
                "created",
                {"scenario": scenario, "provider": provider, "name": user_id},
            )
            session.commit()
        return deployment_id

    def update_deployment(
        self, deployment_id, status=None, outputs=None, error=None, actor="system"
    ):
        with self._session() as session:
            dep = session.get(Deployment, deployment_id)
            if dep is None:
                return  # historical contract: updating a missing row is a no-op

            # `is not None`, not truthiness — and every status write goes
            # through the lifecycle graph (ADR-0004).
            if status is not None:
                validate_transition(dep.status, status)
                if status != dep.status:
                    self._append_event(
                        session,
                        deployment_id,
                        actor,
                        "status",
                        {"from": dep.status, "to": status},
                    )
                dep.status = status
            if outputs is not None:
                # Encrypted at rest when SECRETS_ENCRYPTION_KEY is set;
                # plaintext passthrough otherwise (audit #14).
                dep.outputs = encrypt_secret(json.dumps(outputs))
            if error is not None:
                dep.error = error
            dep.updated_at = datetime.now()
            session.commit()

    def get_deployment(self, deployment_id):
        with self._session() as session:
            dep = session.get(Deployment, deployment_id)
            return self._row_to_dict(dep) if dep else None

    def list_deployments(self):
        with self._session() as session:
            rows = session.scalars(
                select(Deployment).order_by(Deployment.created_at.desc())
            )
            return [self._row_to_dict(dep) for dep in rows]

    def delete_deployment(self, deployment_id, actor="system"):
        with self._session() as session:
            dep = session.get(Deployment, deployment_id)
            if dep is None:
                return False
            self._append_event(
                session, deployment_id, actor, "record_deleted", {"status": dep.status}
            )
            session.delete(dep)
            session.commit()
            return True

    def purge_deployments(self, statuses, actor="system"):
        """Delete every deployment record whose status is in `statuses`.

        Returns the number of rows removed. Used to clear the archive of
        terminal (destroyed/failed) labs — never call with live states.
        """
        with self._session() as session:
            rows = session.scalars(
                select(Deployment).where(Deployment.status.in_(list(statuses)))
            ).all()
            for dep in rows:
                self._append_event(
                    session, dep.id, actor, "record_deleted", {"status": dep.status}
                )
                session.delete(dep)
            session.commit()
            return len(rows)

    # --- reaper (TTL + stuck reconciliation, audit #9) -----------------------

    def find_reapable(self, now, stuck_before):
        """Labs the reaper should drive toward destruction.

        Two independent reasons (a lab can match either):
        - `expired`: a live lab past its `expires_at` (TTL elapsed). NULL
          `expires_at` is skipped — those opted out of TTL.
        - `stuck`: a lab sitting in a transient state (pending/deploying/
          destroying) with `updated_at` older than `stuck_before`, i.e. no
          live worker is driving it (the "stuck pending forever" failure).

        Returns `[{"id": ..., "status": ..., "reason": "expired"|"stuck"}]`.
        `expired` wins when a lab matches both (TTL is the deliberate signal).
        """
        with self._session() as session:
            rows = session.scalars(
                select(Deployment).where(
                    or_(
                        Deployment.status.in_(list(STUCK_STATES)),
                        Deployment.status.in_(list(LIVE_STATES)),
                    )
                )
            ).all()
            reapable = []
            for dep in rows:
                if (
                    dep.status in LIVE_STATES
                    and dep.expires_at is not None
                    and dep.expires_at <= now
                ):
                    reapable.append({"id": dep.id, "status": dep.status, "reason": "expired"})
                elif (
                    dep.status in STUCK_STATES
                    and dep.updated_at is not None
                    and dep.updated_at <= stuck_before
                ):
                    reapable.append({"id": dep.id, "status": dep.status, "reason": "stuck"})
            return reapable

    # --- events (audit stream, ADR-0004) -------------------------------------

    def record_event(self, lab_id, type, payload=None, actor="system"):
        """Append an audit event directly (e.g. reaper actions)."""
        with self._session() as session:
            self._append_event(session, lab_id, actor, type, payload)
            session.commit()

    def list_events(self, lab_id=None, limit=100, types=None):
        """Recent events (newest first), optionally for one lab and/or restricted
        to a set of event ``types``. The type filter lets the setup-phase derive
        the current session from setup-lifecycle events alone, so high-volume
        engagement noise (agent_exec/status/finding) can't push the open session
        out of the fetch window (the 500-event window bug)."""
        with self._session() as session:
            query = select(Event).order_by(Event.id.desc()).limit(limit)
            if lab_id is not None:
                query = query.where(Event.lab_id == lab_id)
            if types is not None:
                query = query.where(Event.type.in_(list(types)))
            return [
                {
                    "id": e.id,
                    "lab_id": e.lab_id,
                    "ts": _stringify(e.ts),
                    "actor": e.actor,
                    "type": e.type,
                    "payload": json.loads(e.payload) if e.payload else None,
                }
                for e in session.scalars(query)
            ]

    # --- API keys (ADR-0002) -------------------------------------------------
    # Only SHA-256 digests are stored; plaintext keys never touch the DB.

    def create_api_key(self, key_hash, name, role):
        with self._session() as session:
            session.add(
                ApiKey(key_hash=key_hash, name=name, role=role, created_at=datetime.now())
            )
            session.commit()

    def get_api_key(self, key_hash):
        """Return the active (non-revoked) key record, updating last_used_at."""
        with self._session() as session:
            key = session.get(ApiKey, key_hash)
            if key is None or key.revoked:
                return None
            key.last_used_at = datetime.now()
            record = {
                "key_hash": key.key_hash,
                "name": key.name,
                "role": key.role,
                "created_at": _stringify(key.created_at),
                "last_used_at": _stringify(key.last_used_at),
                "revoked": key.revoked,
            }
            session.commit()
            return record

    # --- model connections (operator's BYO agent model credential) ----------
    # The API key is Fernet-encrypted at rest; only a last-4 hint is kept clear.
    # Masked reads never expose the key; the plaintext is available only via
    # get_decrypted_model_credential for in-process use by activation features.

    @staticmethod
    def _mc_masked(row: ModelConnection) -> dict:
        return {
            "configured": True,
            "provider": row.provider,
            "model": row.model,
            "key_last4": row.key_last4,
            "status": row.status,
            "updated_at": _stringify(row.updated_at),
        }

    def upsert_model_connection(self, owner, provider, model, api_key, keep_key=False):
        """Create/replace the operator's model connection. Encrypts the API key
        at rest, keeps only a last-4 hint in clear, resets status to standby.
        Returns the masked view (never the key).

        ``keep_key=True`` updates provider/model but retains the stored key
        (the "update model, leave key blank" path); if there is no stored key
        yet it stores an empty one (keyless local runtimes)."""
        now = datetime.now()
        with self._session() as session:
            row = session.get(ModelConnection, owner)
            if row is None:
                row = ModelConnection(owner=owner, created_at=now)
                session.add(row)
            row.provider = provider
            row.model = model
            if not keep_key:
                row.encrypted_key = encrypt_secret(api_key or "")
                row.key_last4 = api_key[-4:] if api_key else None
            elif row.encrypted_key is None:
                row.encrypted_key = encrypt_secret("")
                row.key_last4 = None
            row.status = "standby"
            row.updated_at = now
            session.commit()
            return self._mc_masked(row)

    def get_model_connection(self, owner):
        """Masked view of the operator's model connection, or None. Never
        returns the API key."""
        with self._session() as session:
            row = session.get(ModelConnection, owner)
            return self._mc_masked(row) if row else None

    def set_model_connection_status(self, owner, status):
        """Flip the connection between 'standby' and 'active' (used by the
        activators). Returns the masked view, or None if unset."""
        with self._session() as session:
            row = session.get(ModelConnection, owner)
            if row is None:
                return None
            row.status = status
            session.commit()
            return self._mc_masked(row)

    def get_decrypted_model_credential(self, owner):
        """Plaintext provider/model/api_key for IN-PROCESS use by activation
        features (scenario generator, agent-stance launch) ONLY. Never exposed
        over HTTP, never logged. None if the operator has no connection."""
        with self._session() as session:
            row = session.get(ModelConnection, owner)
            if row is None:
                return None
            return {
                "provider": row.provider,
                "model": row.model,
                "api_key": decrypt_secret(row.encrypted_key),
            }

    def delete_model_connection(self, owner) -> bool:
        with self._session() as session:
            row = session.get(ModelConnection, owner)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def count_api_keys(self):
        with self._session() as session:
            return len(session.scalars(select(ApiKey).where(ApiKey.revoked == 0)).all())

    def revoke_api_keys_by_name(self, name):
        """Revoke (not delete: keep the audit trail) all keys with this name."""
        with self._session() as session:
            rows = session.scalars(
                select(ApiKey).where(ApiKey.name == name, ApiKey.revoked == 0)
            ).all()
            for key in rows:
                key.revoked = 1
            session.commit()
            return len(rows)
