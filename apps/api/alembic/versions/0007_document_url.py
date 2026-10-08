"""A document's own link, for citations that open the upstream page.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08

Set at ingest from the file's front matter `url:` or `corpus.source_url_template`. Null means
no link: the citation falls back to the stable `corpus://` URI. Existing rows stay null until
their next rebuild.
"""
import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("url", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "url")
