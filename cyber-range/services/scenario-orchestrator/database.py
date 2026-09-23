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
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from crypto import decrypt_secret, encrypt_secret
import setup_phase
from models import (
    ApiKey, Base, BudgetAccount, BudgetAction, BudgetControl, BudgetGate, Deployment, Event,
    LifecycleRecipe, ModelConnection, PocJob,
    ResetOperation,
)
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
STUCK_STATES = (
    LabStatus.PENDING,
    LabStatus.DEPLOYING,
    LabStatus.DESTROYING,
    LabStatus.ERROR_DESTROYING,
)

# Legacy SQLite location (kept for compose stacks that set DATABASE_PATH)
DB_PATH = os.getenv(
    "DATABASE_PATH",
    str(Path(__file__).parent.parent.parent / "data" / "deployments.db"),
)


class StopDenied(ValueError):
    """A system-wide stop rejected new infrastructure admission."""


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
        with self._session() as session:
            if session.get(BudgetGate, "system") is None:
                session.add(BudgetGate(scope="system", account_scope=None, epoch=0,
                                       state="open", updated_at=datetime.now()))
                session.commit()

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
            "effective_provider": dep.effective_provider,
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
        expires_at=None, effective_provider=None,
    ):
        with self._session() as session:
            system = self._lock_gate(session, "system")
            if system.state != "open":
                raise StopDenied("system emergency stop is active")
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
                    effective_provider=effective_provider,
                    expires_at=expires_at,
                )
            )
            self._append_event(
                session,
                deployment_id,
                actor,
                "created",
                {
                    "scenario": scenario, "provider": provider,
                    "effective_provider": effective_provider, "name": user_id,
                },
            )
            deadline = expires_at or datetime.now() + timedelta(days=365)
            cap = max(1, min(int(os.getenv("ARENA_ACTION_BUDGET", "1000")), 100000))
            session.add(BudgetAccount(
                arena_id=deployment_id, scope_id=deployment_id, version=1,
                action_cap=cap, spent=0, reserved=0, deadline=deadline,
                created_at=datetime.now(),
            ))
            session.add(BudgetGate(scope=deployment_id, account_scope=deployment_id,
                                   epoch=0, state="open", updated_at=datetime.now()))
            session.commit()
        return deployment_id

    @staticmethod
    def _lock_gate(session, scope):
        # UPDATE obtains a PostgreSQL row lock and a SQLite writer reservation.
        session.execute(update(BudgetGate).where(BudgetGate.scope == scope)
                        .values(updated_at=BudgetGate.updated_at))
        return session.get(BudgetGate, scope)

    @staticmethod
    def _lock_account(session, scope):
        session.execute(update(BudgetAccount).where(BudgetAccount.arena_id == scope)
                        .values(spent=BudgetAccount.spent))
        return session.get(BudgetAccount, scope)

    def budget_status(self, arena_id):
        with self._session() as session:
            system = session.get(BudgetGate, "system")
            gate = session.get(BudgetGate, arena_id)
            account = session.get(BudgetAccount, gate.account_scope) if gate and gate.account_scope else None
            return {
                "system": {"state": system.state, "epoch": system.epoch} if system else None,
                "arena": {"state": gate.state, "epoch": gate.epoch,
                          "reason": gate.reason} if gate else None,
                "policy": {"version": account.version, "action_cap": account.action_cap,
                           "spent": account.spent, "reserved": account.reserved,
                           "remaining": account.action_cap - account.spent - account.reserved,
                           "deadline": _stringify(account.deadline),
                           "token_cost": "unsupported_for_external_agents"} if account else None,
            }

    def stopping_budget_scopes(self):
        with self._session() as session:
            return list(session.scalars(select(BudgetGate.scope).where(
                BudgetGate.state == "stopping")))

    def expired_budget_arenas(self, now):
        with self._session() as session:
            rows = session.execute(select(BudgetGate.scope).join(
                BudgetAccount, BudgetGate.account_scope == BudgetAccount.arena_id
            ).where(BudgetGate.state == "open", BudgetAccount.deadline <= now))
            return [row[0] for row in rows]

    def inherit_budget_scope(self, source_id, replacement_id):
        """A replacement UUID retains its source's aggregate account and stop state."""
        with self._session() as session:
            self._lock_gate(session, "system")
            source = self._lock_gate(session, source_id)
            replacement = self._lock_gate(session, replacement_id)
            if source is None or replacement is None:
                raise ValueError("reset budget gate is missing")
            replacement.account_scope = source.account_scope
            replacement.state = source.state
            replacement.reason = source.reason
            replacement.epoch = source.epoch
            session.delete(session.get(BudgetAccount, replacement_id))
            session.commit()

    def revise_budget_policy(self, arena_id, *, action_cap, deadline, actor, reason):
        if not reason or len(reason) > 500:
            raise ValueError("a bounded policy-change reason is required")
        if action_cap < 1 or action_cap > 100000:
            raise ValueError("action cap must be between 1 and 100000")
        with self._session() as session:
            self._lock_gate(session, "system")
            gate = self._lock_gate(session, arena_id)
            if gate is None:
                raise ValueError("legacy arena has no durable budget policy")
            account = self._lock_account(session, gate.account_scope)
            dep = session.get(Deployment, arena_id)
            if dep is None or dep.status != LabStatus.ACTIVE:
                raise ValueError("arena must be active for a policy change")
            if action_cap < account.spent + account.reserved:
                raise ValueError("new cap is below committed and reserved actions")
            if deadline <= datetime.now() or (dep.expires_at and deadline > dep.expires_at):
                raise ValueError("deadline must be future and within deployment expiry")
            account.action_cap = action_cap
            account.deadline = deadline
            account.version += 1
            self._append_event(session, arena_id, actor, "budget_policy_revised", {
                "version": account.version, "action_cap": action_cap,
                "deadline": deadline.isoformat(), "reason": reason,
            })
            session.commit()
            return account.version

    def reserve_budget_action(self, arena_id, *, key, digest, kind, actor):
        """Serialize stop, deadline and aggregate cap with one action reservation."""
        now = datetime.now()
        with self._session() as session:
            system = self._lock_gate(session, "system")
            gate = self._lock_gate(session, arena_id)
            if gate is None:
                raise ValueError("arena has no durable budget policy (legacy arena)")
            account = self._lock_account(session, gate.account_scope)
            existing = session.scalar(select(BudgetAction).where(
                BudgetAction.arena_id == arena_id, BudgetAction.action_key == key))
            if existing:
                if existing.input_digest != digest or existing.actor != actor or existing.kind != kind:
                    raise ValueError("action idempotency key was reused with different input")
                raise ValueError(f"action {existing.id} is already {existing.state}")
            if system.state != "open" or gate.state != "open":
                self._append_event(session, arena_id, actor, "budget_denied",
                                   {"kind": kind, "reason": "stopped"})
                session.commit()
                raise ValueError("research work is stopped")
            dep = session.get(Deployment, arena_id)
            if dep is None or dep.status != LabStatus.ACTIVE:
                raise ValueError("arena is no longer active")
            if account.deadline <= now:
                gate.state = "stopping"
                gate.reason = "wall-clock budget expired"
                gate.epoch += 1
                gate.updated_at = now
                self._append_event(session, arena_id, "budget", "arena_stop",
                                   {"epoch": gate.epoch, "reason": gate.reason})
                session.commit()
                raise ValueError("wall-clock budget expired")
            if account.spent + account.reserved >= account.action_cap:
                self._append_event(session, arena_id, actor, "budget_denied",
                                   {"kind": kind, "reason": "action_cap"})
                session.commit()
                raise ValueError("action budget exhausted")
            setup_step = kind in {"setup/step", "setup/run", "setup/upload"} or (
                kind.startswith("setup/proposals/") and kind.endswith("/approve"))
            if setup_step:
                rows = list(session.scalars(select(Event).where(
                    Event.lab_id == arena_id,
                    Event.type.in_(setup_phase.SETUP_EVENT_TYPES),
                ).order_by(Event.id.desc()).limit(setup_phase.SETUP_EVENT_WINDOW)))
                events = [{"id": row.id, "type": row.type,
                           "payload": json.loads(row.payload) if row.payload else {}}
                          for row in rows]
                setup = setup_phase.current_session(events)
                if setup:
                    setup_kind = f"setup-step:{setup['session_id']}"
                    # Count every ledger row, not just the first, while older
                    # event-only setup steps remain visible via steps_run.
                    ledger_actions = list(session.scalars(select(BudgetAction).where(
                        BudgetAction.arena_id == arena_id,
                        BudgetAction.kind == setup_kind,
                        BudgetAction.state.in_(("reserved", "spent", "unknown")),
                    )))
                    first_action = min((action.created_at for action in ledger_actions),
                                       default=None)
                    legacy_steps = sum(
                        row.type == setup_phase.SETUP_STEP
                        and row.id > setup["open_event_id"]
                        and (first_action is None or row.ts < first_action)
                        for row in rows
                    )
                    used = max(setup["steps_run"], legacy_steps + len(ledger_actions))
                    if used >= setup["command_budget"]:
                        raise ValueError("setup command budget exhausted")
                    kind = setup_kind
            account.reserved += 1
            action = BudgetAction(id=str(uuid.uuid4()), arena_id=arena_id,
                                  scope_id=account.scope_id, action_key=key,
                                  input_digest=digest, kind=kind, actor=actor,
                                  state="reserved", epoch=gate.epoch,
                                  created_at=now, updated_at=now)
            session.add(action)
            self._append_event(session, arena_id, actor, "budget_reserved",
                               {"action_id": action.id, "kind": kind})
            session.commit()
            return action.id, account.deadline

    def settle_budget_action(self, action_id, *, outcome):
        if outcome not in {"spent", "released", "unknown"}:
            raise ValueError("invalid budget outcome")
        with self._session() as session:
            action = session.get(BudgetAction, action_id)
            if action is None or action.state != "reserved":
                return False
            self._lock_gate(session, "system")
            self._lock_gate(session, action.arena_id)
            account = self._lock_account(session, action.scope_id)
            account.reserved -= 1
            if outcome != "released":
                account.spent += 1  # ambiguous execution is charged, never replayed
            action.state = outcome
            action.updated_at = datetime.now()
            self._append_event(session, action.arena_id, action.actor, "budget_settled",
                               {"action_id": action_id, "outcome": outcome})
            session.commit()
            return True

    @staticmethod
    def _control_replay(session, scope, key, command, actor, reason):
        row = session.get(BudgetControl, (scope, key))
        if row is None:
            return None
        if (row.command, row.actor, row.reason) != (command, actor, reason):
            raise ValueError("stop idempotency key was reused with different input")
        return row.epoch

    def stop_budget_gate(self, scope, *, actor, reason, key=None):
        if not reason or len(reason) > 500:
            raise ValueError("a bounded stop reason is required")
        key = key or str(uuid.uuid4())
        with self._session() as session:
            self._lock_gate(session, "system")
            gate = self._lock_gate(session, scope) if scope != "system" else session.get(BudgetGate, "system")
            if gate is None:
                raise ValueError("unknown stop scope")
            replay = self._control_replay(session, scope, key, "stop", actor, reason)
            if replay is not None:
                return replay
            if gate.state == "open":
                gate.state = "stopping"
                gate.epoch += 1
                gate.reason = reason
                gate.updated_at = datetime.now()
                self._append_event(session, scope, actor, "arena_stop" if scope != "system" else "system_stop",
                                   {"epoch": gate.epoch, "reason": reason})
            session.add(BudgetControl(scope=scope, idempotency_key=key,
                                      command="stop", actor=actor, reason=reason,
                                      epoch=gate.epoch, created_at=datetime.now()))
            session.commit()
            return gate.epoch

    def reconcile_budget_stop(self, scope):
        with self._session() as session:
            self._lock_gate(session, "system")
            gate = self._lock_gate(session, scope) if scope != "system" else session.get(BudgetGate, "system")
            if not gate or gate.state != "stopping":
                return False
            scopes = [g.scope for g in session.scalars(select(BudgetGate).where(BudgetGate.scope != "system"))] if scope == "system" else [scope]
            active_actions = session.scalar(select(BudgetAction.id).where(
                BudgetAction.arena_id.in_(scopes), BudgetAction.state == "reserved").limit(1))
            active_jobs = session.scalar(select(PocJob.id).where(
                PocJob.arena_id.in_(scopes),
                (PocJob.state.in_(("queued", "running")) |
                 PocJob.cleanup_state.in_(("pending", "incomplete", "reconcile_pending")))).limit(1))
            if active_actions or active_jobs:
                return False
            gate.state = "stopped"
            gate.updated_at = datetime.now()
            self._append_event(session, scope, "reaper", "stop_verified", {"epoch": gate.epoch})
            session.commit()
            return True

    def resume_budget_gate(self, scope, *, actor, reason, key=None):
        if not reason or len(reason) > 500:
            raise ValueError("a bounded resume reason is required")
        key = key or str(uuid.uuid4())
        self.reconcile_budget_stop(scope)
        with self._session() as session:
            self._lock_gate(session, "system")
            gate = self._lock_gate(session, scope) if scope != "system" else session.get(BudgetGate, "system")
            replay = self._control_replay(session, scope, key, "resume", actor, reason)
            if replay is not None:
                return replay
            if gate is None or gate.state != "stopped":
                raise ValueError("stop has not drained and been verified")
            account = session.get(BudgetAccount, gate.account_scope) if gate.account_scope else None
            if account and account.deadline <= datetime.now():
                raise ValueError("wall-clock budget has expired")
            gate.state = "open"
            gate.epoch += 1
            gate.reason = reason
            gate.updated_at = datetime.now()
            self._append_event(session, scope, actor, "stop_cleared",
                               {"epoch": gate.epoch, "reason": reason})
            session.add(BudgetControl(scope=scope, idempotency_key=key,
                                      command="resume", actor=actor, reason=reason,
                                      epoch=gate.epoch, created_at=datetime.now()))
            session.commit()
            return gate.epoch

    @contextmanager
    def helper_start_guard(self, arena_id, job_id):
        """Hold both stop gates while a worker creates or starts one helper.

        Stop cannot commit midway through a Docker create/start call. Once it
        commits, every later guard fails before touching Docker.
        """
        with self._session() as session:
            system = self._lock_gate(session, "system")
            gate = self._lock_gate(session, arena_id)
            job = session.get(PocJob, job_id)
            account = session.get(BudgetAccount, gate.account_scope) if gate else None
            dep = session.get(Deployment, arena_id)
            now = datetime.now()
            if (system.state != "open" or gate is None or gate.state != "open"
                    or job is None or job.state != "running" or job.cancel_requested
                    or account.deadline <= now or job.deadline <= now
                    or dep is None or dep.status != LabStatus.ACTIVE):
                raise ValueError("helper start was cancelled or stopped")
            yield
            session.commit()

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

    def transition_deployment(self, deployment_id, expected, new, *, actor="system"):
        """Atomically claim a lifecycle transition and append its audit event.

        Returns False when another worker moved the record first. Idempotence is
        handled by callers deliberately rather than hiding a stale claim.
        """
        expected = tuple(str(value) for value in expected)
        with self._session() as session:
            dep = session.get(Deployment, deployment_id)
            if dep is None or dep.status not in expected:
                return False
            validate_transition(dep.status, new)
            old = dep.status
            result = session.execute(
                update(Deployment)
                .where(Deployment.id == deployment_id, Deployment.status == old)
                .values(status=new, updated_at=datetime.now())
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            if old != new:
                self._append_event(
                    session, deployment_id, actor, "status", {"from": old, "to": new}
                )
            session.commit()
            return True

    # --- NV-02 lifecycle recipes / reset operations -------------------------

    def save_lifecycle_recipe(self, deployment_id, recipe):
        encoded = encrypt_secret(json.dumps(recipe, sort_keys=True))
        with self._session() as session:
            row = session.get(LifecycleRecipe, deployment_id)
            if row is None:
                row = LifecycleRecipe(
                    deployment_id=deployment_id,
                    digest=recipe["recipe_digest"],
                    encrypted_payload=encoded,
                    created_at=datetime.now(),
                )
                session.add(row)
            elif row.digest != recipe["recipe_digest"]:
                raise ValueError("a lifecycle recipe is immutable once recorded")
            session.commit()

    def get_lifecycle_recipe(self, deployment_id):
        with self._session() as session:
            row = session.get(LifecycleRecipe, deployment_id)
            if row is None:
                return None
            plaintext = decrypt_secret(row.encrypted_payload)
            if plaintext is None:
                raise ValueError("lifecycle recipe could not be decrypted")
            return json.loads(plaintext)

    @staticmethod
    def _reset_to_dict(row):
        if row is None:
            return None
        return {
            "id": row.id,
            "source_id": row.source_id,
            "replacement_id": row.replacement_id,
            "idempotency_key": row.idempotency_key,
            "recipe_digest": row.recipe_digest,
            "status": row.status,
            "stage": row.stage,
            "deadline": _stringify(row.deadline),
            "created_at": _stringify(row.created_at),
            "updated_at": _stringify(row.updated_at),
            "error": row.error,
            "result": json.loads(row.result) if row.result else None,
        }

    def create_reset_operation(
        self, *, operation_id, source_id, replacement_id, idempotency_key,
        recipe_digest, deadline,
    ):
        now = datetime.now()
        with self._session() as session:
            existing = session.scalar(
                select(ResetOperation).where(
                    ResetOperation.source_id == source_id,
                    ResetOperation.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return self._reset_to_dict(existing), False
            row = ResetOperation(
                id=operation_id,
                source_id=source_id,
                replacement_id=replacement_id,
                idempotency_key=idempotency_key,
                active_source=source_id,
                recipe_digest=recipe_digest,
                status="pending",
                stage="claimed",
                deadline=deadline,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                existing = session.scalar(
                    select(ResetOperation).where(
                        ResetOperation.source_id == source_id,
                        ResetOperation.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return self._reset_to_dict(existing), False
                raise ValueError("another reset is already in flight for this arena") from exc
            return self._reset_to_dict(row), True

    def get_reset_operation(self, operation_id):
        with self._session() as session:
            return self._reset_to_dict(session.get(ResetOperation, operation_id))

    def get_reset_operation_by_replacement(self, replacement_id):
        with self._session() as session:
            return self._reset_to_dict(session.scalar(
                select(ResetOperation).where(ResetOperation.replacement_id == replacement_id)
            ))

    def list_reset_operations(self, source_id=None, *, active_only=False):
        with self._session() as session:
            stmt = select(ResetOperation).order_by(ResetOperation.created_at.desc())
            if source_id is not None:
                stmt = stmt.where(ResetOperation.source_id == source_id)
            if active_only:
                stmt = stmt.where(ResetOperation.active_source.is_not(None))
            return [self._reset_to_dict(row) for row in session.scalars(stmt).all()]

    def update_reset_operation(self, operation_id, *, status=None, stage=None,
                               error=None, result=None, terminal=False):
        with self._session() as session:
            row = session.get(ResetOperation, operation_id)
            if row is None:
                return False
            if status is not None:
                row.status = status
            if stage is not None:
                row.stage = stage
            if error is not None:
                row.error = str(error)[:4000]
            if result is not None:
                row.result = json.dumps(result, sort_keys=True)
            if terminal:
                row.active_source = None
            row.updated_at = datetime.now()
            session.commit()
            return True

    def claim_reset_operation(self, operation_id, *, actor_stage="destroying_source"):
        """Atomically claim a pending reset for one worker.

        Celery delivery is at-least-once. A conditional UPDATE makes duplicate
        deliveries harmless on both SQLite and PostgreSQL without relying on a
        process-local lock.
        """
        with self._session() as session:
            result = session.execute(
                update(ResetOperation)
                .where(
                    ResetOperation.id == operation_id,
                    ResetOperation.status == "pending",
                    ResetOperation.active_source.is_not(None),
                )
                .values(
                    status="running",
                    stage=actor_stage,
                    updated_at=datetime.now(),
                )
            )
            session.commit()
            return result.rowcount == 1

    def recover_stale_reset_operations(self, stale_before):
        """Return stale running operations to pending so the reaper can resume them."""
        now = datetime.now()
        with self._session() as session:
            ids = list(session.scalars(
                select(ResetOperation.id).where(
                    ResetOperation.status == "running",
                    ResetOperation.active_source.is_not(None),
                    ResetOperation.updated_at < stale_before,
                )
            ))
            recovered = []
            for operation_id in ids:
                result = session.execute(
                    update(ResetOperation)
                    .where(
                        ResetOperation.id == operation_id,
                        ResetOperation.status == "running",
                        ResetOperation.updated_at < stale_before,
                    )
                    .values(status="pending", stage="recovery_pending", updated_at=now)
                )
                if result.rowcount == 1:
                    recovered.append(operation_id)
            session.commit()
            return recovered

    # --- NV-03 confined PoC jobs -------------------------------------------

    @staticmethod
    def _poc_to_dict(row, *, include_payload=False):
        if row is None:
            return None
        result = decrypt_secret(row.result) if row.result else None
        payload = decrypt_secret(row.encrypted_payload) if include_payload else None
        return {
            "id": row.id,
            "arena_id": row.arena_id,
            "principal": row.principal,
            "principal_role": row.principal_role,
            "binding_stance": row.binding_stance,
            "idempotency_key": row.idempotency_key,
            "input_digest": row.input_digest,
            "payload": json.loads(payload) if payload else None,
            "runner_image": row.runner_image,
            "runner_image_id": row.runner_image_id,
            "target_node": row.target_node,
            "target_policy": json.loads(row.target_policy) if row.target_policy else None,
            "limits": json.loads(row.limits),
            "deadline": _stringify(row.deadline),
            "state": row.state,
            "worker_claim": row.worker_claim,
            "cancel_requested": bool(row.cancel_requested),
            "result": json.loads(result) if result else None,
            "cleanup_state": row.cleanup_state,
            "cleanup_error": row.cleanup_error,
            "created_at": _stringify(row.created_at),
            "updated_at": _stringify(row.updated_at),
            "started_at": _stringify(row.started_at),
            "completed_at": _stringify(row.completed_at),
        }

    def create_poc_job(
        self, *, job_id, arena_id, principal, principal_role, binding_stance, idempotency_key,
        input_digest, payload, runner_image, target_node, target_policy, limits,
        deadline, max_arena_jobs, max_global_jobs,
    ):
        """Create a job and atomically reserve one arena and global slot."""
        now = datetime.now()
        target_json = json.dumps(target_policy, sort_keys=True)
        limits_json = json.dumps(limits, sort_keys=True)

        def assert_same_request(existing):
            same = (
                existing.principal == principal
                and existing.principal_role == principal_role
                and existing.input_digest == input_digest
                and existing.runner_image == runner_image
                and existing.target_node == target_node
                and existing.target_policy == target_json
                and existing.limits == limits_json
            )
            if not same:
                raise ValueError("idempotency key was already used with different input")

        with self._session() as session:
            existing = session.scalar(select(PocJob).where(
                PocJob.arena_id == arena_id,
                PocJob.idempotency_key == idempotency_key,
            ))
            if existing is not None:
                assert_same_request(existing)
                return self._poc_to_dict(existing), False

        for arena_slot in range(max_arena_jobs):
            for global_slot in range(max_global_jobs):
                with self._session() as session:
                    system = self._lock_gate(session, "system")
                    gate = self._lock_gate(session, arena_id)
                    if system.state != "open" or gate is None or gate.state != "open":
                        raise ValueError("research work is stopped or has no durable gate")
                    account = self._lock_account(session, gate.account_scope)
                    existing = session.scalar(select(PocJob).where(
                        PocJob.arena_id == arena_id,
                        PocJob.idempotency_key == idempotency_key,
                    ))
                    if existing is not None:
                        assert_same_request(existing)
                        return self._poc_to_dict(existing), False
                    if account.deadline <= now:
                        raise ValueError("wall-clock budget expired")
                    deadline = min(deadline, account.deadline)
                    budgeted = payload.get("primitive") not in {"http", "browser"}
                    if budgeted and account.spent + account.reserved >= account.action_cap:
                        raise ValueError("action budget exhausted")
                    # Serialize admission with the arena's destroy/reset state
                    # transition on both SQLite and PostgreSQL. An API entry
                    # check alone can race teardown while queueing new work.
                    admitted = session.execute(update(Deployment).where(
                        Deployment.id == arena_id, Deployment.status == LabStatus.ACTIVE,
                    ).values(updated_at=Deployment.updated_at))
                    if admitted.rowcount != 1:
                        raise ValueError("arena is no longer active")
                    row = PocJob(
                        id=job_id, arena_id=arena_id, principal=principal,
                        principal_role=principal_role,
                        binding_stance=binding_stance, idempotency_key=idempotency_key,
                        input_digest=input_digest,
                        encrypted_payload=encrypt_secret(json.dumps(payload, sort_keys=True)),
                        runner_image=runner_image, target_node=target_node,
                        target_policy=target_json,
                        limits=limits_json, deadline=deadline,
                        state="queued", cleanup_state="pending",
                        active_arena_slot=f"{arena_id}:{arena_slot}",
                        active_global_slot=f"global:{global_slot}",
                        created_at=now, updated_at=now,
                    )
                    session.add(row)
                    if budgeted:
                        account.reserved += 1
                        session.add(BudgetAction(
                            id=job_id, arena_id=arena_id, scope_id=account.scope_id,
                            action_key=f"poc:{idempotency_key}", input_digest=input_digest,
                            kind="poc", actor=principal, state="reserved", epoch=gate.epoch,
                            created_at=now, updated_at=now,
                        ))
                        self._append_event(session, arena_id, principal, "budget_reserved",
                                           {"action_id": job_id, "kind": "poc"})
                    try:
                        session.commit()
                        return self._poc_to_dict(row), True
                    except IntegrityError:
                        session.rollback()
                        existing = session.scalar(select(PocJob).where(
                            PocJob.arena_id == arena_id,
                            PocJob.idempotency_key == idempotency_key,
                        ))
                        if existing is not None:
                            assert_same_request(existing)
                            return self._poc_to_dict(existing), False
        raise ValueError("confined PoC execution capacity is exhausted")

    def get_poc_job(self, job_id, *, include_payload=False):
        with self._session() as session:
            return self._poc_to_dict(session.get(PocJob, job_id), include_payload=include_payload)

    def list_poc_jobs(self, arena_id):
        with self._session() as session:
            rows = session.scalars(
                select(PocJob).where(PocJob.arena_id == arena_id)
                .order_by(PocJob.created_at.desc())
            )
            return [self._poc_to_dict(row) for row in rows]

    def list_active_poc_jobs(self):
        with self._session() as session:
            rows = session.scalars(
                select(PocJob).where(PocJob.state.in_(("queued", "running")))
                .order_by(PocJob.created_at.asc())
            )
            return [self._poc_to_dict(row) for row in rows]

    def claim_poc_job(self, job_id, worker_claim):
        now = datetime.now()
        with self._session() as session:
            job = session.get(PocJob, job_id)
            if job is None:
                return False
            system = self._lock_gate(session, "system")
            gate = self._lock_gate(session, job.arena_id)
            account = session.get(BudgetAccount, gate.account_scope) if gate else None
            if (system.state != "open" or gate is None or gate.state != "open"
                    or account.deadline <= now):
                return False
            result = session.execute(
                update(PocJob).where(
                    PocJob.id == job_id, PocJob.state == "queued",
                    PocJob.cancel_requested == 0,
                ).values(
                    state="running", worker_claim=worker_claim,
                    started_at=now, updated_at=now,
                )
            )
            session.commit()
            return result.rowcount == 1

    def request_cancel_poc_job(self, job_id):
        now = datetime.now()
        with self._session() as session:
            # Conditional writes prevent a queued read racing a worker claim
            # from releasing slots while a helper is being created.
            session.execute(update(PocJob).where(
                PocJob.id == job_id, PocJob.state == "queued",
            ).values(
                state="cancelled", cancel_requested=1, cleanup_state="not_started",
                active_arena_slot=None, active_global_slot=None,
                completed_at=now, updated_at=now,
            ))
            session.execute(update(PocJob).where(
                PocJob.id == job_id, PocJob.state == "running",
                PocJob.cancel_requested == 0,
            ).values(cancel_requested=1, updated_at=now))
            session.commit()
            result = self._poc_to_dict(session.get(PocJob, job_id))
        if result and result["state"] == "cancelled" and result["started_at"] is None:
            self.settle_budget_action(job_id, outcome="released")
        return result

    def request_cancel_arena_poc_jobs(self, arena_id):
        with self._session() as session:
            ids = list(session.scalars(select(PocJob.id).where(
                PocJob.arena_id == arena_id, PocJob.state.in_(("queued", "running"))
            )))
        for job_id in ids:
            self.request_cancel_poc_job(job_id)
        return len(ids)

    def finish_poc_job(
        self, job_id, *, state, result=None, runner_image_id=None,
        cleanup_state="complete", cleanup_error=None,
    ):
        if state not in {"succeeded", "failed", "timed_out", "cancelled"}:
            raise ValueError("invalid terminal PoC state")
        now = datetime.now()
        with self._session() as session:
            finished = session.execute(update(PocJob).where(
                PocJob.id == job_id, PocJob.state.in_(("queued", "running")),
            ).values(state=PocJob.state))
            if finished.rowcount != 1:
                return False
            row = session.get(PocJob, job_id)
            if row.cancel_requested and cleanup_state in {"complete", "not_started"}:
                state = "cancelled"
                result = {**(result or {}), "success": False, "cancelled": True}
            row.state = state
            row.result = encrypt_secret(json.dumps(result, sort_keys=True)) if result else None
            row.runner_image_id = runner_image_id or row.runner_image_id
            row.cleanup_state = cleanup_state
            row.cleanup_error = cleanup_error
            if cleanup_state in {"complete", "not_started"}:
                row.active_arena_slot = None
                row.active_global_slot = None
            row.updated_at = now
            row.completed_at = now
            session.commit()
            final_cleanup = row.cleanup_state
            started = row.started_at
        if final_cleanup == "not_started" or started is None:
            self.settle_budget_action(job_id, outcome="released")
        else:
            self.settle_budget_action(job_id, outcome="spent")
        return True

    def recover_stale_poc_jobs(self, stale_before):
        """Never replay possibly side-effecting work after worker loss."""
        now = datetime.now()
        recovered = []
        with self._session() as session:
            ids = list(session.scalars(select(PocJob.id).where(
                PocJob.state == "running", PocJob.updated_at < stale_before,
            )))
            for job_id in ids:
                changed = session.execute(update(PocJob).where(
                    PocJob.id == job_id, PocJob.state == "running",
                    PocJob.updated_at < stale_before,
                ).values(state="failed", result=encrypt_secret(json.dumps({
                    "error": "worker claim became stale; execution was not replayed"
                })), cleanup_state="reconcile_pending", updated_at=now, completed_at=now))
                if changed.rowcount == 1:
                    recovered.append(job_id)
            session.commit()
        for job_id in recovered:
            self.settle_budget_action(job_id, outcome="unknown")
        return recovered

    def reconcile_poc_budget_actions(self):
        """Close a lost settlement after a terminal job without replaying work."""
        with self._session() as session:
            actions = list(session.scalars(select(BudgetAction).where(
                BudgetAction.kind == "poc", BudgetAction.state == "reserved")))
            obligations = []
            for action in actions:
                job = session.get(PocJob, action.id)
                if job and job.state not in {"queued", "running"}:
                    outcome = "released" if job.cleanup_state == "not_started" or job.started_at is None else "unknown"
                    obligations.append((action.id, outcome))
        for action_id, outcome in obligations:
            self.settle_budget_action(action_id, outcome=outcome)
        return len(obligations)

    def record_poc_cleanup(self, job_id, *, success, error=None):
        """Persist reconciliation separately from the already-terminal outcome."""
        with self._session() as session:
            row = session.get(PocJob, job_id)
            if row is None:
                return False
            row.cleanup_state = "complete" if success else "incomplete"
            row.cleanup_error = error
            if success:
                row.active_arena_slot = None
                row.active_global_slot = None
            row.updated_at = datetime.now()
            session.commit()
            return True

    def list_poc_cleanup_obligations(self):
        """Keep failed reclamation retryable after the execution is terminal."""
        with self._session() as session:
            rows = session.scalars(select(PocJob).where(
                PocJob.state.in_(("failed", "succeeded", "timed_out", "cancelled")),
                PocJob.cleanup_state.in_(("incomplete", "reconcile_pending")),
            ))
            return [self._poc_to_dict(row) for row in rows]

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
        out of the fetch window (the 500-event window bug).

        ``limit=None`` is reserved for internal consumers that must process the
        complete append-only history, such as scoring and eval export. Public
        event-feed endpoints continue to impose their own bounded limits.
        """
        with self._session() as session:
            query = select(Event).order_by(Event.id.desc())
            if lab_id is not None:
                query = query.where(Event.lab_id == lab_id)
            if types is not None:
                query = query.where(Event.type.in_(list(types)))
            if limit is not None:
                query = query.limit(limit)
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
            "base_url": row.base_url,  # non-secret (P3-4)
            "status": row.status,
            "updated_at": _stringify(row.updated_at),
        }

    def upsert_model_connection(self, owner, provider, model, api_key, base_url=None,
                                keep_key=False):
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
            row.base_url = (base_url or "").strip() or None
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
                "base_url": row.base_url,
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
