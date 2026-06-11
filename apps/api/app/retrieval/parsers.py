from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedDocument:
    title: str
    text: str
    source_path: str


def _title_from_markdown(text: str, path: Path) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def parse_markdown(path: Path) -> ParsedDocument:
    text = path.read_text(encoding="utf-8")
    title = _title_from_markdown(text, path)
    return ParsedDocument(title=title, text=text, source_path=str(path))


def parse_pdf(path: Path) -> ParsedDocument:
    import pypdf

    reader = pypdf.PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n\n".join(pages)
    title = path.stem.replace("-", " ").replace("_", " ").title()
    return ParsedDocument(title=title, text=text, source_path=str(path))


def parse_html(path: Path) -> ParsedDocument:
    from bs4 import BeautifulSoup

    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # Extract title from <title> or first <h1>
    title_tag = soup.find("title")
    h1_tag = soup.find("h1")
    if title_tag:
        title = title_tag.get_text(strip=True)
    elif h1_tag:
        title = h1_tag.get_text(strip=True)
    else:
        title = path.stem.replace("-", " ").replace("_", " ").title()

    # Remove script and style elements
    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    # Collapse excessive blank lines
    import re

    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return ParsedDocument(title=title, text=text, source_path=str(path))


_PARSERS = {
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".pdf": parse_pdf,
    ".html": parse_html,
    ".htm": parse_html,
}


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise ValueError(f"Unsupported file type {suffix!r} for {path}")
    return parser(path)


def iter_corpus(corpus_dir: Path) -> list[Path]:
    """Return all parseable files in a corpus directory, sorted."""
    return sorted(
        p for p in corpus_dir.rglob("*") if p.is_file() and p.suffix.lower() in _PARSERS
    )
