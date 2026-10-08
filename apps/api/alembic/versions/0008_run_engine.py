"""Which engine owns a run's checkpoint thread (D13).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08

`confirm_ticket` resumes the graph the run was proposed on, so the run has to remember it.
Every run before this migration was the support graph.
"""
import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("engine", sa.String(32), nullable=True))
    op.execute("UPDATE runs SET engine = 'support_graph'")


def downgrade() -> None:
    op.drop_column("runs", "engine")
