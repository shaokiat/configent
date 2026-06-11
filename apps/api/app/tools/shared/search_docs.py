"""search_docs tool: semantic search over the client's document corpus."""
from typing import Any

DEFINITION = {
    "name": "search_docs",
    "description": (
        "Search the client's document corpus for information relevant to the user's question. "
        "Use this tool whenever the user asks a factual question that may be answered by the "
        "documentation — maintenance procedures, error codes, part numbers, policy clauses, "
        "claim procedures, specifications, or any other domain-specific fact. "
        "Always call this tool before answering factual questions; do not answer from memory. "
        "You may call it multiple times with different queries if the question spans multiple topics."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A focused natural-language search query. Be specific: include the "
                    "key entities (part names, error codes, clause numbers, product names) "
                    "rather than a verbatim copy of the user's question."
                ),
            },
            "k": {
                "type": "integer",
                "description": "Number of results to return. Defaults to 5. Use up to 8 for broad topics.",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}


async def execute(tool_input: dict[str, Any], *, client_id: str, db) -> list[dict]:
    from app.retrieval.search import search

    query = tool_input["query"]
    k = tool_input.get("k", 5)
    hits = await search(db, client_id=client_id, query=query, k=k)
    return [
        {
            "chunk_id": h.chunk_id,
            "document_id": h.document_id,
            "document_title": h.document_title,
            "source_uri": h.source_uri,
            "text": h.text,
            "similarity": round(h.similarity, 4),
        }
        for h in hits
    ]
