"""copilot chats and messages (ADR-0020, UX-20)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "copilot_chats",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_copilot_chats_owner_updated", "copilot_chats",
                    ["owner", "updated_at"])
    op.create_table(
        "copilot_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("data", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_copilot_messages_chat_id", "copilot_messages", ["chat_id", "id"])


def downgrade():
    op.drop_index("ix_copilot_messages_chat_id", "copilot_messages")
    op.drop_table("copilot_messages")
    op.drop_index("ix_copilot_chats_owner_updated", "copilot_chats")
    op.drop_table("copilot_chats")
