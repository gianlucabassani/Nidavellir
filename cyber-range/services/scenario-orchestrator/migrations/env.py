"""Alembic environment: reuses the app's URL resolution and model metadata."""
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

# Make the flat-layout service importable when alembic is invoked from
# anywhere other than the service directory (e.g. repo root, CI).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import database_url  # noqa: E402
from models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
