"""Event indexes for type-filtered reads; naive timestamps are UTC (FR-08).

Adds ``ix_events_lab_type_id (lab_id, type, id)`` for per-arena event reads
filtered by type (session lists) and ``ix_events_type_id (type, id)`` for global
type scans (lost source-review captures).

Timestamp decision (recorded here, 2026-11-16): every
``DateTime`` column stays timezone-naive and its values are interpreted as UTC.
Rows written before this revision came from ``datetime.now()`` inside the
python:3.11-slim service containers, which run without ``TZ`` and therefore in
UTC, so no data is rewritten. Rows written by a service run directly on a non-UTC
host are offset by that host's UTC offset; they are not corrected. New writes use
``timeutil.db_now()`` (aware UTC, stored naive).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-16

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_events_lab_type_id", "events", ["lab_id", "type", "id"])
    op.create_index("ix_events_type_id", "events", ["type", "id"])


def downgrade() -> None:
    op.drop_index("ix_events_type_id", "events")
    op.drop_index("ix_events_lab_type_id", "events")
