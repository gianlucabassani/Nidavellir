"""Global search indexes (UX-13, FR-18).

PostgreSQL: GIN full-text indexes ('simple' configuration, no stemming;
punctuation becomes spaces first, because the default parser keeps
"/admin/users" or "profile-bio" as one lexeme and a word would never match) over the operator-visible text the
search reads, and ``text_pattern_ops`` indexes so a digest prefix is an index
range scan. The expressions match ``search.py`` exactly; change both together.
SQLite (development and tests) gets the digest indexes only; search falls back
to LIKE there.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-25

"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_events_search ON events USING gin "
            "(to_tsvector('simple', regexp_replace(coalesce(payload, ''), "
            "'[^[:alnum:]_]+', ' ', 'g'))) "
            "WHERE type IN ('finding', 'http_request')")
        op.execute(
            "CREATE INDEX ix_spans_search ON spans USING gin "
            "(to_tsvector('simple', regexp_replace(name || ' ' || "
            "coalesce(input_preview, ''), '[^[:alnum:]_]+', ' ', 'g')))")
        op.execute("CREATE INDEX ix_spans_input_digest ON spans "
                   "(input_digest text_pattern_ops)")
        op.execute("CREATE INDEX ix_spans_output_digest ON spans "
                   "(output_digest text_pattern_ops)")
    else:
        op.create_index("ix_spans_input_digest", "spans", ["input_digest"])
        op.create_index("ix_spans_output_digest", "spans", ["output_digest"])


def downgrade() -> None:
    op.drop_index("ix_spans_output_digest", "spans")
    op.drop_index("ix_spans_input_digest", "spans")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_spans_search", "spans")
        op.drop_index("ix_events_search", "events")
