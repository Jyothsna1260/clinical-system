"""Controlled clinical vocabulary: lab aliases, clinical domains and condition synonyms.

Everything here is a deterministic lookup table, so behaviour is reviewable and testable.
"""

import re

# canonical attribute -> aliases as they appear in protocols or patient records (lower case)
LAB_ALIASES: dict[str, list[str]] = {
    "egfr": ["egfr", "e-gfr", "estimated gfr", "estimated glomerular filtration rate",
             "glomerular filtration rate", "gfr"],
    "creatinine": ["serum creatinine", "creatinine", "scr"],
    "crcl": ["creatinine clearance", "crcl"],
    "alt": ["alanine aminotransferase", "alanine transaminase", "alt", "sgpt"],
    "ast": ["aspartate aminotransferase", "aspartate transaminase", "ast", "sgot"],
    "bilirubin": ["total bilirubin", "bilirubin", "tbili"],
    "hemoglobin": ["hemoglobin", "haemoglobin", "hgb", "hb"],
    "platelets": ["platelet count", "platelets", "plt"],
    "anc": ["absolute neutrophil count", "anc"],
    "hba1c": ["hba1c", "glycated hemoglobin", "hemoglobin a1c", "a1c"],
    "lvef": ["left ventricular ejection fraction", "ejection fraction", "lvef"],
    "qtc": ["qtcf", "qtc interval", "qtc"],
    "bmi": ["body mass index", "bmi"],
    "weight": ["body weight", "weight"],
    "potassium": ["serum potassium", "potassium"],
    "sodium": ["serum sodium", "sodium"],
}

ATTRIBUTE_LABELS: dict[str, str] = {
    "age": "Age",
    "egfr": "eGFR",
    "creatinine": "Serum creatinine",
    "crcl": "Creatinine clearance",
    "alt": "ALT",
    "ast": "AST",
    "bilirubin": "Total bilirubin",
    "hemoglobin": "Hemoglobin",
    "platelets": "Platelet count",
    "anc": "ANC",
    "hba1c": "HbA1c",
    "lvef": "LVEF",
    "qtc": "QTc",
    "bmi": "BMI",
    "weight": "Body weight",
    "potassium": "Potassium",
    "sodium": "Sodium",
    "condition": "Documented condition",
}

# clinical domain -> keywords/attributes used to relate criteria to each other
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "renal": ["egfr", "creatinine", "crcl", "renal", "kidney", "nephro", "dialysis", "glomerular"],
    "hepatic": ["alt", "ast", "bilirubin", "liver", "hepatic", "hepatitis", "cirrhosis"],
    "cardiac": ["lvef", "qtc", "cardiac", "heart", "myocardial", "arrhythmia", "ejection fraction", "angina"],
    "hematologic": ["hemoglobin", "platelets", "anc", "neutrophil", "anemia", "anaemia", "thrombocytopenia"],
    "metabolic": ["hba1c", "diabetes", "glucose", "bmi", "weight", "obesity"],
    "reproductive": ["pregnan", "breastfeed", "breast-feed", "lactat", "childbearing", "contracept"],
    "electrolytes": ["potassium", "sodium", "hyperkalemia", "hyponatremia"],
}

# condition synonym groups; the first entry is the canonical name
CONDITION_SYNONYMS: list[list[str]] = [
    ["severe renal impairment", "severe kidney impairment", "severe chronic kidney disease", "ckd stage 4",
     "ckd stage 5", "chronic kidney disease stage 4", "chronic kidney disease stage 5", "end-stage renal disease",
     "end stage renal disease", "esrd", "kidney failure", "renal failure"],
    ["pregnancy", "pregnant"],
    ["breastfeeding", "breast-feeding", "lactation", "lactating", "nursing"],
    ["hepatic impairment", "liver impairment", "liver dysfunction"],
    ["heart failure", "congestive heart failure", "chf"],
    ["type 2 diabetes mellitus", "type 2 diabetes", "t2dm", "diabetes mellitus type 2"],
    ["type 1 diabetes mellitus", "type 1 diabetes", "t1dm", "diabetes mellitus type 1"],
    ["myocardial infarction", "heart attack", "mi"],
]

# conditions that cannot apply to male patients (deterministic, documented rule)
SEX_SPECIFIC_FEMALE_CONDITIONS = {"pregnancy", "breastfeeding"}

# qualifiers that make a criterion ambiguous unless a numeric definition is given
AMBIGUOUS_QUALIFIERS = [
    "adequate", "sufficient", "significant", "clinically significant", "appropriate", "normal",
    "severe", "moderate", "mild", "uncontrolled", "acceptable", "reasonable", "poor", "recent",
]

_ws = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Lower-case, unify dashes/quotes and collapse whitespace."""
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = text.replace("’", "'").replace(" ", " ")
    return _ws.sub(" ", text).strip().lower()


def canonical_lab(name: str) -> str | None:
    """Map a lab name from a patient record to its canonical attribute."""
    n = normalize_text(name).strip(" .:")
    for attr, aliases in LAB_ALIASES.items():
        if n == attr or n in aliases:
            return attr
    # Substring match: the longest alias wins ("creatinine clearance (cockcroft-gault)" is CrCl).
    hits = [(len(alias), attr) for attr, aliases in LAB_ALIASES.items() for alias in aliases
            if len(alias) > 3 and alias in n]
    return max(hits)[1] if hits else None


def find_lab_in_text(text: str) -> tuple[str, str] | None:
    """Find the first lab attribute mentioned in protocol text -> (attribute, matched alias)."""
    t = normalize_text(text)
    best: tuple[int, str, str] | None = None
    for attr, aliases in LAB_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            m = re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", t)
            # Earliest mention wins; at the same position the longer alias is more specific
            # ("creatinine clearance" is CrCl, not creatinine).
            if m and (best is None or (m.start(), -len(alias)) < (best[0], -len(best[2]))):
                best = (m.start(), attr, alias)
                break
    return (best[1], best[2]) if best else None


def canonical_condition(term: str) -> str:
    n = normalize_text(term).strip(" .;:")
    for group in CONDITION_SYNONYMS:
        if n in group:
            return group[0]
    return n


def condition_matches(criterion_term: str, patient_term: str) -> bool:
    """True when a patient's documented condition is the same concept as the criterion term."""
    a = canonical_condition(criterion_term)
    b = canonical_condition(patient_term)
    if a == b:
        return True
    # A documented condition matches when it contains the full criterion concept,
    # e.g. "severe renal impairment (stage 4)" matches "severe renal impairment".
    return bool(re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", normalize_text(patient_term)))


def domains_for(text: str, attributes: list[str] | None = None) -> set[str]:
    hay = normalize_text(text) + " " + " ".join(attributes or [])
    found = set()
    for domain, keys in DOMAIN_KEYWORDS.items():
        for k in keys:
            # short keys (alt, ast, anc) must match whole words; longer ones may be stems
            tail = r"(?![a-z])" if len(k) <= 4 else ""
            if re.search(r"(?<![a-z])" + re.escape(k) + tail, hay):
                found.add(domain)
                break
    return found


def domain_attributes(domain: str) -> list[str]:
    return [k for k in DOMAIN_KEYWORDS.get(domain, []) if k in LAB_ALIASES]


def label(attribute: str) -> str:
    return ATTRIBUTE_LABELS.get(attribute, attribute)
