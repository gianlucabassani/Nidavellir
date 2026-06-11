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

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models import ApiKey, Base, Deployment, Event
from states import LabStatus, validate_transition

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
            "outputs": dep.outputs,
            "error": dep.error,
            "provider": dep.provider,
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
        self, deployment_id, user_id, scenario, provider=None, actor="system"
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
                dep.outputs = json.dumps(outputs)
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

    # --- events (audit stream, ADR-0004) -------------------------------------

    def list_events(self, lab_id=None, limit=100):
        with self._session() as session:
            query = select(Event).order_by(Event.id.desc()).limit(limit)
            if lab_id is not None:
                query = query.where(Event.lab_id == lab_id)
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
