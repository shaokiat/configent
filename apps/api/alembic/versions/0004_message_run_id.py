"""Link a message to the pipeline run that produced it.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-30

The step trail is durable in `runs.steps` but was unreachable when reloading a
conversation, because history is rebuilt from `messages`. This adds the join rather than
copying the steps: `runs` stays the single source of truth, so a run that crashed before
its message was written still keeps its trail.
"""
import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("run_id", sa.String(64), nullable=True))
    op.create_index("ix_messages_run_id", "messages", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_run_id", table_name="messages")
    op.drop_column("messages", "run_id")
