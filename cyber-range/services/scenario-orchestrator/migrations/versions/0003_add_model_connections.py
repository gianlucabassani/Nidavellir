"""Add model_connections (operator's BYO agent model credential).

One row per operator (owner is the PK). The API key is stored Fernet-encrypted
at rest in `encrypted_key`; only a non-secret last-4 hint is kept in `key_last4`
for masked display. `status` is 'standby' while configured-but-idle and 'active'
when an activator (scenario generator / agent-stance launch) is using it.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-19

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_connections",
        sa.Column("owner", sa.Text(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="standby"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("model_connections")
