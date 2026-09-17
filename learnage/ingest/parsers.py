"""Book parsers — epub / pdf / docx / txt → ParsedBook."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


def sanitize_text(s: str) -> str:
    """Strip control / non-printable characters and normalize whitespace.

    Some DOCX/PDF extractors produce layout binary or stray control codes
    (\\x00-\\x08, \\x0b-\\x1f, \\x7f) which the chunk text inherits. We keep
    real Unicode punctuation, smart quotes, em-dashes, etc. (codepoints
    >= 0x20 or in common Unicode punctuation ranges).
    """
    if not s:
        return ""
    # Normalize whitespace first
    s = unicodedata.normalize("NFKC", s)
    # Drop C0/C1 controls except \t, \n, \r
    s = "".join(
        ch for ch in s
        if ch in "\t\n\r"
        or (ord(ch) >= 0x20 and ord(ch) not in (0x7f,))
        and not (0x80 <= ord(ch) <= 0x9f)
    )
    # Replace common layout garbage that survived
    s = s.replace("\x00", "")
    # Collapse runs of spaces (preserve newlines)
    s = re.sub(r"[^\S\n]+", " ", s)
    # Drop blank-line spam
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


@dataclass
class Chapter:
    heading: str | None
    text: str


@dataclass
class ParsedBook:
    title: str
    author: str | None
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        out = []
        for ch in self.chapters:
            if ch.heading:
                out.append(f"\n# {ch.heading}\n")
            out.append(ch.text)
        return "\n".join(out)


# --------------------------------------------------------------------- detect


def detect_format(path: Path) -> str:
    """Return one of: epub, pdf, docx, txt."""
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "epub":
        return "epub"
    if suffix == "pdf":
        return "pdf"
    if suffix in ("docx", "doc"):
        return "docx"
    if suffix == "txt":
        return "txt"
    raise ValueError(f"Unsupported format: {path.suffix}")


# --------------------------------------------------------------------- epub


def _parse_epub(path: Path) -> ParsedBook:
    from ebooklib import epub, ITEM_DOCUMENT  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore

    book = epub.read_epub(str(path), options={"ignore_ncx": True})

    # Title / author
    title = _dc_field(book.get_metadata("DC", "title")) or path.stem
    author = _dc_field(book.get_metadata("DC", "creator"))

    chapters: list[Chapter] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Find a heading-ish first line
        heading = None
        for tag in ("h1", "h2", "h3"):
            h = soup.find(tag)
            if h and h.get_text(strip=True):
                heading = h.get_text(strip=True)
                break
        text = soup.get_text(separator="\n", strip=True)
        text = sanitize_text(text)
        if text:
            chapters.append(Chapter(heading=heading, text=text))

    if not chapters:
        # Fallback: treat whole book as one chapter
        chapters = [Chapter(heading=None, text="")]
    return ParsedBook(title=title, author=author, chapters=chapters)


def _dc_field(items: list[tuple[str, dict]]) -> str | None:
    if not items:
        return None
    return items[0][0] or None


# --------------------------------------------------------------------- pdf


_PDF_HEADING_RE = re.compile(
    r"^(chapter|CHAPTER|Chapter)\s+([\w\dIVX]+)(?:\s*[:.\-—]\s*(.+))?$",
    re.MULTILINE,
)
# All-caps lines that are short and not page numbers — common in older books.
_PDF_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9 ,&'\-:!?]{2,80}$")


def _pdf_outline_chapters(reader) -> list[tuple[int, str]] | None:
    """Return [(page_index, heading)] from the PDF outline / TOC.

    Returns None if no usable outline. Filters out empty titles and tries
    to skip "Cover", "Dedication", "Illustrations" if they would dominate.
    """
    try:
        outline = reader.outline
    except Exception:  # noqa: BLE001
        return None
    if not outline:
        return None

    flat: list[tuple[int, str]] = []

    def _walk(node):
        if isinstance(node, list):
            for child in node:
                _walk(child)
            return
        # OutlinedItem — has .title and .page (Destination)
        try:
            title = getattr(node, "title", None)
            page_idx = reader.get_destination_page_number(node)
        except Exception:  # noqa: BLE001
            return
        if not title:
            return
        # Strip whitespace; collapse multi-line
        clean = " ".join(str(title).split()).strip()
        if len(clean) < 2 or len(clean) > 200:
            return
        flat.append((int(page_idx), clean))

    _walk(outline)
    if not flat:
        return None
    # Sort by page; keep order as-is from tree (which is meaningful).
    flat.sort(key=lambda x: x[0])
    return flat


def _looks_like_heading(line: str) -> bool:
    """Heuristic: short line, mostly caps or title case, ends without punctuation."""
    s = line.strip()
    if not s or len(s) > 100:
        return False
    # Reject pure page numbers
    if re.match(r"^\d+$", s):
        return False
    # Reject obvious body text: long-ish with lots of lowercase letters
    if len(s) > 60:
        return False
    # Accept ALL CAPS lines (common in older books)
    if _PDF_CAPS_RE.match(s) and len(s) >= 4:
        return True
    # Accept "Chapter N — Title" style
    if _PDF_HEADING_RE.match(s):
        return True
    return False


def _parse_pdf(path: Path) -> ParsedBook:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    title = meta.get("/Title") or path.stem
    author = meta.get("/Author")

    # --- Strategy 1: outline / TOC ---
    outline = _pdf_outline_chapters(reader)

    pages_text: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        pages_text.append(t)

    if outline and len(outline) >= 2:
        chapters = _chapters_from_outline(outline, pages_text, title)
    else:
        chapters = _chapters_from_heuristic(pages_text)

    if not chapters:
        chapters = [Chapter(heading=None, text="")]

    return ParsedBook(title=title, author=author, chapters=chapters)


def _chapters_from_outline(
    outline: list[tuple[int, str]], pages_text: list[str], book_title: str
) -> list[Chapter]:
    """Build Chapter records from the PDF outline (page-indexed)."""
    chapters: list[Chapter] = []
    n_pages = len(pages_text)

    for i, (start, heading) in enumerate(outline):
        if start >= n_pages:
            continue
        end = outline[i + 1][0] if i + 1 < len(outline) else n_pages
        end = min(end, n_pages)
        body = sanitize_text(
            "\n".join((pages_text[p] or "").strip() for p in range(start, end))
        )
        if not body:
            continue
        chapters.append(Chapter(heading=sanitize_text(heading)[:140], text=body))

    if not chapters:
        return []
    return chapters


def _chapters_from_heuristic(pages_text: list[str]) -> list[Chapter]:
    """Fallback: detect headings by ALL-CAPS / 'Chapter N' on the first non-empty
    line of a page."""
    chapters: list[Chapter] = []
    current_heading: str | None = None
    current_text: list[str] = []

    def flush() -> None:
        text = sanitize_text("\n".join(current_text))
        if text:
            chapters.append(Chapter(heading=current_heading, text=text))

    for page_text in pages_text:
        page_text = sanitize_text(page_text)
        if not page_text:
            continue
        first_line = page_text.splitlines()[0].strip() if page_text else ""
        if _looks_like_heading(first_line):
            flush()
            current_text = []
            current_heading = first_line[:140]
        current_text.append(page_text)
    flush()

    # If we ended up with one giant "no heading" chapter and many pages,
    # split every ~10 pages as a "Section N" so the reader still has nav.
    if len(chapters) <= 1 and len(pages_text) > 20:
        return _split_into_sections(pages_text, pages_per_section=8)
    return chapters


def _split_into_sections(pages_text: list[str], *, pages_per_section: int = 8) -> list[Chapter]:
    chapters: list[Chapter] = []
    for i in range(0, len(pages_text), pages_per_section):
        chunk = pages_text[i : i + pages_per_section]
        body = sanitize_text("\n".join((p or "").strip() for p in chunk))
        if body:
            label = f"Pages {i+1}–{min(i + pages_per_section, len(pages_text))}"
            chapters.append(Chapter(heading=label, text=body))
    return chapters


# --------------------------------------------------------------------- docx


def _parse_docx(path: Path) -> ParsedBook:
    from docx import Document  # type: ignore

    doc = Document(str(path))
    title = path.stem
    author = None
    try:
        cp = doc.core_properties
        title = cp.title or path.stem
        author = cp.author
    except Exception:  # noqa: BLE001
        pass

    chapters: list[Chapter] = []
    current_heading: str | None = None
    current_text: list[str] = []

    def flush() -> None:
        text = sanitize_text("\n".join(current_text))
        if text:
            chapters.append(Chapter(heading=current_heading, text=text))

    for para in doc.paragraphs:
        style = (para.style.name or "").lower() if para.style else ""
        text = sanitize_text(para.text)
        if not text:
            continue
        if style.startswith("heading"):
            flush()
            current_text = []
            current_heading = text[:120]
        else:
            current_text.append(text)
    flush()

    # Also try to extract tables as plain text rows (very lightweight).
    try:
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(sanitize_text(cell.text) for cell in row.cells)
                if row_text.strip():
                    chapters.append(Chapter(heading=None, text=row_text))
    except Exception:  # noqa: BLE001
        pass

    if not chapters:
        chapters = [Chapter(heading=None, text="")]
    return ParsedBook(title=title, author=author, chapters=chapters)


# --------------------------------------------------------------------- txt


def _parse_txt(path: Path) -> ParsedBook:
    title = path.stem
    author = None
    text = path.read_text(encoding="utf-8", errors="replace")
    # Best effort: lines starting with "# " are headings.
    chapters: list[Chapter] = []
    current_heading: str | None = None
    current_text: list[str] = []

    def flush() -> None:
        body = "\n".join(current_text).strip()
        if body:
            chapters.append(Chapter(heading=current_heading, text=body))

    for line in text.splitlines():
        if line.startswith("# "):
            flush()
            current_text = []
            current_heading = line[2:].strip()[:120]
        else:
            current_text.append(line)
    flush()

    if not chapters:
        chapters = [Chapter(heading=None, text="")]
    return ParsedBook(title=title, author=author, chapters=chapters)


# --------------------------------------------------------------------- dispatch


_PARSERS = {
    "epub": _parse_epub,
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "txt": _parse_txt,
}


def parse(path: Path) -> ParsedBook:
    fmt = detect_format(path)
    parser = _PARSERS[fmt]
    return parser(path)
