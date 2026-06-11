import re
from dataclasses import dataclass

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def _token_len(text: str) -> int:
    return len(_ENCODER.encode(text))


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _split_sentences(text: str) -> list[str]:
    # Split on sentence-ending punctuation followed by whitespace or end of string
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


@dataclass
class Chunk:
    text: str
    chunk_index: int
    document_title: str
    source_uri: str


def chunk_document(
    text: str,
    document_title: str,
    source_uri: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[Chunk]:
    """Chunk a document into token-aware pieces with overlap.

    Strategy (in order):
    1. Split on double-newline (paragraph boundaries).
    2. If a paragraph exceeds chunk_size, split on sentences.
    3. If a sentence still exceeds chunk_size, hard-split by tokens.

    Overlap is implemented by carrying forward the last `overlap` tokens
    from the previous chunk as a prefix for the next.
    """
    paragraphs = _split_paragraphs(text)

    # Flatten into a list of atomic units that fit within chunk_size
    units: list[str] = []
    for para in paragraphs:
        if _token_len(para) <= chunk_size:
            units.append(para)
        else:
            sentences = _split_sentences(para)
            for sent in sentences:
                if _token_len(sent) <= chunk_size:
                    units.append(sent)
                else:
                    # Hard split by tokens
                    tokens = _ENCODER.encode(sent)
                    for i in range(0, len(tokens), chunk_size):
                        fragment = _ENCODER.decode(tokens[i : i + chunk_size])
                        units.append(fragment)

    # Assemble units into chunks, respecting chunk_size with overlap
    chunks: list[Chunk] = []
    current_tokens: list[int] = []
    overlap_buffer: list[int] = []

    def flush(buf: list[int]) -> None:
        if not buf:
            return
        chunk_text = _ENCODER.decode(buf).strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    text=chunk_text,
                    chunk_index=len(chunks),
                    document_title=document_title,
                    source_uri=source_uri,
                )
            )

    for unit in units:
        unit_tokens = _ENCODER.encode(unit)

        if current_tokens and _token_len("") + len(current_tokens) + len(unit_tokens) > chunk_size:
            flush(current_tokens)
            # Start new chunk with overlap from end of previous chunk
            overlap_buffer = current_tokens[-overlap:] if overlap > 0 else []
            current_tokens = overlap_buffer + unit_tokens
        else:
            current_tokens.extend(unit_tokens)

    flush(current_tokens)
    return chunks
