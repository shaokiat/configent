"""Per-document ingest fingerprint, so a settings change rebuilds the index.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29

`CorpusConfig.fingerprint()` hashes the embedding model, chunk size and overlap. Ingest
skips a document only when its content hash *and* fingerprint match; the chat endpoints
refuse a client whose documents carry any other fingerprint. Existing rows are null, which
matches nothing, so the first ingest after this migration rebuilds them.
"""
import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("ingest_fingerprint", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "ingest_fingerprint")
