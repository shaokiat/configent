"""Full-text search on chunks, for Level 2's keyword retrieval (D10).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-11

A generated `tsvector` column plus a GIN index. Generated, so ingest never writes it and it
cannot drift from `chunks.text`. This is the whole of the new search infrastructure: the
keyword half of hybrid search is Postgres, next to the pgvector half.
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chunks ADD COLUMN text_search tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
    )
    op.execute("CREATE INDEX ix_chunks_text_search ON chunks USING GIN (text_search)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_text_search")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS text_search")
