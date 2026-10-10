"""Numbered citations (D15): the model writes `[n]`, Python turns it into what the UI renders."""
from types import SimpleNamespace

from app.agent.common import Markers, segments_from, usage_counts

P = [
    {"source": "corpus://a", "title": "A", "text": "Each instance gets 1 vCPU."},
    {"source": "https://b", "title": "B", "text": "Memory defaults to 512 MiB."},
]


def parse(chunks: list[str], n: int = 2):
    m = Markers(n)
    pieces = [p for c in chunks for p in m.feed(c)] + m.flush()
    return pieces, m.bad


def test_a_marker_becomes_a_citation_and_leaves_the_text():
    pieces, bad = parse(["1 vCPU by default [1]."])
    assert pieces == [("text", "1 vCPU by default"), ("cite", 1), ("text", ".")] and bad == 0


def test_a_marker_split_across_chunks_still_parses():
    assert parse(["1 vCPU [", "1", "]", " and 512 MiB [2", "]"])[0] == [
        ("text", "1 vCPU"), ("cite", 1), ("text", " and 512 MiB"), ("cite", 2),
    ]


def test_adjacent_markers_cite_both():
    pieces, _ = parse(["Both [1][2]."])
    assert [p for p in pieces if p[0] == "cite"] == [("cite", 1), ("cite", 2)]


def test_a_number_with_no_passage_stays_as_text_and_is_counted():
    pieces, bad = parse(["See [9] and arr[0] and a lone [ bracket"])
    assert "".join(v for k, v in pieces if k == "text") == "See [9] and arr[0] and a lone [ bracket"
    assert bad == 2


def test_segments_keep_the_shape_the_ui_and_stored_messages_use():
    pieces, _ = parse(["1 vCPU [1]. Memory is 512 MiB [2][1]. Ask more."])
    text, citations, segments = segments_from(pieces, P)
    assert text == "1 vCPU. Memory is 512 MiB. Ask more."
    assert [s["text"] for s in segments] == ["1 vCPU", ". Memory is 512 MiB", ". Ask more."]
    assert [[c["title"] for c in s["citations"]] for s in segments] == [["A"], ["B", "A"], []]
    assert segments[0]["citations"][0] == {
        "source": "corpus://a", "title": "A", "cited_text": "Each instance gets 1 vCPU.",
    }
    assert len(citations) == 3


def test_cached_tokens_are_taken_out_of_prompt_tokens():
    """OpenAI's prompt_tokens includes cache reads and writes; pricing them as plain input
    too would overstate every cached call."""
    details = SimpleNamespace(cached_tokens=700, cache_write_tokens=200)
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=50, prompt_tokens_details=details)
    assert usage_counts(usage) == (100, 50, 200, 700)
