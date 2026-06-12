"""Initial schema: clients, documents, chunks, conversations, messages, traces, eval_runs

Revision ID: 0001
Revises:
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op
from app.retrieval.embed import EMBEDDING_DIM

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "clients",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("config_snapshot", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.String(64), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("source_uri", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("ingested_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", "source_uri", name="uq_client_source"),
    )
    op.create_index("ix_documents_client_id", "documents", ["client_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_client_id", "chunks", ["client_id"])
    # HNSW index for fast approximate nearest neighbour search
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("total_cost", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_conversations_client_id", "conversations", ["client_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("citations", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "traces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("span_type", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("input", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("output", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_traces_conversation_id", "traces", ["conversation_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("git_sha", sa.String(40), nullable=True),
        sa.Column("scores", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("ran_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_eval_runs_client_id", "eval_runs", ["client_id"])


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("traces")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.drop_index("ix_chunks_client_id", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_documents_client_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("clients")
