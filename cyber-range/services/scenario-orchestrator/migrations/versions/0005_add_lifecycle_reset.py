"""Add immutable lifecycle recipes and durable reset operations (NV-02).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deployments", sa.Column("effective_provider", sa.Text(), nullable=True))
    op.create_table(
        "lifecycle_recipes",
        sa.Column("deployment_id", sa.Text(), primary_key=True),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "reset_operations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("replacement_id", sa.Text(), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("active_source", sa.Text(), nullable=True, unique=True),
        sa.Column("recipe_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.UniqueConstraint("source_id", "idempotency_key", name="uq_reset_source_key"),
    )
    op.create_index("ix_reset_operations_source_id", "reset_operations", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_reset_operations_source_id", "reset_operations")
    op.drop_table("reset_operations")
    op.drop_table("lifecycle_recipes")
    op.drop_column("deployments", "effective_provider")
