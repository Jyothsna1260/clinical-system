"""Page-level chunking that keeps trial, document, page and section metadata."""

import re
from dataclasses import asdict, dataclass

from app.rag.pdf_loader import PageText

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

_SECTION_HEADINGS = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s+)?(inclusion criteria|exclusion criteria)\s*:?\s*$", re.I | re.M
)


@dataclass
class Chunk:
    chunk_id: str
    trial_id: str
    document_id: str
    page: int
    section: str | None
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _section_at(text: str, position: int, carried: str | None) -> str | None:
    section = carried
    for m in _SECTION_HEADINGS.finditer(text):
        if m.start() <= position:
            section = m.group(1).lower()
    return section


def chunk_pages(
    pages: list[PageText],
    trial_id: str,
    document_id: str,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    carried: str | None = None
    step = max(1, size - overlap)
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        starts = list(range(0, max(1, len(text) - overlap), step)) or [0]
        for i, start in enumerate(starts):
            piece = text[start : start + size]
            if not piece.strip():
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"{document_id}:p{page.page}:c{i}",
                    trial_id=trial_id,
                    document_id=document_id,
                    page=page.page,
                    section=_section_at(text, start, carried),
                    text=piece,
                )
            )
        carried = _section_at(text, len(text), carried)
    return chunks
