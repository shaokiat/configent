"""Engines are now templates (D13, amended 2026-10-10).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-10

The stored names change with the column, or a ticket offer pending across the deploy would
404 on confirm: `confirm_ticket` looks the run's template up among the compiled graphs.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_NAMES = {"support_graph": "documents", "text_to_sql": "database"}


def upgrade() -> None:
    op.alter_column("runs", "engine", new_column_name="template")
    for old, new in _NAMES.items():
        op.execute(f"UPDATE runs SET template = '{new}' WHERE template = '{old}'")


def downgrade() -> None:
    for old, new in _NAMES.items():
        op.execute(f"UPDATE runs SET template = '{old}' WHERE template = '{new}'")
    op.alter_column("runs", "template", new_column_name="engine")
