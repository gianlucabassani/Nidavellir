"""Durable paired evaluation records (NV-07).

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("agent_builds",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False, unique=True),
        sa.Column("driver", sa.Text(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("eval_challenges",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("source_arena_id", sa.Text(), nullable=False),
        sa.Column("recipe_digest", sa.Text(), nullable=False),
        sa.Column("validator_version", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("eval_suites",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("challenge_ids", sa.Text(), nullable=False),
        sa.Column("seeds", sa.Text(), nullable=False),
        sa.Column("action_cap", sa.Integer(), nullable=False),
        sa.Column("deadline_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("evaluations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("suite_id", sa.Text(), nullable=False),
        sa.Column("baseline_id", sa.Text(), nullable=False),
        sa.Column("candidate_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("eval_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("evaluation_id", sa.Text(), nullable=False),
        sa.Column("build_id", sa.Text(), nullable=False),
        sa.Column("challenge_id", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False))
    op.create_index("ix_eval_runs_evaluation_id", "eval_runs", ["evaluation_id"])
    op.create_table("eval_trials",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("evaluation_id", sa.Text(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("arena_id", sa.Text(), unique=True),
        sa.Column("starting_digest", sa.Text()),
        sa.Column("result", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("worker_claim", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "seed", name="uq_eval_run_seed"))
    op.create_index("ix_eval_trials_run_id", "eval_trials", ["run_id"])
    op.create_index("ix_eval_trials_evaluation_id", "eval_trials", ["evaluation_id"])


def downgrade():
    op.drop_index("ix_eval_trials_evaluation_id", table_name="eval_trials")
    op.drop_index("ix_eval_trials_run_id", table_name="eval_trials")
    op.drop_table("eval_trials")
    op.drop_index("ix_eval_runs_evaluation_id", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_table("evaluations")
    op.drop_table("eval_suites")
    op.drop_table("eval_challenges")
    op.drop_table("agent_builds")
