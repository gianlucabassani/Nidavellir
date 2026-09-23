"""
SQLAlchemy models (ADR-0004).

Column names and types deliberately mirror the pre-ORM raw-SQL schema so an
existing SQLite file (dev stacks, the compose volume) keeps working without
conversion. Schema changes go through Alembic migrations (`migrations/`),
never through editing these models alone.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(Text)  # the user's friendly name
    scenario: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)  # see states.LabStatus
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    outputs: Mapped[str | None] = mapped_column(Text)  # JSON text, flat {name: value}
    error: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)  # backend recorded at deploy
    effective_provider: Mapped[str | None] = mapped_column(Text)  # resolved backend snapshot
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # TTL; NULL = no expiry


class LifecycleRecipe(Base):
    __tablename__ = "lifecycle_recipes"

    deployment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ResetOperation(Base):
    __tablename__ = "reset_operations"
    __table_args__ = (
        UniqueConstraint("source_id", "idempotency_key", name="uq_reset_source_key"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    replacement_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Equal to source_id while in flight and NULL when terminal. The unique
    # column is an atomic, cross-database one-reset-per-source claim.
    active_source: Mapped[str | None] = mapped_column(Text, unique=True)
    recipe_digest: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)


class PocJob(Base):
    """Durable, worker-owned confined PoC execution (ADR-0014).

    Active slot columns are nullable unique leases.  Clearing them at every
    terminal transition makes admission atomic on SQLite and PostgreSQL without
    relying on process-local counters.
    """

    __tablename__ = "poc_jobs"
    __table_args__ = (
        UniqueConstraint("arena_id", "idempotency_key", name="uq_poc_arena_key"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    arena_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    principal_role: Mapped[str] = mapped_column(Text, nullable=False)
    binding_stance: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    input_digest: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    runner_image: Mapped[str] = mapped_column(Text, nullable=False)
    runner_image_id: Mapped[str | None] = mapped_column(Text)
    target_node: Mapped[str | None] = mapped_column(Text)
    target_policy: Mapped[str | None] = mapped_column(Text)
    limits: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    worker_claim: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    result: Mapped[str | None] = mapped_column(Text)
    cleanup_state: Mapped[str] = mapped_column(Text, nullable=False)
    cleanup_error: Mapped[str | None] = mapped_column(Text)
    active_arena_slot: Mapped[str | None] = mapped_column(Text, unique=True)
    active_global_slot: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class BudgetGate(Base):
    """A durable lock row for system and arena admissions and stop state."""

    __tablename__ = "budget_gates"

    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    account_scope: Mapped[str | None] = mapped_column(Text)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BudgetAccount(Base):
    """The scope survives replacement reset by retaining the source scope ID."""

    __tablename__ = "budget_accounts"

    arena_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    action_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BudgetAction(Base):
    __tablename__ = "budget_actions"
    __table_args__ = (UniqueConstraint("arena_id", "action_key", name="uq_budget_action_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    arena_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    action_key: Mapped[str] = mapped_column(Text, nullable=False)
    input_digest: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BudgetControl(Base):
    __tablename__ = "budget_controls"

    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ForwardLease(Base):
    """One fixed-destination, single-stream research access lease."""

    __tablename__ = "forward_leases"
    __table_args__ = (
        UniqueConstraint("arena_id", "idempotency_key", name="uq_forward_arena_key"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    arena_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    principal: Mapped[str] = mapped_column(Text, nullable=False)
    principal_role: Mapped[str] = mapped_column(Text, nullable=False)
    binding_generation: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_digest: Mapped[str] = mapped_column(Text, nullable=False)
    foothold: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    service_id: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    stream_id: Mapped[str | None] = mapped_column(Text, unique=True)
    worker_claim: Mapped[str | None] = mapped_column(Text)
    bytes_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cleanup_state: Mapped[str] = mapped_column(Text, nullable=False)
    cleanup_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    key_hash: Mapped[str] = mapped_column(Text, primary_key=True)  # SHA-256 only
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class ModelConnection(Base):
    """An operator's bring-your-own model credential (provider + model + API key),
    bound to the operator principal (``owner`` is the PK — one current connection
    per operator).

    Security-by-design: the API key is stored **Fernet-encrypted at rest**
    (``crypto.encrypt_secret``) in ``encrypted_key``; only a non-secret last-4
    hint (``key_last4``) is kept in clear for masked display. The plaintext key
    is never logged and never returned over the API — it is decrypted only
    in-process when an *activator* (scenario generator / agent-stance launch)
    needs it. ``status`` is ``standby`` while configured-but-idle ("active but
    waiting") and flips to ``active`` when a feature is using the connection.
    """

    __tablename__ = "model_connections"

    owner: Mapped[str] = mapped_column(Text, primary_key=True)  # Principal.name
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet ciphertext
    key_last4: Mapped[str | None] = mapped_column(Text)  # display hint only
    # Per-connection OpenAI-compatible base URL (OpenRouter/HF/vLLM/self-hosted) —
    # overrides the provider preset + NIDAVELLIR_MODEL_BASE_URL. Non-secret (P3-4).
    base_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="standby", server_default="standby"
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Event(Base):
    """Append-only audit stream: lab state transitions and admin actions.

    `lab_id` is intentionally NOT a foreign key — the audit trail must
    survive the lab record being deleted from the archive.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lab_id: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)  # api key name / "worker"
    type: Mapped[str] = mapped_column(Text, nullable=False)  # created|status|record_deleted
    payload: Mapped[str | None] = mapped_column(Text)  # JSON text
