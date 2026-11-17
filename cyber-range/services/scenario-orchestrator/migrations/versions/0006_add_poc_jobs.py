"""add durable confined PoC jobs

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "poc_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("arena_id", sa.Text(), nullable=False),
        sa.Column("principal", sa.Text(), nullable=False),
        sa.Column("principal_role", sa.Text(), nullable=False),
        sa.Column("binding_stance", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("input_digest", sa.Text(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("runner_image", sa.Text(), nullable=False),
        sa.Column("runner_image_id", sa.Text(), nullable=True),
        sa.Column("target_node", sa.Text(), nullable=True),
        sa.Column("target_policy", sa.Text(), nullable=True),
        sa.Column("limits", sa.Text(), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("worker_claim", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("cleanup_state", sa.Text(), nullable=False),
        sa.Column("cleanup_error", sa.Text(), nullable=True),
        sa.Column("active_arena_slot", sa.Text(), nullable=True, unique=True),
        sa.Column("active_global_slot", sa.Text(), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("arena_id", "idempotency_key", name="uq_poc_arena_key"),
    )
    op.create_index("ix_poc_jobs_arena_id", "poc_jobs", ["arena_id"])


def downgrade():
    op.drop_index("ix_poc_jobs_arena_id", table_name="poc_jobs")
    op.drop_table("poc_jobs")
