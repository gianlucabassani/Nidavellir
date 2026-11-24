"""spans: one row per action (ADR-0018, OBS-01)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "spans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("span_id", sa.Text(), nullable=False, unique=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("parent_span_id", sa.Text()),
        sa.Column("arena_id", sa.Text()),
        sa.Column("evaluation_id", sa.Text()),
        sa.Column("trial_id", sa.Text()),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("stance", sa.Text()),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_class", sa.Text()),
        sa.Column("input_digest", sa.Text()),
        sa.Column("output_digest", sa.Text()),
        sa.Column("input_preview", sa.Text()),
        sa.Column("output_preview", sa.Text()),
        sa.Column("attrs", sa.Text()),
        sa.Column("visibility", sa.Text(), nullable=False),
    )
    op.create_index("ix_spans_arena_id_id", "spans", ["arena_id", "id"])
    op.create_index("ix_spans_trace_id", "spans", ["trace_id"])
    op.create_index("ix_spans_trial_id", "spans", ["trial_id"])


def downgrade():
    op.drop_index("ix_spans_trial_id", table_name="spans")
    op.drop_index("ix_spans_trace_id", table_name="spans")
    op.drop_index("ix_spans_arena_id_id", table_name="spans")
    op.drop_table("spans")
