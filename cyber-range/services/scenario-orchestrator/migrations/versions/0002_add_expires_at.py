"""Add deployments.expires_at (lab TTL, audit #9 reaper).

NULL means "no expiry" — pre-existing rows are left untouched and never
auto-reaped on the expiry path (the stuck-reconciliation path keys off
updated_at instead, so it still covers them).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deployments", sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployments", "expires_at")
