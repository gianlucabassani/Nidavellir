"""durable action budgets and stop gates

Revision ID: 0007
Revises: 0006
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "budget_gates",
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("account_scope", sa.Text()),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "budget_accounts",
        sa.Column("arena_id", sa.Text(), primary_key=True),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action_cap", sa.Integer(), nullable=False),
        sa.Column("spent", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_budget_accounts_scope_id", "budget_accounts", ["scope_id"])
    op.create_table(
        "budget_actions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("arena_id", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("action_key", sa.Text(), nullable=False),
        sa.Column("input_digest", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("arena_id", "action_key", name="uq_budget_action_key"),
    )
    op.create_index("ix_budget_actions_arena_id", "budget_actions", ["arena_id"])
    op.create_table(
        "budget_controls",
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.bulk_insert(sa.table("budget_gates", sa.column("scope", sa.Text()),
                            sa.column("account_scope", sa.Text()),
                            sa.column("epoch", sa.Integer()), sa.column("state", sa.Text()),
                            sa.column("reason", sa.Text()), sa.column("updated_at", sa.DateTime())),
                   [{"scope": "system", "account_scope": None, "epoch": 0, "state": "open",
                     "reason": None, "updated_at": datetime.utcnow()}])


def downgrade():
    op.drop_table("budget_controls")
    op.drop_index("ix_budget_actions_arena_id", table_name="budget_actions")
    op.drop_table("budget_actions")
    op.drop_index("ix_budget_accounts_scope_id", table_name="budget_accounts")
    op.drop_table("budget_accounts")
    op.drop_table("budget_gates")
