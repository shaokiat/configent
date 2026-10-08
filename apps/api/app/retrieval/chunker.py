import re
from dataclasses import dataclass

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def token_len(text: str) -> int:
    return len(_ENCODER.encode(text))


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _split_sentences(text: str) -> list[str]:
    # Split on sentence-ending punctuation followed by whitespace or end of string
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


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
    prefix_title: bool = False,
    markdown: bool = False,
) -> list[Chunk]:
    """Chunk a document into token-aware pieces with overlap.

    Strategy (in order):
    1. Split on double-newline (paragraph boundaries).
    2. If a paragraph exceeds chunk_size, split on sentences.
    3. If a sentence still exceeds chunk_size, hard-split by tokens.

    Overlap is implemented by carrying forward the last `overlap` tokens
    from the previous chunk as a prefix for the next.

    `prefix_title` puts "<title> — <heading path>" in front of every chunk's text, so the
    embedding and the tsvector both see where the chunk came from. The path is built from
    `#` headings only when `markdown` is set; other formats get the title alone. The prefix
    sits on top of `chunk_size`, which counts the body.
    """
    paragraphs = _split_paragraphs(text)

    # Flatten into a list of atomic units that fit within chunk_size, each with the heading
    # path in force where it sits.
    units: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    in_fence = False
    for para in paragraphs:
        for line in para.splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence  # a `# comment` in a code block is not a heading
            elif markdown and not in_fence and (m := _HEADING.match(line)):
                level = len(m.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, m.group(2)))
        # The H1 usually is the title; repeating it in the path adds nothing.
        path = " › ".join(t for _, t in stack if t != document_title)
        if token_len(para) <= chunk_size:
            units.append((para, path))
        else:
            sentences = _split_sentences(para)
            for sent in sentences:
                if token_len(sent) <= chunk_size:
                    units.append((sent, path))
                else:
                    # Hard split by tokens
                    tokens = _ENCODER.encode(sent)
                    for i in range(0, len(tokens), chunk_size):
                        fragment = _ENCODER.decode(tokens[i : i + chunk_size])
                        units.append((fragment, path))

    # Assemble units into chunks, respecting chunk_size with overlap
    chunks: list[Chunk] = []
    current_tokens: list[int] = []
    overlap_buffer: list[int] = []
    # Path of the unit that opened the chunk being built, not of the overlap carried in.
    start_path = ""

    def flush(buf: list[int], path: str) -> None:
        if not buf:
            return
        chunk_text = _ENCODER.decode(buf).strip()
        if chunk_text:
            if prefix_title:
                chunk_text = f"{document_title}{' — ' + path if path else ''}\n\n{chunk_text}"
            chunks.append(
                Chunk(
                    text=chunk_text,
                    chunk_index=len(chunks),
                    document_title=document_title,
                    source_uri=source_uri,
                )
            )

    for unit, path in units:
        unit_tokens = _ENCODER.encode(unit)

        if current_tokens and token_len("") + len(current_tokens) + len(unit_tokens) > chunk_size:
            flush(current_tokens, start_path)
            # Start new chunk with overlap from end of previous chunk
            overlap_buffer = current_tokens[-overlap:] if overlap > 0 else []
            current_tokens = overlap_buffer + unit_tokens
            start_path = path
        else:
            if not current_tokens:
                start_path = path
            current_tokens.extend(unit_tokens)

    flush(current_tokens, start_path)
    return chunks
