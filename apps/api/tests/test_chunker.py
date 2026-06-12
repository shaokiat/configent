import tiktoken

from app.retrieval.chunker import chunk_document

_ENCODER = tiktoken.get_encoding("cl100k_base")


def _token_len(text: str) -> int:
    return len(_ENCODER.encode(text))


def test_chunker_respects_size_and_overlap():
    # Generate text that forces multiple chunks
    para = "This is a sentence about semiconductor equipment. " * 30
    text = "\n\n".join([para] * 5)

    chunks = chunk_document(text, "Test Doc", "corpus://test/doc", chunk_size=200, overlap=20)

    assert len(chunks) > 1, "Should produce multiple chunks for large text"
    for chunk in chunks:
        assert _token_len(chunk.text) <= 250, f"Chunk too large: {_token_len(chunk.text)}"

    # Verify overlap: last N tokens of chunk[i] should appear at the start of chunk[i+1]
    if len(chunks) >= 2:
        prev_tokens = _ENCODER.encode(chunks[0].text)
        next_tokens = _ENCODER.encode(chunks[1].text)
        # At least some overlap should exist
        overlap_start = next_tokens[: len(prev_tokens)]
        assert any(t in prev_tokens[-30:] for t in overlap_start[:20])


def test_chunker_keeps_small_table_intact():
    # A 20-row Markdown table under the limit should land in one chunk
    header = "| Part | P/N | Price |\n|------|-----|-------|\n"
    rows = "".join(f"| Part {i} | PN-{i:03d} | ${i * 10}.00 |\n" for i in range(20))
    table = header + rows

    assert _token_len(table) < 800, "Pre-condition: table fits in one chunk"

    chunks = chunk_document(table, "Parts Table", "corpus://test/parts", chunk_size=800, overlap=100)

    # All table content should be in one or two chunks (not fragmented across many)
    combined = " ".join(c.text for c in chunks)
    assert "Part 0" in combined
    assert "Part 19" in combined


def test_chunker_assigns_correct_metadata():
    text = "First paragraph with content.\n\nSecond paragraph with more content."
    chunks = chunk_document(text, "My Doc", "corpus://test/my-doc", chunk_size=800, overlap=100)

    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.document_title == "My Doc"
        assert chunk.source_uri == "corpus://test/my-doc"
        assert isinstance(chunk.chunk_index, int)


def test_chunker_empty_text():
    chunks = chunk_document("", "Empty", "corpus://test/empty", chunk_size=800, overlap=100)
    assert chunks == []


def test_chunker_single_small_paragraph():
    text = "One small paragraph that fits easily."
    chunks = chunk_document(text, "Small", "corpus://test/small", chunk_size=800, overlap=100)
    assert len(chunks) == 1
    assert "One small paragraph" in chunks[0].text
