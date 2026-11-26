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
import hashlib
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from timeutil import db_now
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from crypto import decrypt_secret, encrypt_secret
import setup_phase
import otlp
import streams
from model_headers import extra_headers_digest, normalize_extra_headers
from models import (
    AgentBuild, ApiKey, Base, BudgetAccount, BudgetAction, BudgetControl, BudgetGate,
    CopilotChat, CopilotMessage, Deployment,
    EvalChallenge, EvalRun, EvalSuite, EvalTrial, Evaluation, Event,
    ForwardLease, LifecycleRecipe, ModelConnection, PocJob,
    ResetOperation, Span,
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


# F1: an arena time-box extension is an audited lifecycle event; only arenas that
# still have (or are getting) infrastructure can be extended.
ARENA_EXTENDED_EVENT = "arena_extended"
EXTENDABLE_STATES = (LabStatus.PENDING, LabStatus.DEPLOYING, LabStatus.ACTIVE)


# F4: audit trail of agent self-deploys (lab_id = the new arena) and the runtime
# kill switch (lab_id = "system"; the newest event decides).
AGENT_DEPLOY_EVENT = "agent_deploy"
AGENT_DEPLOY_KILL_EVENT = "agent_deploy_kill_switch"


class AgentDeployRefused(ValueError):
    """An agent deploy was refused by quota; ``code`` is a stable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ExtendRefused(ValueError):
    """A time-box extension was refused; ``code`` is a stable machine reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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

    def ping(self) -> None:
        """FR-07 readiness: one round trip to the database (raises on failure)."""
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))

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
        streams.install()  # OBS-04: publish event/span inserts after commit
        # FR-01 (B10, U4): `create_all` only creates missing tables, never missing
        # columns, so on a deployed database it masked schema drift. On PostgreSQL
        # outside mock mode the schema is owned by the `migrate` step and a
        # revision other than head refuses to start. SQLite (dev, tests, the
        # mock demo) keeps the idempotent bootstrap.
        import migrate  # noqa: PLC0415

        if migrate.schema_check_required(url):
            migrate.check_schema_head(self._engine)
        else:
            Base.metadata.create_all(self._engine)
        with self._session() as session:
            if session.get(BudgetGate, "system") is None:
                session.add(BudgetGate(scope="system", account_scope=None, epoch=0,
                                       state="open", updated_at=db_now()))
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
                ts=db_now(),
                actor=actor,
                type=type_,
                payload=json.dumps(payload) if payload is not None else None,
            )
        )

    # --- durable evaluations -------------------------------------------------

    @staticmethod
    def _eval_dict(row):
        if row is None:
            return None
        data = {c.name: _stringify(getattr(row, c.name)) for c in row.__table__.columns}
        for key in ("config", "challenge_ids", "seeds", "result"):
            if key in data and data[key] is not None:
                data[key] = json.loads(data[key])
        return data

    def create_agent_build(self, *, name, version, digest, driver, config):
        with self._session() as session:
            row = AgentBuild(id=str(uuid.uuid4()), name=name, version=version,
                             digest=digest, driver=driver,
                             config=json.dumps(config, sort_keys=True), created_at=db_now())
            session.add(row)
            session.commit()
            return self._eval_dict(row)

    def list_agent_builds(self):
        with self._session() as session:
            return [self._eval_dict(r) for r in session.scalars(
                select(AgentBuild).order_by(AgentBuild.created_at.desc())).all()]

    def get_agent_build(self, build_id):
        with self._session() as session:
            return self._eval_dict(session.get(AgentBuild, build_id))

    def create_eval_challenge(self, *, name, version, scenario, source_arena_id, recipe_digest,
                              validator_version, label):
        with self._session() as session:
            row = EvalChallenge(id=str(uuid.uuid4()), name=name, version=version,
                scenario=scenario, source_arena_id=source_arena_id, recipe_digest=recipe_digest,
                validator_version=validator_version, label=label,
                created_at=db_now())
            session.add(row)
            session.commit()
            return self._eval_dict(row)

    def list_eval_challenges(self):
        with self._session() as session:
            return [self._eval_dict(r) for r in session.scalars(
                select(EvalChallenge).order_by(EvalChallenge.created_at.desc())).all()]

    def get_eval_challenge(self, challenge_id):
        with self._session() as session:
            return self._eval_dict(session.get(EvalChallenge, challenge_id))

    def create_eval_suite(self, *, name, version, challenge_ids, seeds,
                          action_cap, deadline_seconds):
        with self._session() as session:
            row = EvalSuite(id=str(uuid.uuid4()), name=name, version=version,
                challenge_ids=json.dumps(challenge_ids), seeds=json.dumps(seeds),
                action_cap=action_cap, deadline_seconds=deadline_seconds,
                created_at=db_now())
            session.add(row)
            session.commit()
            return self._eval_dict(row)

    def list_eval_suites(self):
        with self._session() as session:
            return [self._eval_dict(r) for r in session.scalars(
                select(EvalSuite).order_by(EvalSuite.created_at.desc())).all()]

    def get_eval_suite(self, suite_id):
        with self._session() as session:
            return self._eval_dict(session.get(EvalSuite, suite_id))

    def create_evaluation(self, *, suite_id, baseline_id, candidate_id):
        now = db_now()
        with self._session() as session:
            suite = session.get(EvalSuite, suite_id)
            if suite is None or session.get(AgentBuild, baseline_id) is None or session.get(
                    AgentBuild, candidate_id) is None:
                raise ValueError("suite or agent build not found")
            eid = str(uuid.uuid4())
            evaluation = Evaluation(id=eid, suite_id=suite_id, baseline_id=baseline_id,
                                    candidate_id=candidate_id, state="queued",
                                    created_at=now, updated_at=now)
            session.add(evaluation)
            for challenge_id in json.loads(suite.challenge_ids):
                if session.get(EvalChallenge, challenge_id) is None:
                    raise ValueError("challenge not found")
                for side, build_id in (("baseline", baseline_id), ("candidate", candidate_id)):
                    run_id = str(uuid.uuid4())
                    session.add(EvalRun(id=run_id, evaluation_id=eid, build_id=build_id,
                                        challenge_id=challenge_id, side=side))
                    for seed in json.loads(suite.seeds):
                        session.add(EvalTrial(id=str(uuid.uuid4()), run_id=run_id,
                                              evaluation_id=eid, seed=seed, state="queued",
                                              updated_at=now))
            session.commit()
            return self._eval_dict(evaluation)

    def create_eval_smoke(self, *, challenge_id, build_id, seed, action_cap, deadline_seconds):
        """One durable calibration trial; no paired comparison is implied."""
        now = db_now()
        with self._session() as session:
            challenge = session.get(EvalChallenge, challenge_id)
            build = session.get(AgentBuild, build_id)
            if challenge is None or build is None or challenge.label != "calibration":
                raise ValueError("calibration challenge or agent build not found")
            if build.driver != "model-mcp/v1":
                raise ValueError("smoke requires a model-driven build")
            suite_id = str(uuid.uuid4())
            eid = str(uuid.uuid4())
            run_id = str(uuid.uuid4())
            session.add(EvalSuite(id=suite_id, name="single-trial model smoke",
                version="v1", challenge_ids=json.dumps([challenge_id]),
                seeds=json.dumps([seed]), action_cap=action_cap,
                deadline_seconds=deadline_seconds, created_at=now))
            session.add(Evaluation(id=eid, suite_id=suite_id, baseline_id=build_id,
                candidate_id=build_id, state="queued", created_at=now, updated_at=now))
            session.add(EvalRun(id=run_id, evaluation_id=eid, build_id=build_id,
                challenge_id=challenge_id, side="smoke"))
            session.add(EvalTrial(id=str(uuid.uuid4()), run_id=run_id,
                evaluation_id=eid, seed=seed, state="queued", updated_at=now))
            session.commit()
            return self._eval_dict(session.get(Evaluation, eid))

    def list_evaluations(self):
        with self._session() as session:
            return [self._eval_dict(r) for r in session.scalars(
                select(Evaluation).order_by(Evaluation.created_at.desc())).all()]

    def get_evaluation(self, evaluation_id):
        with self._session() as session:
            evaluation = session.get(Evaluation, evaluation_id)
            if evaluation is None:
                return None
            runs = session.scalars(select(EvalRun).where(EvalRun.evaluation_id == evaluation_id)).all()
            trials = session.scalars(select(EvalTrial).where(
                EvalTrial.evaluation_id == evaluation_id)).all()
            data = self._eval_dict(evaluation)
            data["runs"] = [self._eval_dict(r) for r in runs]
            data["trials"] = [self._eval_dict(t) for t in trials]
            challenge_ids = {run.challenge_id for run in runs}
            data["challenges"] = [self._eval_dict(row) for row in session.scalars(
                select(EvalChallenge).where(EvalChallenge.id.in_(challenge_ids))).all()]
            return data

    def evaluation_ids_for_suite(self, suite_id, limit=200):
        """UX-11 history: a suite's evaluations, newest first."""
        with self._session() as session:
            return list(session.scalars(select(Evaluation.id).where(
                Evaluation.suite_id == suite_id).order_by(
                Evaluation.created_at.desc()).limit(limit)).all())

    def spans_for_arenas(self, arena_ids, kinds=("tool", "model"), limit=20000):
        """Spans of several arenas grouped by arena, oldest first (UX-11/12)."""
        ids = sorted({a for a in arena_ids if a})
        out = {arena_id: [] for arena_id in ids}
        if not ids:
            return out
        query = (select(Span).where(Span.arena_id.in_(ids), Span.kind.in_(tuple(kinds)))
                 .order_by(Span.id).limit(limit))
        with self._session() as session:
            for row in session.scalars(query).all():
                out[row.arena_id].append(self._span_dict(row))
        return out

    def get_eval_challenge_for_arena(self, arena_id):
        with self._session() as session:
            trial = session.scalar(select(EvalTrial).where(EvalTrial.arena_id == arena_id))
            if trial is None:
                return None
            run = session.get(EvalRun, trial.run_id)
            return self._eval_dict(session.get(EvalChallenge, run.challenge_id)) if run else None

    @staticmethod
    def _eval_heartbeat(session, trial_id, now):
        """Trial progress is evaluation progress: stale recovery keys on this, so a
        long suite that keeps finishing trials is never mistaken for a lost worker."""
        session.execute(update(Evaluation).where(
            Evaluation.id == select(EvalTrial.evaluation_id).where(
                EvalTrial.id == trial_id).scalar_subquery(),
            Evaluation.state == "running").values(updated_at=now))

    @staticmethod
    def _touch_trial(session, trial_id):
        """UX-11: a trial's state change is a change of its evaluation's stream."""
        import streams  # noqa: PLC0415

        streams.touch_evaluation(session, session.scalar(
            select(EvalTrial.evaluation_id).where(EvalTrial.id == trial_id)))

    def claim_eval_trial(self, trial_id, claim):
        now = db_now()
        with self._session() as session:
            result = session.execute(update(EvalTrial).where(
                EvalTrial.id == trial_id, EvalTrial.state == "queued")
                .values(state="running", worker_claim=claim, updated_at=now))
            if result.rowcount == 1:
                self._eval_heartbeat(session, trial_id, now)
                self._touch_trial(session, trial_id)
            session.commit()
            return result.rowcount == 1

    def assign_eval_trial_arena(self, trial_id, claim, arena_id):
        with self._session() as session:
            changed = session.execute(update(EvalTrial).where(
                EvalTrial.id == trial_id, EvalTrial.worker_claim == claim,
                EvalTrial.state == "running", EvalTrial.arena_id.is_(None))
                .values(arena_id=arena_id, updated_at=db_now())).rowcount
            if changed == 1:
                self._touch_trial(session, trial_id)
            session.commit()
            return changed == 1

    def set_evaluation_state(self, evaluation_id, state, *, expected=None):
        with self._session() as session:
            stmt = update(Evaluation).where(Evaluation.id == evaluation_id)
            if expected is not None:
                stmt = stmt.where(Evaluation.state == expected)
            changed = session.execute(stmt.values(state=state, updated_at=db_now())).rowcount
            if changed == 1:
                import streams  # noqa: PLC0415

                streams.touch_evaluation(session, evaluation_id)
            session.commit()
            return changed == 1

    def configure_eval_budget(self, arena_id, *, action_cap, deadline):
        with self._session() as session:
            account = session.get(BudgetAccount, arena_id)
            if account is None or account.spent or account.reserved:
                raise ValueError("evaluation budget must be set before trial activity")
            account.action_cap = action_cap
            account.deadline = deadline
            session.commit()

    def terminalize_unfinished_eval_trials(self, evaluation_id, *, error):
        """Close every trial the worker can no longer run as infrastructure failure,
        never as agent failure."""
        with self._session() as session:
            changed = session.execute(update(EvalTrial).where(
                EvalTrial.evaluation_id == evaluation_id,
                EvalTrial.state.in_(("running", "queued")))
                .values(state="infrastructure_failure", error=error,
                        updated_at=db_now())).rowcount
            if changed:
                import streams  # noqa: PLC0415

                streams.touch_evaluation(session, evaluation_id)
            session.commit()
            return changed

    def recover_stale_evaluations(self, before):
        """Terminalize evaluations whose worker made no trial progress since ``before``."""
        with self._session() as session:
            rows = session.scalars(select(Evaluation).where(
                Evaluation.state == "running", Evaluation.updated_at < before)).all()
            ids = [row.id for row in rows]
            for row in rows:
                session.execute(update(EvalTrial).where(
                    EvalTrial.evaluation_id == row.id,
                    EvalTrial.state.in_(("running", "queued"))).values(
                        state="infrastructure_failure", error="worker_interrupted",
                        updated_at=db_now()))
                row.state = "complete"
                row.updated_at = db_now()
            session.commit()
            return ids

    def queued_evaluations_before(self, before):
        with self._session() as session:
            return [row.id for row in session.scalars(select(Evaluation).where(
                Evaluation.state == "queued", Evaluation.created_at < before)).all()]

    def finish_eval_trial(self, trial_id, claim, *, state, arena_id=None,
                          starting_digest=None, result=None, error=None):
        if state not in ("completed", "infrastructure_failure", "agent_failure"):
            raise ValueError("invalid terminal trial state")
        with self._session() as session:
            now = db_now()
            changed = session.execute(update(EvalTrial).where(
                EvalTrial.id == trial_id, EvalTrial.worker_claim == claim,
                EvalTrial.state == "running").values(
                    state=state, starting_digest=starting_digest,
                    result=json.dumps(result) if result is not None else None,
                    error=error, updated_at=now)).rowcount
            if changed == 1:
                self._eval_heartbeat(session, trial_id, now)
                self._touch_trial(session, trial_id)
            session.commit()
            return changed == 1

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
                    created_at=db_now(),
                    updated_at=db_now(),
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
            deadline = expires_at or db_now() + timedelta(days=365)
            cap = max(1, min(int(os.getenv("ARENA_ACTION_BUDGET", "1000")), 100000))
            session.add(BudgetAccount(
                arena_id=deployment_id, scope_id=deployment_id, version=1,
                action_cap=cap, spent=0, reserved=0, deadline=deadline,
                created_at=db_now(),
            ))
            session.add(BudgetGate(scope=deployment_id, account_scope=deployment_id,
                                   epoch=0, state="open", updated_at=db_now()))
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

    @staticmethod
    def _forward_dict(row):
        if row is None:
            return None
        return {
            "id": row.id, "arena_id": row.arena_id,
            "principal": row.principal, "principal_role": row.principal_role,
            "binding_generation": row.binding_generation,
            "foothold": row.foothold, "target": row.target,
            "service_id": row.service_id, "segment": row.segment, "port": row.port,
            "expires_at": _stringify(row.expires_at), "state": row.state,
            "stream_id": row.stream_id, "bytes_in": row.bytes_in,
            "bytes_out": row.bytes_out, "cleanup_state": row.cleanup_state,
            "cleanup_error": row.cleanup_error,
            "created_at": _stringify(row.created_at),
            "updated_at": _stringify(row.updated_at),
        }

    def create_forward_lease(self, arena_id, *, principal, role, binding_generation,
                             key, digest, foothold, target, service_id, segment, port,
                             lifetime_seconds):
        """Serialize creation with stop and idempotency, including across PG writers."""
        with self._session() as session:
            system = self._lock_gate(session, "system")
            gate = self._lock_gate(session, arena_id)
            existing = session.scalar(select(ForwardLease).where(
                ForwardLease.arena_id == arena_id,
                ForwardLease.idempotency_key == key))
            if existing:
                if (existing.principal, existing.request_digest,
                        existing.binding_generation) != (
                            principal, digest, binding_generation):
                    raise ValueError("forward idempotency key was reused with different input")
                return self._forward_dict(existing)
            dep = session.get(Deployment, arena_id)
            account = self._lock_account(session, gate.account_scope) if gate else None
            now = db_now()
            if (system is None or system.state != "open" or gate is None
                    or gate.state != "open" or dep is None or dep.status != LabStatus.ACTIVE
                    or account is None or account.deadline <= now):
                raise ValueError("arena, stop gate or durable budget is not active")
            expiry = min(now + timedelta(seconds=lifetime_seconds), account.deadline)
            if dep.expires_at:
                expiry = min(expiry, dep.expires_at)
            if expiry <= now:
                raise ValueError("forward lifetime has expired")
            if account.spent + account.reserved >= account.action_cap:
                raise ValueError("action budget exhausted")
            account.spent += 1
            session.add(BudgetAction(
                id=str(uuid.uuid4()), arena_id=arena_id, scope_id=account.scope_id,
                action_key="forward:" + hashlib.sha256(key.encode()).hexdigest(),
                input_digest=digest, kind="forward/create", actor=principal,
                state="spent", epoch=gate.epoch, created_at=now, updated_at=now,
            ))
            row = ForwardLease(
                id=str(uuid.uuid4()), arena_id=arena_id, principal=principal,
                principal_role=role, binding_generation=binding_generation,
                idempotency_key=key, request_digest=digest,
                foothold=foothold, target=target, service_id=service_id,
                segment=segment,
                port=port, expires_at=expiry, state="open", stream_id=None,
                worker_claim=None,
                bytes_in=0, bytes_out=0, cleanup_state="complete",
                created_at=now, updated_at=now,
            )
            session.add(row)
            self._append_event(session, arena_id, principal, "forward_opened", {
                "forward_id": row.id, "foothold": foothold, "target": target,
                "service_id": service_id, "expires_at": _stringify(expiry),
            })
            session.commit()
            return self._forward_dict(row)

    def get_forward_lease(self, forward_id):
        with self._session() as session:
            return self._forward_dict(session.get(ForwardLease, forward_id))

    def list_forward_leases(self, arena_id):
        with self._session() as session:
            rows = session.scalars(select(ForwardLease).where(
                ForwardLease.arena_id == arena_id).order_by(ForwardLease.created_at.desc()))
            return [self._forward_dict(row) for row in rows]

    def claim_forward_stream(self, forward_id, *, principal, binding_generation):
        with self._session() as session:
            system = self._lock_gate(session, "system")
            row = session.get(ForwardLease, forward_id)
            gate = self._lock_gate(session, row.arena_id) if row else None
            account = session.get(BudgetAccount, gate.account_scope) if gate else None
            dep = session.get(Deployment, row.arena_id) if row else None
            now = db_now()
            if (row is None or row.principal != principal
                    or row.binding_generation != binding_generation):
                raise ValueError("forward is not owned by this binding")
            if (row.state != "open" or row.expires_at <= now
                    or system is None or system.state != "open"
                    or gate is None or gate.state != "open" or account is None
                    or account.deadline <= now or dep is None
                    or dep.status != LabStatus.ACTIVE):
                raise ValueError("forward is unavailable or expired")
            row.stream_id = str(uuid.uuid4())
            row.state = "connecting"
            row.cleanup_state = "pending"
            row.updated_at = now
            self._append_event(session, row.arena_id, principal, "forward_connected", {
                "forward_id": row.id, "stream_id": row.stream_id,
            })
            session.commit()
            return self._forward_dict(row)

    @contextmanager
    def forward_start_guard(self, forward_id):
        """A helper create/start cannot straddle a committed stop."""
        with self._session() as session:
            system = self._lock_gate(session, "system")
            row = session.get(ForwardLease, forward_id)
            gate = self._lock_gate(session, row.arena_id) if row else None
            dep = session.get(Deployment, row.arena_id) if row else None
            if (system is None or system.state != "open" or gate is None
                    or gate.state != "open" or row is None
                    or row.state != "connecting" or row.expires_at <= db_now()
                    or dep is None or dep.status != LabStatus.ACTIVE):
                raise ValueError("forward helper start was cancelled or stopped")
            yield
            session.commit()

    def claim_forward_worker(self, forward_id, claim):
        with self._session() as session:
            row = session.get(ForwardLease, forward_id)
            if row is None:
                return False
            session.execute(update(ForwardLease).where(ForwardLease.id == forward_id)
                            .values(updated_at=ForwardLease.updated_at))
            session.refresh(row)
            if row.state != "connecting" or row.worker_claim is not None:
                return False
            row.worker_claim = claim
            row.updated_at = db_now()
            session.commit()
            return True

    def forward_stream_valid(self, forward_id):
        with self._session() as session:
            row = session.get(ForwardLease, forward_id)
            if row is None or row.state != "connecting" or row.expires_at <= db_now():
                return False
            system = session.get(BudgetGate, "system")
            gate = session.get(BudgetGate, row.arena_id)
            dep = session.get(Deployment, row.arena_id)
            return bool(system and system.state == "open" and gate
                        and gate.state == "open" and dep and dep.status == LabStatus.ACTIVE)

    def heartbeat_forward_stream(self, forward_id):
        with self._session() as session:
            row = session.get(ForwardLease, forward_id)
            if row is None or row.state != "connecting":
                return False
            row.updated_at = db_now()
            session.commit()
            return True

    def finish_forward_stream(self, forward_id, *, bytes_in=0, bytes_out=0,
                              cleanup_complete=True, error=None):
        with self._session() as session:
            row = session.get(ForwardLease, forward_id)
            if row is None:
                return
            if row.state == "connecting":
                row.state = "closed"
            row.bytes_in = max(row.bytes_in, bytes_in)
            row.bytes_out = max(row.bytes_out, bytes_out)
            row.cleanup_state = "complete" if cleanup_complete else "incomplete"
            row.cleanup_error = error[:500] if error else None
            row.updated_at = db_now()
            self._append_event(session, row.arena_id, row.principal, "forward_closed", {
                "forward_id": forward_id, "bytes_in": row.bytes_in,
                "bytes_out": row.bytes_out, "cleanup_state": row.cleanup_state,
            })
            session.commit()

    def revoke_forward_lease(self, forward_id, *, actor, reason="operator"):
        with self._session() as session:
            row = session.get(ForwardLease, forward_id)
            if row is None:
                return None
            self._lock_gate(session, "system")
            self._lock_gate(session, row.arena_id)
            if row.state in {"open", "connecting"}:
                row.state = "revoked"
                row.updated_at = db_now()
                self._append_event(session, row.arena_id, actor, "forward_revoked", {
                    "forward_id": row.id, "reason": reason,
                })
                session.commit()
            return self._forward_dict(row)

    def revoke_arena_forwards(self, arena_id, *, actor, reason):
        for row in self.list_forward_leases(arena_id):
            if row["state"] in {"open", "connecting"}:
                self.revoke_forward_lease(row["id"], actor=actor, reason=reason)

    def stale_forward_leases(self, now, stale_before):
        with self._session() as session:
            rows = session.scalars(select(ForwardLease).where(
                (ForwardLease.state.in_(("open", "connecting")) |
                 (ForwardLease.cleanup_state != "complete"))))
            return [self._forward_dict(row) for row in rows
                    if (row.expires_at <= now or
                        (row.state == "connecting" and row.updated_at <= stale_before)
                        or row.cleanup_state == "incomplete"
                        or (row.state in {"revoked", "closed"}
                            and row.cleanup_state == "pending"))]

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

    def extend_arena(self, arena_id, *, seconds, actor, max_lifetime_seconds,
                     key=None, require_open_gate=False):
        """F1: move an arena's time box forward by ``seconds``.

        The TTL (``deployments.expires_at``, the reaper's signal) and the durable
        budget deadline move together, each from ``max(now, current)``, so a
        tighter operator budget deadline keeps its offset and never exceeds the
        TTL. One serialized step under the arena gate lock; an optional
        ``key`` makes a retry replay the first result instead of extending
        twice. ``require_open_gate`` (agent callers) refuses while a stop holds:
        an agent never prolongs a stopped arena. Raises ``ExtendRefused``.
        """
        now = db_now()
        with self._session() as session:
            system = self._lock_gate(session, "system")
            gate = self._lock_gate(session, arena_id)
            dep = session.get(Deployment, arena_id)
            if dep is None:
                raise ExtendRefused("arena_not_found", "arena not found")
            if key is not None:
                row = session.get(BudgetControl, (arena_id, key))
                if row is not None:
                    if (row.command, row.actor, row.reason) != ("extend", actor, str(seconds)):
                        raise ExtendRefused("idempotency_key_reused",
                                            "extension key was reused with different input")
                    prior = session.scalars(select(Event).where(
                        Event.lab_id == arena_id, Event.type == ARENA_EXTENDED_EVENT,
                    ).order_by(Event.id.desc())).all()
                    for event in prior:
                        payload = json.loads(event.payload or "{}")
                        if payload.get("idempotency_key") == key:
                            return {**payload, "replayed": True}
                    raise ExtendRefused("idempotency_key_reused", "extension record missing")
            if dep.status not in EXTENDABLE_STATES:
                raise ExtendRefused("arena_not_extendable",
                                    f"arena is {dep.status}; only live arenas can be extended")
            if gate is None:
                raise ExtendRefused("legacy_budget_unavailable",
                                    "legacy arena has no durable budget policy")
            if require_open_gate and (system.state != "open" or gate.state != "open"):
                raise ExtendRefused("stop_active",
                                    "a stop is active; an operator must resume first")
            account = self._lock_account(session, gate.account_scope)
            delta = timedelta(seconds=seconds)
            previous_expires, previous_deadline = dep.expires_at, account.deadline
            new_expires = None
            if dep.expires_at is not None:
                new_expires = max(now, dep.expires_at) + delta
                born = dep.created_at or now
                if new_expires - born > timedelta(seconds=max_lifetime_seconds):
                    raise ExtendRefused(
                        "max_lifetime_exceeded",
                        f"extension would exceed the {max_lifetime_seconds}s arena lifetime cap")
            new_deadline = max(now, account.deadline) + delta
            if new_expires is not None:
                new_deadline = min(new_deadline, new_expires)
            dep.expires_at = new_expires
            account.deadline = new_deadline
            account.version += 1
            result = {
                "category": "lifecycle", "action": "extended",
                "seconds": seconds,
                "previous_expires_at": _stringify(previous_expires),
                "expires_at": _stringify(new_expires),
                "previous_deadline": _stringify(previous_deadline),
                "deadline": _stringify(new_deadline),
                "budget_version": account.version,
                "idempotency_key": key,
            }
            self._append_event(session, arena_id, actor, ARENA_EXTENDED_EVENT, result)
            if key is not None:
                session.add(BudgetControl(scope=arena_id, idempotency_key=key,
                                          command="extend", actor=actor,
                                          reason=str(seconds), epoch=gate.epoch,
                                          created_at=now))
            session.commit()
            return {**result, "replayed": False}

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
            if deadline <= db_now() or (dep.expires_at and deadline > dep.expires_at):
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
        now = db_now()
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
            action.updated_at = db_now()
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
                gate.updated_at = db_now()
                self._append_event(session, scope, actor, "arena_stop" if scope != "system" else "system_stop",
                                   {"epoch": gate.epoch, "reason": reason})
            session.add(BudgetControl(scope=scope, idempotency_key=key,
                                      command="stop", actor=actor, reason=reason,
                                      epoch=gate.epoch, created_at=db_now()))
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
            active_forwards = session.scalar(select(ForwardLease.id).where(
                ForwardLease.arena_id.in_(scopes), ForwardLease.stream_id.is_not(None),
                ForwardLease.cleanup_state != "complete").limit(1))
            if active_actions or active_jobs or active_forwards:
                return False
            gate.state = "stopped"
            gate.updated_at = db_now()
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
            if account and account.deadline <= db_now():
                raise ValueError("wall-clock budget has expired")
            gate.state = "open"
            gate.epoch += 1
            gate.reason = reason
            gate.updated_at = db_now()
            self._append_event(session, scope, actor, "stop_cleared",
                               {"epoch": gate.epoch, "reason": reason})
            session.add(BudgetControl(scope=scope, idempotency_key=key,
                                      command="resume", actor=actor, reason=reason,
                                      epoch=gate.epoch, created_at=db_now()))
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
            now = db_now()
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
            dep.updated_at = db_now()
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
                .values(status=new, updated_at=db_now())
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
                    created_at=db_now(),
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
        now = db_now()
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
            row.updated_at = db_now()
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
                    updated_at=db_now(),
                )
            )
            session.commit()
            return result.rowcount == 1

    def recover_stale_reset_operations(self, stale_before):
        """Return stale running operations to pending so the reaper can resume them."""
        now = db_now()
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
        now = db_now()
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
        now = db_now()
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
        now = db_now()
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
        now = db_now()
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
        now = db_now()
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
            row.updated_at = db_now()
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
            if self._record_has_evidence(session, deployment_id):
                raise ValueError("research evidence or evaluation references require retaining this record")
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
            removed = 0
            for dep in rows:
                if self._record_has_evidence(session, dep.id):
                    continue
                self._append_event(
                    session, dep.id, actor, "record_deleted", {"status": dep.status}
                )
                session.delete(dep)
                removed += 1
            session.commit()
            return removed

    @staticmethod
    def _record_has_evidence(session, deployment_id):
        if session.scalar(select(Event.id).where(
            Event.lab_id == deployment_id,
            Event.type.notin_(("created", "status", "record_deleted")),
        ).limit(1)) is not None:
            return True
        if session.scalar(select(EvalChallenge.id).where(
            EvalChallenge.source_arena_id == deployment_id).limit(1)) is not None:
            return True
        return session.scalar(select(EvalTrial.id).where(
            EvalTrial.arena_id == deployment_id).limit(1)) is not None

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

    # --- spans (ADR-0018, OBS-01) ------------------------------------------

    def insert_span(self, row: dict) -> int:
        """Insert one prepared span row (see ``spans.build``); returns its id."""
        with self._session() as session:
            span = Span(**row)
            session.add(span)
            session.commit()
            otlp.export(row)  # OBS-07: optional, off unless configured
            return span.id

    def list_spans(self, *, arena_id=None, trace_id=None, trial_id=None,
                   visibility=None, after_id=None, limit=500):
        """Spans oldest-first by id. ``visibility`` restricts to those values."""
        query = select(Span)
        if arena_id is not None:
            query = query.where(Span.arena_id == arena_id)
        if trace_id is not None:
            query = query.where(Span.trace_id == trace_id)
        if trial_id is not None:
            query = query.where(Span.trial_id == trial_id)
        if visibility is not None:
            query = query.where(Span.visibility.in_(tuple(visibility)))
        if after_id is not None:
            query = query.where(Span.id > after_id)
        query = query.order_by(Span.id).limit(max(1, min(int(limit), 5000)))
        with self._session() as session:
            return [self._span_dict(row) for row in session.scalars(query).all()]

    def activity_rows(self, *, arena_id=None, since=None, kinds=("tool", "model")):
        """UX-17: the columns an activity summary needs, for an arena or for
        every arena since ``since``. Operator material: callers gate access."""
        query = select(Span.kind, Span.name, Span.status, Span.actor, Span.arena_id,
                       Span.started_at, Span.duration_ms, Span.attrs
                       ).where(Span.kind.in_(tuple(kinds)))
        if arena_id is not None:
            query = query.where(Span.arena_id == arena_id)
        if since is not None:
            query = query.where(Span.started_at >= since)
        with self._session() as session:
            return [tuple(row) for row in session.execute(query.order_by(Span.id)).all()]

    def recent_action_spans(self, arena_id, *, limit=8, kinds=("tool", "model")):
        """UX-17: the newest action spans of an arena, newest first."""
        query = (select(Span).where(Span.arena_id == arena_id, Span.kind.in_(tuple(kinds)))
                 .order_by(Span.started_at.desc(), Span.id.desc())
                 .limit(max(1, min(int(limit), 50))))
        with self._session() as session:
            return [self._span_dict(row) for row in session.scalars(query).all()]

    def last_span_end(self, arena_id):
        """When the arena's last recorded span ended (or started), or None."""
        with self._session() as session:
            row = session.execute(
                select(func.max(func.coalesce(Span.ended_at, Span.started_at)))
                .where(Span.arena_id == arena_id)).scalar()
            return row

    # --- Copilot chats (ADR-0020): owner-scoped; callers pass the principal name.
    COPILOT_MESSAGE_LIMIT = 200

    @staticmethod
    def _copilot_message(row) -> dict:
        try:
            data = json.loads(row.data) if row.data else None
        except ValueError:
            data = None
        return {"id": row.id, "role": row.role, "text": row.text, "data": data,
                "created_at": _stringify(row.created_at)}

    def copilot_create_chat(self, owner: str, title: str) -> dict:
        now = db_now()
        chat = CopilotChat(id=uuid.uuid4().hex[:16], owner=owner,
                           title=(title or "New chat")[:120], created_at=now, updated_at=now)
        with self._session() as session:
            session.add(chat)
            session.commit()
            return {"id": chat.id, "title": chat.title,
                    "created_at": _stringify(now), "updated_at": _stringify(now)}

    def copilot_list_chats(self, owner: str, limit: int = 50) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(select(CopilotChat).where(CopilotChat.owner == owner)
                                   .order_by(CopilotChat.updated_at.desc())
                                   .limit(max(1, min(limit, 200)))).all()
            return [{"id": r.id, "title": r.title, "created_at": _stringify(r.created_at),
                     "updated_at": _stringify(r.updated_at)} for r in rows]

    def copilot_get_chat(self, owner: str, chat_id: str) -> dict | None:
        """The chat and its messages, or None when it is not this owner's."""
        with self._session() as session:
            chat = session.get(CopilotChat, chat_id)
            if chat is None or chat.owner != owner:
                return None
            messages = session.scalars(select(CopilotMessage)
                                       .where(CopilotMessage.chat_id == chat_id)
                                       .order_by(CopilotMessage.id)).all()
            return {"id": chat.id, "title": chat.title,
                    "created_at": _stringify(chat.created_at),
                    "updated_at": _stringify(chat.updated_at),
                    "messages": [self._copilot_message(m) for m in messages]}

    def copilot_add_message(self, owner: str, chat_id: str, role: str,
                            text: str | None = None, data: dict | None = None) -> dict | None:
        """Append a message to the owner's chat; None when the chat is not
        theirs or is full."""
        with self._session() as session:
            chat = session.get(CopilotChat, chat_id)
            if chat is None or chat.owner != owner:
                return None
            count = session.scalar(select(func.count()).select_from(CopilotMessage)
                                   .where(CopilotMessage.chat_id == chat_id))
            if count >= self.COPILOT_MESSAGE_LIMIT:
                return None
            now = db_now()
            row = CopilotMessage(chat_id=chat_id, role=role,
                                 text=(text or "")[:20000] if text is not None else None,
                                 data=json.dumps(data, default=str) if data is not None else None,
                                 created_at=now)
            session.add(row)
            chat.updated_at = now
            session.commit()
            return self._copilot_message(row)

    def copilot_rename_chat(self, owner: str, chat_id: str, title: str) -> bool:
        with self._session() as session:
            chat = session.get(CopilotChat, chat_id)
            if chat is None or chat.owner != owner:
                return False
            chat.title = (title or "New chat")[:120]
            session.commit()
            return True

    def copilot_delete_chat(self, owner: str, chat_id: str) -> bool:
        with self._session() as session:
            chat = session.get(CopilotChat, chat_id)
            if chat is None or chat.owner != owner:
                return False
            session.execute(CopilotMessage.__table__.delete()
                            .where(CopilotMessage.chat_id == chat_id))
            session.delete(chat)
            session.commit()
            return True

    def copilot_decide_proposal(self, owner: str, message_id: int, state: str,
                                detail: str | None = None) -> dict | None:
        """Move a pending proposal to applied, denied or failed (once). None when
        it is not the owner's, not a proposal, or no longer pending."""
        if state not in ("applied", "denied", "failed"):
            return None
        with self._session() as session:
            row = session.get(CopilotMessage, message_id)
            if row is None or row.role != "proposal":
                return None
            chat = session.get(CopilotChat, row.chat_id)
            if chat is None or chat.owner != owner:
                return None
            data = json.loads(row.data or "{}")
            if data.get("state") != "pending":
                return None
            data.update({"state": state, "detail": (detail or "")[:300] or None,
                         "decided_at": _stringify(db_now())})
            row.data = json.dumps(data, default=str)
            session.commit()
            return self._copilot_message(row)

    @staticmethod
    def _span_dict(row) -> dict:
        try:
            attrs = json.loads(row.attrs) if row.attrs else {}
        except ValueError:
            attrs = {}
        return {
            "id": row.id, "span_id": row.span_id, "trace_id": row.trace_id,
            "parent_span_id": row.parent_span_id, "arena_id": row.arena_id,
            "evaluation_id": row.evaluation_id, "trial_id": row.trial_id,
            "actor": row.actor, "actor_kind": row.actor_kind, "stance": row.stance,
            "kind": row.kind, "name": row.name,
            "started_at": _stringify(row.started_at), "ended_at": _stringify(row.ended_at),
            "duration_ms": row.duration_ms, "status": row.status,
            "error_class": row.error_class, "input_digest": row.input_digest,
            "output_digest": row.output_digest, "input_preview": row.input_preview,
            "output_preview": row.output_preview, "attrs": attrs,
            "visibility": row.visibility,
        }

    def record_event(self, lab_id, type, payload=None, actor="system"):
        """Append an audit event directly (e.g. reaper actions)."""
        with self._session() as session:
            self._append_event(session, lab_id, actor, type, payload)
            session.commit()

    def record_event_once(self, lab_id, type, payload=None, actor="system") -> bool:
        """Append an event unless ``lab_id`` already has one of this type.

        Check and insert are one serialized step, so two writers racing for "the"
        outcome of something can never both append: exactly one returns True.
        Order of commit and order of event id therefore cannot disagree.
        """
        with self._session() as session:
            if self._engine.dialect.name == "postgresql":
                # Held until this transaction ends; the check below then sees
                # anything a competing writer committed first.
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                                {"key": f"event-once\x1f{lab_id}\x1f{type}"})
            else:
                # SQLite: a write takes the database lock before the check.
                session.execute(update(BudgetGate).where(BudgetGate.scope == "system")
                                .values(scope="system"))
            exists = session.execute(select(Event.id).where(
                Event.lab_id == lab_id, Event.type == type).limit(1)).first()
            if exists is not None:
                session.rollback()
                return False
            self._append_event(session, lab_id, actor, type, payload)
            session.commit()
            return True

    def guarded_append(self, lock_key, decide):
        """Check-then-append audit events as one serialized step.

        ``decide(read)`` receives ``read(lab_id=None, types=None, scenario=None)``
        returning newest-first event dicts seen under the lock, and returns
        ``(appends, result)`` where ``appends`` is a list of ``(lab_id, actor,
        type, payload)``. An exception from ``decide`` appends nothing. Writers
        sharing ``lock_key`` (PostgreSQL advisory lock) or any writer (SQLite
        database lock) cannot interleave between the check and the append."""
        with self._session() as session:
            if self._engine.dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                                {"key": f"guarded\x1f{lock_key}"})
            else:
                session.execute(update(BudgetGate).where(BudgetGate.scope == "system")
                                .values(scope="system"))

            def read(lab_id=None, types=None, scenario=None):
                query = select(Event).order_by(Event.id.desc())
                if lab_id is not None:
                    query = query.where(Event.lab_id == lab_id)
                if scenario is not None:
                    query = query.where(Event.lab_id.in_(
                        select(Deployment.id).where(Deployment.scenario == scenario)))
                if types is not None:
                    query = query.where(Event.type.in_(list(types)))
                return [{"id": e.id, "lab_id": e.lab_id, "ts": _stringify(e.ts),
                         "actor": e.actor, "type": e.type,
                         "payload": json.loads(e.payload) if e.payload else None}
                        for e in session.scalars(query)]

            appends, result = decide(read)
            for lab_id, actor, type_, payload in appends:
                self._append_event(session, lab_id, actor, type_, payload)
            session.commit()
            return result

    def events_after(self, lab_id, after_id=0, types=None, limit=500):
        """Events of one lab after ``after_id``, oldest first (OBS-04 stream)."""
        with self._session() as session:
            query = select(Event).where(Event.lab_id == lab_id, Event.id > (after_id or 0))
            if types is not None:
                query = query.where(Event.type.in_(list(types)))
            query = query.order_by(Event.id).limit(limit)
            return [{"id": e.id, "lab_id": e.lab_id, "ts": _stringify(e.ts),
                     "actor": e.actor, "type": e.type,
                     "payload": json.loads(e.payload) if e.payload else None}
                    for e in session.scalars(query)]

    def recent_spans(self, arena_id, limit=50):
        """The arena's newest spans, newest first (OBS-06 board)."""
        with self._session() as session:
            query = (select(Span).where(Span.arena_id == arena_id)
                     .order_by(Span.id.desc()).limit(limit))
            return [self._span_dict(row) for row in session.scalars(query)]

    def recent_events_of(self, types, limit=200):
        """Newest events of the given types across all arenas (OBS-06 inbox)."""
        with self._session() as session:
            query = (select(Event).where(Event.type.in_(list(types)))
                     .order_by(Event.id.desc()).limit(limit))
            return [{"id": e.id, "lab_id": e.lab_id, "ts": _stringify(e.ts),
                     "actor": e.actor, "type": e.type,
                     "payload": json.loads(e.payload) if e.payload else None}
                    for e in session.scalars(query)]

    def recent_refusals(self, limit=50):
        """Newest budget-refused spans across arenas (OBS-06 inbox)."""
        with self._session() as session:
            query = (select(Span).where(Span.status == "budget_refused")
                     .order_by(Span.id.desc()).limit(limit))
            return [self._span_dict(row) for row in session.scalars(query)]

    def eval_trials_for_board(self, limit=100):
        """Running trials and the most recently finished ones (OBS-06)."""
        with self._session() as session:
            query = select(EvalTrial).order_by(EvalTrial.updated_at.desc()).limit(limit)
            return [{"id": t.id, "evaluation_id": t.evaluation_id, "run_id": t.run_id,
                     "seed": t.seed, "state": t.state, "arena_id": t.arena_id,
                     "error": t.error, "updated_at": _stringify(t.updated_at)}
                    for t in session.scalars(query)]

    def telemetry_counts(self) -> dict:
        """Database-derived metric families (OBS-07)."""
        with self._session() as session:
            states = dict(session.execute(
                select(Deployment.status, func.count()).group_by(Deployment.status)).all())
            refusals = session.scalar(select(func.count()).select_from(Span)
                                      .where(Span.status == "budget_refused")) or 0
            reaper = dict(session.execute(
                select(Event.type, func.count()).where(Event.actor == "reaper")
                .group_by(Event.type)).all())
            verdicts: dict[str, int] = {}
            for (payload,) in session.execute(select(Event.payload).where(Event.type == "finding")):
                try:
                    verdict = ((json.loads(payload) or {}).get("validation") or {}).get("verdict")
                except (TypeError, ValueError):
                    verdict = None
                if verdict:
                    verdicts[verdict] = verdicts.get(verdict, 0) + 1
        return {"arena_states": {str(k): int(v) for k, v in states.items()},
                "budget_refusals": int(refusals), "verdicts": verdicts,
                "reaper_actions": {str(k): int(v) for k, v in reaper.items()}}

    def latest_ids(self, lab_id):
        """(newest event id, newest span id) for one lab, 0 when none."""
        with self._session() as session:
            event = session.scalar(select(func.max(Event.id)).where(Event.lab_id == lab_id))
            span = session.scalar(select(func.max(Span.id)).where(Span.arena_id == lab_id))
            return event or 0, span or 0

    def list_events(self, lab_id=None, limit=100, types=None, before_id=None):
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
            if before_id is not None:
                query = query.where(Event.id < before_id)
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

    def admit_agent_deploy(self, arena_id, *, agent_name, scenario, per_hour, max_live):
        """F4: quota check and audit record in one serialized step.

        The system gate row lock (PostgreSQL) / writer reservation (SQLite)
        serializes concurrent admissions, so N parallel requests can never all
        pass a quota of N-1. Counts this agent's ``agent_deploy`` events in the
        last hour and its arenas that are still live."""
        now = db_now()
        with self._session() as session:
            self._lock_gate(session, "system")
            rows = session.execute(select(Event.lab_id, Event.ts).where(
                Event.type == AGENT_DEPLOY_EVENT, Event.actor == agent_name)).all()
            recent = sum(1 for _, ts in rows if ts is not None and ts > now - timedelta(hours=1))
            if recent >= per_hour:
                raise AgentDeployRefused(
                    "agent_deploy_quota_exceeded",
                    f"{recent} agent deploys in the last hour (limit {per_hour})")
            labs = [lab for lab, _ in rows]
            live = session.scalar(select(func.count()).select_from(Deployment).where(
                Deployment.id.in_(labs), Deployment.status.in_(list(LIVE_STATES)))) if labs else 0
            if live >= max_live:
                raise AgentDeployRefused(
                    "agent_deploy_live_limit",
                    f"{live} live agent-deployed arenas (limit {max_live}); destroy one first")
            self._append_event(session, arena_id, agent_name, AGENT_DEPLOY_EVENT,
                               {"agent_name": agent_name, "scenario": scenario})
            session.commit()

    def scenario_binding_events(self, scenario, types, exclude_lab_id=None):
        """F2: binding events of every arena of ``scenario`` (newest first by
        global id), so the newest grant/revoke for an agent across a redeploy
        lineage can be found in one query."""
        with self._session() as session:
            labs = select(Deployment.id).where(Deployment.scenario == scenario)
            if exclude_lab_id is not None:
                labs = labs.where(Deployment.id != exclude_lab_id)
            query = (select(Event).where(Event.lab_id.in_(labs),
                                         Event.type.in_(list(types)))
                     .order_by(Event.id.desc()))
            return [
                {"id": e.id, "lab_id": e.lab_id, "ts": _stringify(e.ts),
                 "actor": e.actor, "type": e.type,
                 "payload": json.loads(e.payload) if e.payload else None}
                for e in session.scalars(query)
            ]

    def has_http_capture(self, lab_id: str, actor: str, digest: str) -> bool:
        """An immutable body-free execution receipt proves deduplicated capture access.

        Event payloads are serialized by _append_event with json.dumps. Match the
        complete named digest field, not a replay_of or another reference.
        """
        needle = json.dumps({"transaction_digest": digest})[1:-1]
        with self._session() as session:
            query = select(Event.id).where(
                Event.lab_id == lab_id, Event.actor == actor,
                Event.type == "http_request", Event.payload.contains(needle)).limit(1)
            return session.scalar(query) is not None

    # --- API keys (ADR-0002) -------------------------------------------------
    # Only SHA-256 digests are stored; plaintext keys never touch the DB.

    def create_api_key(self, key_hash, name, role):
        with self._session() as session:
            session.add(
                ApiKey(key_hash=key_hash, name=name, role=role, created_at=db_now())
            )
            session.commit()

    def get_api_key(self, key_hash):
        """Return the active (non-revoked) key record, updating last_used_at."""
        with self._session() as session:
            key = session.get(ApiKey, key_hash)
            if key is None or key.revoked:
                return None
            key.last_used_at = db_now()
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
    def _mc_headers(row: ModelConnection) -> dict:
        """Decrypted extra headers, or {} when unset or undecryptable.

        Values are secret-adjacent: callers must never log or return them —
        only sorted names and the digest leave storage (see _mc_masked)."""
        raw = decrypt_secret(row.encrypted_headers)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _mc_masked(row: ModelConnection) -> dict:
        headers = Database._mc_headers(row)
        return {
            "configured": True,
            "provider": row.provider,
            "model": row.model,
            "key_last4": row.key_last4,
            "base_url": row.base_url,  # non-secret (P3-4)
            "header_names": sorted(headers),  # names only, never values
            "headers_digest": extra_headers_digest(headers),
            "status": row.status,
            "updated_at": _stringify(row.updated_at),
        }

    def upsert_model_connection(self, owner, provider, model, api_key, base_url=None,
                                keep_key=False, extra_headers=None):
        """Create/replace the operator's model connection. Encrypts the API key
        at rest, keeps only a last-4 hint in clear, resets status to standby.
        Returns the masked view (never the key).

        ``keep_key=True`` updates provider/model but retains the stored key
        (the "update model, leave key blank" path); if there is no stored key
        yet it stores an empty one (keyless local runtimes).

        ``extra_headers=None`` keeps any stored headers (blank-update-keeps-
        stored, matching the key convention); ``{}`` clears them; a dict
        replaces them (validated by ``model_headers``; values encrypted
        exactly like the API key)."""
        now = db_now()
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
            if extra_headers is not None:
                normalized = normalize_extra_headers(extra_headers)
                row.encrypted_headers = (
                    encrypt_secret(json.dumps(normalized, sort_keys=True))
                    if normalized else None
                )
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
                "extra_headers": self._mc_headers(row),
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

    def api_keys_by_name(self, name):
        """Key metadata (never the hash) for every key with this name."""
        with self._session() as session:
            rows = session.scalars(select(ApiKey).where(ApiKey.name == name)).all()
            return [{"name": key.name, "role": key.role,
                     "created_at": _stringify(key.created_at),
                     "last_used_at": _stringify(key.last_used_at),
                     "revoked": bool(key.revoked)} for key in rows]

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
