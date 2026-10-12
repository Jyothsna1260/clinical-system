"""Protocols whose criteria are ruled tables with IDs (I-01 / E-01) and qualified headings.

Uses the synthetic protocol_t2d_table.pdf; patients are built inline. Outcomes come from the
offline pipeline (rule-based extraction, deterministic comparators).
"""

import copy

import pytest

from app.agents.protocol_extraction import find_criteria_items, parse_rule
from app.rag.pdf_loader import PageText, load_pdf, pages_from_dicts

ELIGIBLE = {
    "as_of": "2026-10-01",
    "demographics": {"age": 52, "sex": "female"},
    "labs": [
        {"name": "HbA1c", "value": 8.4, "unit": "%", "observed_at": "2026-09-20"},
        {"name": "eGFR", "value": 72, "unit": "mL/min/1.73m2", "observed_at": "2026-09-20"},
        {"name": "Potassium", "value": 4.4, "unit": "mmol/L", "observed_at": "2026-09-20"},
    ],
    "diagnoses": [{"name": "Type 2 diabetes mellitus", "documented_at": "2019-05-14"}],
    "history": [
        {"condition": "Type 1 diabetes", "present": False},
        {"condition": "Pregnancy", "present": False},
        {"condition": "Breastfeeding", "present": False},
        {"condition": "Acute medical instability", "present": False},
    ],
}


@pytest.fixture(scope="module")
def pages(fixture_path):
    return [p.to_dict() for p in load_pdf(fixture_path("protocol_t2d_table.pdf"))]


@pytest.fixture(scope="module")
def fixture_path():
    from pathlib import Path

    root = Path(__file__).parent / "fixtures"
    return lambda name: str(root / name)


def _run(pages, patient):
    from app.workflow.graph import run_eligibility

    result = run_eligibility(run_id="t", trial_id="trial-t2d", pages=pages, patient_input=patient)["result"]
    return result, {e.criterion_id: e.status for e in result.inclusion_results + result.exclusion_results}


def test_table_rows_become_criteria_without_commentary_columns(pages):
    items = find_criteria_items(pages_from_dicts(pages))
    assert [i.category for i in items] == ["inclusion"] * 5 + ["exclusion"] * 4
    assert items[2].text == "HbA1c 7.5%–10.5% inclusive, measured within 90 days before assessment"
    assert not any("Dated result required" in i.text or "Exclude if documented" in i.text for i in items)
    # Sections 4 and 5 after the exclusion table are not swallowed as criteria.
    assert not any("Data Requirements" in i.text or "Screening Outcomes" in i.text for i in items)


def test_table_criteria_parse_to_rules(pages):
    from app.agents.protocol_extraction import extract_criteria

    result = extract_criteria(pages_from_dicts(pages), "trial-t2d")
    rules = {c.criterion_id: c.normalized_rule for c in result.criteria}
    assert all(r is not None for r in rules.values())
    r = rules["INC-03"]
    assert (r.attribute, r.value, r.value_max, r.inclusive) == ("hba1c", 7.5, 10.5, True)
    assert rules["INC-02"].value == ["type 2 diabetes"]
    assert rules["EXC-01"].value == ["type 1 diabetes"]
    assert rules["EXC-03"].value == ["acute medical instability"]
    assert rules["EXC-04"].attribute == "data_completeness"
    assert rules["EXC-04"].value == ["egfr", "hba1c", "potassium"]


def test_all_criteria_met_is_eligible(pages):
    result, s = _run(pages, ELIGIBLE)
    assert result.overall_status == "ELIGIBLE", result.final_explanation
    assert s["EXC-04"] == "NOT_TRIGGERED"


def test_type_1_diabetes_and_stale_potassium(pages):
    patient = copy.deepcopy(ELIGIBLE)
    patient["diagnoses"].append({"name": "Type 1 diabetes", "documented_at": "2008-02-01"})
    patient["history"] = [h for h in patient["history"] if h["condition"] != "Type 1 diabetes"]
    patient["labs"][2]["observed_at"] = "2026-03-01"
    result, s = _run(pages, patient)
    assert result.overall_status == "NOT_ELIGIBLE"
    assert s["EXC-01"] == "TRIGGERED"
    assert s["INC-05"] == "UNKNOWN" and s["EXC-04"] == "UNKNOWN"  # stale potassium: insufficient data


def test_hba1c_below_range_with_type_2_undocumented(pages):
    patient = copy.deepcopy(ELIGIBLE)
    patient["labs"][0]["value"] = 6.1
    patient["diagnoses"] = [{"name": "Prediabetes"}]
    result, s = _run(pages, patient)
    assert result.overall_status == "NOT_ELIGIBLE"
    assert s["INC-03"] == "UNSATISFIED" and s["INC-02"] == "UNKNOWN"


def test_type_2_diabetes_does_not_match_type_1():
    from app.engine.vocabulary import condition_matches

    assert not condition_matches("type 1 diabetes", "Type 2 diabetes mellitus")
    assert condition_matches("type 2 diabetes", "T2DM")


@pytest.mark.parametrize("text", ["in 30 days of screening", "E coli bacteremia", "Inclusion of minors"])
def test_continuation_lines_are_not_criterion_ids(text):
    pages = [PageText(1, f"Exclusion Criteria\n1. Active infection treated\n{text}\n2. Pregnancy.")]
    items = find_criteria_items(pages)
    assert len(items) == 2 and text in items[0].text


def test_numbered_list_items_in_title_case_are_not_section_ends():
    text = "Exclusion Criteria\n1. Pregnancy or breastfeeding.\n2. Known Type 1 Diabetes\n3. Severe Renal Impairment"
    pages = [PageText(1, text)]
    assert len(find_criteria_items(pages)) == 3


def test_stored_pages_without_tables_still_load():
    assert pages_from_dicts([{"page": 1, "text": "x"}])[0].tables == ()


def test_lab_range_without_inclusivity_is_flagged():
    parsed = parse_rule("Potassium 3.5-5.0 mmol/L")
    assert parsed.rule is not None and parsed.rule.inclusive is None
    assert any("inclusive" in r for r in parsed.review_reasons)
