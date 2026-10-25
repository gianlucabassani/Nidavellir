"""Immutable encrypted configuration snapshots.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("configuration_snapshots",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("arena_id", sa.Text(), nullable=False),
        sa.Column("target_digest", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("snapshot_digest", sa.Text(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("arena_id", "snapshot_digest", name="uq_configuration_digest"))
    op.create_index("ix_configuration_snapshots_arena_id", "configuration_snapshots", ["arena_id"])


def downgrade():
    op.drop_index("ix_configuration_snapshots_arena_id", table_name="configuration_snapshots")
    op.drop_table("configuration_snapshots")
