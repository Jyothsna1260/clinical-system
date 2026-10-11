"""Web Research step (supports Agent F, the Reviewer).

For unresolved criteria whose wording has no definition in the protocol (a condition such as
"severe renal impairment", or a free-text rule with no machine-readable form), search the web
for how the term is defined and attach the top results as external references.

Only the criterion wording is sent to the search provider, never patient data. The references
are context for the human reviewer: they never change a criterion's status or the decision.
"""

import logging

from app.schemas.clinical import Criterion, CriterionEvaluation, ExternalReference
from app.services.web_search import WebSearchClient

log = logging.getLogger(__name__)

RESULTS_PER_QUERY = 2


def _needs_context(criterion: Criterion, evaluation: CriterionEvaluation) -> bool:
    if evaluation.status != "UNKNOWN" or evaluation.comparison_method == "deterministic":
        return False
    rule = criterion.normalized_rule
    # A missing lab value is a patient-data gap; searching the web cannot resolve it.
    return rule is None or rule.attribute == "condition"


def research_ambiguous_criteria(
    criteria: list[Criterion],
    evaluations: list[CriterionEvaluation],
    client: WebSearchClient | None,
    max_queries: int = 3,
) -> tuple[list[ExternalReference], list[str]]:
    """External references for ambiguous unresolved criteria (exclusions first), plus warnings."""
    if client is None:
        return [], []
    by_id = {c.criterion_id: c for c in criteria}
    targets = [e for e in sorted(evaluations, key=lambda e: e.category != "exclusion")
               if e.criterion_id in by_id and _needs_context(by_id[e.criterion_id], e)][:max_queries]
    refs: list[ExternalReference] = []
    warnings: list[str] = []
    for e in targets:
        wording = " ".join(by_id[e.criterion_id].original_text.split())[:160]
        query = f"{wording} clinical trial eligibility definition"
        try:
            results = client.search(query, RESULTS_PER_QUERY)
        except Exception as exc:  # search is optional context; a failure never fails the run
            log.warning("web search failed for %s: %s", e.criterion_id, exc)
            warnings.append(f"{e.criterion_id}: web search unavailable ({type(exc).__name__}).")
            continue
        for r in results:
            refs.append(ExternalReference(criterion_id=e.criterion_id, query=query, title=r["title"], url=r["url"],
                                          snippet=r.get("snippet", ""), provider=client.provider))
    return refs, warnings
