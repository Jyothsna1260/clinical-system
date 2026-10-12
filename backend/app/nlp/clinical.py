"""Clinical NLP: BioBERT sentence similarity between criterion conditions and patient records.

The deterministic vocabulary (``engine/vocabulary.py``) only recognizes the synonyms it lists, so
a patient documented with "chronic kidney disease stage 4" is not linked to an exclusion for
"severe renal impairment". When enabled, this matcher embeds both phrases with a BioBERT model
fine-tuned for clinical sentence similarity and reports pairs above a threshold.

It is used only where it is appropriate for a support tool: an unresolved condition criterion
gains a review note naming the possibly related record. A similarity score never changes a
criterion's status, never confirms a diagnosis and never makes a patient eligible or ineligible.
"""

import logging
import threading
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


class ConceptMatcher(Protocol):
    name: str

    def similar(self, term: str, candidates: list[str]) -> list[tuple[str, float]]:
        """Candidates whose similarity to ``term`` reaches the threshold, best first."""
        ...


class SentenceTransformerConceptMatcher:
    """Cosine similarity over a sentence-transformers model (BioBERT by default), loaded on first use."""

    def __init__(self, model_name: str, threshold: float = 0.75):
        self.model_name = model_name
        self.name = model_name.rsplit("/", 1)[-1]
        self.threshold = threshold
        self._model = None
        self._failed = False
        self._cache: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None and not self._failed:
                try:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name, device="cpu")
                    log.info("clinical NLP model loaded: %s", self.model_name)
                except Exception as exc:  # offline, missing package, out of memory
                    self._failed = True
                    log.warning("clinical NLP model %s unavailable, matcher disabled: %s", self.model_name, exc)
            return self._model

    def _embed(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            vectors = self._load().encode(missing, normalize_embeddings=True, convert_to_numpy=True)
            self._cache.update(zip(missing, vectors))
        return np.stack([self._cache[t] for t in texts])

    def similar(self, term: str, candidates: list[str]) -> list[tuple[str, float]]:
        candidates = [c for c in dict.fromkeys(candidates) if c.strip()]
        if not candidates or self._load() is None:
            return []
        vectors = self._embed([term, *candidates])
        scores = vectors[1:] @ vectors[0]
        hits = [(c, float(s)) for c, s in zip(candidates, scores) if s >= self.threshold]
        return sorted(hits, key=lambda h: h[1], reverse=True)
