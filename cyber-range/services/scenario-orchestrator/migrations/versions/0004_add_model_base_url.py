"""Add per-connection base_url to model_connections (P3-4).

A nullable, non-secret OpenAI-compatible base URL stored per operator model
connection. Overrides the provider preset and the NIDAVELLIR_MODEL_BASE_URL env
so different operators can point the companion at different OpenAI-compatible
gateways (OpenRouter / HuggingFace router / vLLM / self-hosted) without a shared
env var.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_connections",
        sa.Column("base_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_connections", "base_url")
