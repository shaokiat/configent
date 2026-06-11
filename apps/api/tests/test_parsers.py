from pathlib import Path

import pytest

from app.retrieval.parsers import parse_document, parse_markdown


def test_parse_markdown_extracts_h1_title():
    # Test against a real corpus file
    path = Path(__file__).parents[3] / "corpora/acme-fab/px900-maintenance-manual.md"
    if not path.exists():
        pytest.skip("Corpus file not found")

    doc = parse_document(path)
    assert "PX-900" in doc.title
    assert len(doc.text) > 100
    assert doc.source_path == str(path)


def test_parse_markdown_meridian_file():
    path = Path(__file__).parents[3] / "corpora/meridian-insurance/home-policy-wording.md"
    if not path.exists():
        pytest.skip("Corpus file not found")

    doc = parse_document(path)
    assert "HomeShield" in doc.title or "Policy" in doc.title
    assert "Clause 4.2.1" in doc.text


def test_parse_markdown_troubleshooting():
    path = Path(__file__).parents[3] / "corpora/acme-fab/px900-troubleshooting-guide.md"
    if not path.exists():
        pytest.skip("Corpus file not found")

    doc = parse_document(path)
    assert "E-417" in doc.text
    assert len(doc.text) > 500


def test_parse_document_unsupported_extension(tmp_path):
    f = tmp_path / "file.xyz"
    f.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported"):
        parse_document(f)


def test_parse_markdown_fallback_title(tmp_path):
    f = tmp_path / "my-cool-doc.md"
    f.write_text("No heading here, just content.\n\nMore content.")
    doc = parse_markdown(f)
    assert "My Cool Doc" in doc.title or "my-cool-doc" in doc.title.lower()
    assert "just content" in doc.text
