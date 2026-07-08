"""Add documents.full_text (A2): backs get_document with real content instead
of a placeholder string.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""
import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("full_text", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "full_text")
