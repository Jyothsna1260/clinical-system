"""Clinical NLP helpers (optional BioBERT concept matching)."""

from functools import lru_cache

from app.config import Settings
from app.nlp.clinical import ConceptMatcher, SentenceTransformerConceptMatcher


@lru_cache
def _matcher(model_name: str, threshold: float) -> SentenceTransformerConceptMatcher:
    return SentenceTransformerConceptMatcher(model_name, threshold)


def get_concept_matcher(settings: Settings) -> ConceptMatcher | None:
    """The process-wide matcher, or None when CLINICAL_NLP_ENABLED is false."""
    if not settings.clinical_nlp_enabled:
        return None
    return _matcher(settings.clinical_nlp_model, settings.clinical_nlp_threshold)


__all__ = ["ConceptMatcher", "SentenceTransformerConceptMatcher", "get_concept_matcher"]
