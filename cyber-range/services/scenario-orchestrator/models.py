"""
SQLAlchemy models (ADR-0004).

Column names and types deliberately mirror the pre-ORM raw-SQL schema so an
existing SQLite file (dev stacks, the compose volume) keeps working without
conversion. Schema changes go through Alembic migrations (`migrations/`),
never through editing these models alone.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
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
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # TTL; NULL = no expiry


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
