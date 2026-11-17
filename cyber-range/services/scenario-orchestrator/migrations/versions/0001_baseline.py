"""Baseline: the schema as of ADR-0004 adoption.

Matches models.py exactly (deployments incl. the provider column from the
per-request provider-selection work, api_keys from ADR-0002, and the new
events audit table). Pre-existing SQLite files created by the raw-SQL era
already contain deployments/api_keys with these columns; on such databases
run `alembic stamp 0001` once, then upgrade normally.

Revision ID: 0001
Revises:
Create Date: 2026-06-11

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("scenario", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("outputs", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
    )
    op.create_table(
        "api_keys",
        sa.Column("key_hash", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lab_id", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
    )
    op.create_index("ix_events_lab_id", "events", ["lab_id"])


def downgrade() -> None:
    op.drop_index("ix_events_lab_id", "events")
    op.drop_table("events")
    op.drop_table("api_keys")
    op.drop_table("deployments")
