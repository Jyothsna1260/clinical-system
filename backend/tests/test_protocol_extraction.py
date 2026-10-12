"""Agent A: section detection, rule parsing, page citation and excerpt verification."""

from app.agents.protocol_extraction import extract_criteria, extract_rule_based, parse_rule
from app.rag.pdf_loader import PageText, load_pdf


def test_pdf_criteria_with_page_numbers(fixture_path):
    pages = load_pdf(fixture_path("protocol_renal.pdf"))
    assert len(pages) == 3
    criteria = extract_rule_based(pages, "t1")
    ids = [c.criterion_id for c in criteria]
    assert ids == ["INC-01", "INC-02", "EXC-01", "EXC-02"]
    by = {c.criterion_id: c for c in criteria}
    assert by["INC-01"].source_page == 2 and by["INC-02"].source_page == 2
    assert by["EXC-01"].source_page == 3 and by["EXC-02"].source_page == 3

    age = by["INC-01"].normalized_rule
    assert (age.attribute, age.operator, age.value, age.value_max, age.inclusive) == ("age", "between", 18, 70, True)
    egfr = by["INC-02"].normalized_rule
    assert (egfr.attribute, egfr.operator, egfr.value, egfr.unit) == ("egfr", "gte", 30, "mL/min/1.73m2")
    assert by["EXC-01"].normalized_rule.operator == "present"
    assert by["EXC-01"].requires_human_review is True  # "severe" without numeric definition
    assert by["EXC-02"].normalized_rule.value == ["pregnancy", "breastfeeding"]
    for c in criteria:
        page_text = pages[c.source_page - 1].text
        assert " ".join(c.source_excerpt.split()).lower() in " ".join(page_text.split()).lower()


def test_defined_exclusion_is_numeric(fixture_path):
    criteria = extract_rule_based(load_pdf(fixture_path("protocol_renal_defined.pdf")), "t1")
    exc1 = next(c for c in criteria if c.criterion_id == "EXC-01")
    r = exc1.normalized_rule
    assert (r.attribute, r.operator, r.value) == ("egfr", "lt", 30)
    assert exc1.requires_human_review is False


def test_ambiguous_criterion_requires_review():
    pages = [PageText(1, "Inclusion Criteria\n1. Adequate hepatic function.\n2. Age at least 18 years.")]
    criteria = extract_rule_based(pages, "t1")
    adequate = criteria[0]
    assert adequate.requires_human_review is True
    assert any("adequate" in r for r in adequate.review_reasons)
    assert criteria[1].normalized_rule.operator == "gte"


def test_unstated_range_inclusivity_flagged():
    parsed = parse_rule("Age 18 to 65 years.")
    assert parsed.rule.inclusive is None
    assert parsed.review_reasons


def test_rule_phrases():
    assert parse_rule("Serum creatinine less than 1.5 mg/dL").rule.operator == "lt"
    assert parse_rule("ALT not exceeding 120 U/L").rule.operator == "lte"
    assert parse_rule("Platelet count at least 100 x10^9/L").rule.value == 100
    assert parse_rule("eGFR of 45 mL/min/1.73m2 or more").rule.operator == "gte"
    assert parse_rule("ALT > 3 x ULN").rule is None  # relative to ULN needs reference range
    assert parse_rule("Able to provide written informed consent.").rule is None


class _FakeLLM:
    provider, model = "fake", "fake"

    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, system, user, schema):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_llm_excerpt_not_on_cited_page_is_flagged():
    pages = [PageText(1, "Synopsis"), PageText(2, "Inclusion Criteria\n1. Age 18 to 70 years inclusive.")]
    llm = _FakeLLM({"criteria": [{
        "category": "inclusion", "original_text": "Age 18 to 70 years inclusive.", "source_page": 1,
        "source_excerpt": "Age 18 to 70 years inclusive.", "attribute": "age", "operator": "between",
        "value": 18, "value_terms": None, "value_max": 70, "unit": "years", "inclusive": True, "ambiguity_reason": None,
    }]})
    result = extract_criteria(pages, "t1", llm)
    assert result.method == "llm"
    c = result.criteria[0]
    assert c.requires_human_review is True
    assert c.extraction_confidence <= 0.3
    assert any("could not be verified on cited page 1" in r for r in c.review_reasons)


def test_invalid_llm_output_falls_back_to_rules(fixture_path):
    from app.services.llm import LLMError

    pages = load_pdf(fixture_path("protocol_renal.pdf"))
    for bad in (LLMError("model returned invalid JSON"), {"criteria": "not-a-list"}, {"unexpected": 1}):
        result = extract_criteria(pages, "t1", _FakeLLM(bad))
        assert result.method == "rule_based"
        assert len(result.criteria) == 4
