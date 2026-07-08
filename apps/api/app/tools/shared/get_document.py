"""get_document tool: retrieve full document text by its corpus:// source URI."""
from typing import Any

_MAX_CHARS = 8000

DEFINITION = {
    "name": "get_document",
    "description": (
        "Retrieve the full text of a specific document from the corpus by its source URI. "
        "Use this tool when search_docs has returned a chunk that references a document and "
        "you need more context than the chunk provides — for example, when a procedure spans "
        "multiple sections, or when the user asks to see a complete policy section. "
        "The source URI is returned by search_docs and by citations as the 'source' field "
        "(a corpus://<client>/<document> URI). "
        "Do not call this tool speculatively; use search_docs first to identify the relevant document."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": (
                    "The corpus:// source URI as returned in the 'source' field of a "
                    "search_docs result or citation."
                ),
            }
        },
        "required": ["source"],
    },
}


def _chunks_to_text(chunks: list) -> str:
    """Fallback for documents ingested before full_text existed: reconstruct text
    by concatenating chunks in original order."""
    ordered = sorted(chunks, key=lambda c: c.chunk_index)
    return "\n\n".join(c.text for c in ordered)


async def execute(tool_input: dict[str, Any], *, client_id: str, db) -> dict:
    from sqlalchemy import select

    from app.models import Chunk, Document

    source = tool_input["source"]

    result = await db.execute(
        select(Document).where(
            Document.source_uri == source, Document.client_id == client_id
        )
    )
    doc = result.scalar_one_or_none()

    if doc is None:
        return {"error": f"Document {source!r} not found for this client."}

    text = doc.full_text
    if not text:
        chunk_result = await db.execute(
            select(Chunk).where(
                Chunk.document_id == doc.id, Chunk.client_id == client_id
            )
        )
        text = _chunks_to_text(chunk_result.scalars().all())

    truncated = len(text) > _MAX_CHARS
    return {
        "title": doc.title,
        "source": doc.source_uri,
        "full_text": text[:_MAX_CHARS],
        "truncated": truncated,
    }
