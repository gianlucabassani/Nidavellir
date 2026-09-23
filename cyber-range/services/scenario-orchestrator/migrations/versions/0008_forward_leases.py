"""durable scoped forward leases

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forward_leases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("arena_id", sa.Text(), nullable=False),
        sa.Column("principal", sa.Text(), nullable=False),
        sa.Column("principal_role", sa.Text(), nullable=False),
        sa.Column("binding_generation", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("foothold", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("service_id", sa.Text(), nullable=False),
        sa.Column("segment", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("stream_id", sa.Text(), unique=True),
        sa.Column("worker_claim", sa.Text()),
        sa.Column("bytes_in", sa.Integer(), nullable=False),
        sa.Column("bytes_out", sa.Integer(), nullable=False),
        sa.Column("cleanup_state", sa.Text(), nullable=False),
        sa.Column("cleanup_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("arena_id", "idempotency_key", name="uq_forward_arena_key"),
    )
    op.create_index("ix_forward_leases_arena_id", "forward_leases", ["arena_id"])


def downgrade():
    op.drop_index("ix_forward_leases_arena_id", table_name="forward_leases")
    op.drop_table("forward_leases")
