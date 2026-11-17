"""Add encrypted extra headers to model_connections (MODEL-R1).

A nullable Fernet-encrypted JSON blob carrying the operator-approved static
request headers for the connection (e.g. User-Agent / x-opencode-session for
gateways that reject the default request shape). Encrypted exactly like
encrypted_key; NULL means "no headers".

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-06

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_connections",
        sa.Column("encrypted_headers", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_connections", "encrypted_headers")
