"""Evidence retrieval with validation.

For each criterion: the primary citation is the criterion's own verified excerpt on its
source page; then the top-3 retrieved chunks are kept only if their text contains the
criterion's excerpt or its key terms (retrieval validation). PDF text is untrusted data
and is only ever quoted, never interpreted as instructions.
"""

import re

from app.agents.protocol_extraction import excerpt_on_page
from app.engine.vocabulary import LAB_ALIASES, normalize_text
from app.rag.chunker import Chunk
from app.rag.index import tokenize
from app.schemas.clinical import Criterion, EvidenceReference

_STOPWORDS = {
    "the", "and", "or", "of", "to", "in", "a", "an", "be", "must", "not", "with", "for", "as", "by", "is",
    "are", "at", "on", "any", "than", "least", "below", "above", "less", "more", "years", "patients",
    "patient", "defined", "inclusive", "who", "have", "has", "within", "prior", "history",
}


def key_terms(criterion: Criterion) -> list[str]:
    """Distinctive terms that a supporting chunk must contain."""
    terms: list[str] = []
    rule = criterion.normalized_rule
    text = normalize_text(criterion.original_text)
    if rule is not None and rule.attribute in LAB_ALIASES:
        aliases = sorted(LAB_ALIASES[rule.attribute], key=len, reverse=True)
        alias = next((a for a in aliases if a in text), rule.attribute)
        terms.append(alias)
    if rule is not None and isinstance(rule.value, (int, float)):
        terms.append(f"{rule.value:g}")
    words = [w for w in tokenize(text) if w not in _STOPWORDS and not re.fullmatch(r"\d+(\.\d+)?", w) and len(w) > 2]
    for w in words:
        if w not in terms:
            terms.append(w)
        if len(terms) >= 4:
            break
    return terms


def chunk_supports(chunk_text: str, criterion: Criterion, terms: list[str]) -> bool:
    if excerpt_on_page(criterion.source_excerpt, chunk_text):
        return True
    hay = normalize_text(chunk_text)
    return bool(terms) and all(t in hay for t in terms)


def _excerpt_chunk(chunks: list[Chunk], criterion: Criterion) -> str | None:
    on_page = [c for c in chunks if c.page == criterion.source_page]
    for c in on_page:
        if excerpt_on_page(criterion.source_excerpt, c.text):
            return c.chunk_id
    head = normalize_text(criterion.source_excerpt)[:60]
    for c in on_page:
        if head and head in normalize_text(c.text):
            return c.chunk_id
    return on_page[0].chunk_id if on_page else None


def retrieve_evidence(
    criteria: list[Criterion],
    index,
    pages_by_no: dict[int, str],
    k: int = 3,
) -> dict[str, list[EvidenceReference]]:
    evidence: dict[str, list[EvidenceReference]] = {}
    chunks: list[Chunk] = list(getattr(index, "chunks", []))
    for c in criteria:
        refs: list[EvidenceReference] = []
        page_text = pages_by_no.get(c.source_page, "")
        if excerpt_on_page(c.source_excerpt, page_text):
            refs.append(EvidenceReference(
                page=c.source_page, excerpt=c.source_excerpt, chunk_id=_excerpt_chunk(chunks, c),
                source="protocol_citation", score=1.0,
            ))
        if index is not None:
            terms = key_terms(c)
            for chunk, score in index.search(c.original_text, k=k):
                if not chunk_supports(chunk.text, c, terms):
                    continue
                if any(r.page == chunk.page for r in refs):
                    continue  # same page already cited verbatim
                excerpt = re.sub(r"\s+", " ", chunk.text).strip()
                refs.append(EvidenceReference(
                    page=chunk.page, excerpt=excerpt[:400], chunk_id=chunk.chunk_id,
                    source="retrieval", score=round(score, 4),
                ))
        evidence[c.criterion_id] = refs
    return evidence
