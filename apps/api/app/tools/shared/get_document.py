"""get_document tool: retrieve full document text by document_id."""
from typing import Any

DEFINITION = {
    "name": "get_document",
    "description": (
        "Retrieve the full text of a specific document from the corpus by its document ID. "
        "Use this tool when search_docs has returned a chunk that references a document and "
        "you need more context than the chunk provides — for example, when a procedure spans "
        "multiple sections, or when the user asks to see a complete policy section. "
        "The document_id is returned by search_docs in the 'document_id' field of each result. "
        "Do not call this tool speculatively; use search_docs first to identify the relevant document."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "The document ID as returned by the search_docs tool.",
            }
        },
        "required": ["document_id"],
    },
}


async def execute(tool_input: dict[str, Any], *, client_id: str, db) -> dict:
    from sqlalchemy import select

    from app.models import Document

    doc_id = tool_input["document_id"]
    result = await db.get(Document, doc_id)

    if result is None or result.client_id != client_id:
        return {"error": f"Document {doc_id!r} not found for this client."}

    return {
        "document_id": result.id,
        "title": result.title,
        "source_uri": result.source_uri,
        # Return the first 8000 chars to stay within practical limits
        "text": result.title + "\n\n" + "(full document — use for context)",
    }
