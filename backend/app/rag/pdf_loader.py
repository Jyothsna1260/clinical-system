"""PDF text extraction with PyMuPDF, one entry per page (1-based page numbers)."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

PDF_MAGIC = b"%PDF-"
log = logging.getLogger(__name__)

# Table detection is comparatively slow, so it only runs on pages that can hold eligibility criteria.
_CRITERIA_HINT = re.compile(r"inclusion|exclusion|eligibility", re.IGNORECASE)


class PDFReadError(ValueError):
    pass


class PDFTooManyPagesError(PDFReadError):
    pass


Table = tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    # Ruled tables detected on the page, as rows of cell text (None cells become "").
    tables: tuple[Table, ...] = field(default=())

    def to_dict(self) -> dict:
        out: dict = {"page": self.page, "text": self.text}
        if self.tables:
            out["tables"] = [[list(row) for row in t] for t in self.tables]
        return out


def _page_tables(page) -> tuple[Table, ...]:
    try:
        found = page.find_tables()
    except Exception as exc:  # layout analysis is best effort; plain text is still available
        log.warning("table detection failed on page %s: %s", page.number + 1, exc)
        return ()
    return tuple(
        tuple(tuple("" if cell is None else str(cell) for cell in row) for row in t.extract())
        for t in found.tables
    )


def is_pdf_bytes(data: bytes) -> bool:
    # The header must appear within the first 1024 bytes per the PDF spec.
    return PDF_MAGIC in data[:1024]


def load_pdf_bytes(data: bytes, max_pages: int | None = None) -> list[PageText]:
    if not is_pdf_bytes(data):
        raise PDFReadError("file is not a PDF (missing %PDF header)")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several exception types for corrupt files
        raise PDFReadError(f"unreadable PDF: {exc}") from exc
    try:
        if doc.needs_pass:
            raise PDFReadError("encrypted PDFs are not supported")
        if max_pages is not None and doc.page_count > max_pages:
            raise PDFTooManyPagesError(f"PDF has {doc.page_count} pages; the limit is {max_pages}")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text")
            tables = _page_tables(page) if _CRITERIA_HINT.search(text) else ()
            pages.append(PageText(page=i + 1, text=text, tables=tables))
    except PDFReadError:
        raise
    except Exception as exc:
        raise PDFReadError(f"unreadable PDF: {exc}") from exc
    finally:
        doc.close()
    if not pages:
        raise PDFReadError("PDF has no pages")
    if not any(p.text.strip() for p in pages):
        raise PDFReadError("PDF contains no extractable text (scanned documents are not supported)")
    return pages


def load_pdf(path: str | Path) -> list[PageText]:
    return load_pdf_bytes(Path(path).read_bytes())


def pages_from_dicts(items: list[dict]) -> list[PageText]:
    return [
        PageText(
            page=int(p["page"]),
            text=str(p["text"]),
            tables=tuple(tuple(tuple(str(c) for c in row) for row in t) for t in p.get("tables") or ()),
        )
        for p in items
    ]
