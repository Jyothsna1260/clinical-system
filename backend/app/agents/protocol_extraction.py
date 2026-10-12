"""Agent A - Protocol Extraction.

Reads per-page protocol text, finds the Inclusion and Exclusion sections, and turns each
numbered/bulleted item into a validated `Criterion` with its real page number and an
excerpt that is verified to appear on that page.

The LLM path (when configured) proposes criteria as strict JSON; the rule-based path is
always available and is used whenever the LLM is unavailable or its output fails
validation. Neither path may invent a rule or a page: any excerpt that cannot be found
on its cited page is flagged for human review with lowered confidence.
"""

import logging
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.config import get_settings
from app.engine.units import CANONICAL_UNITS, UNIT_PATTERN, normalize_unit
from app.engine.vocabulary import AMBIGUOUS_QUALIFIERS, find_lab_in_text, normalize_text
from app.rag.pdf_loader import PageText
from app.schemas.clinical import Criterion, NormalizedRule
from app.services.llm import UNTRUSTED_DATA_RULE, LLMClient, LLMError

log = logging.getLogger(__name__)

# "Inclusion Criteria", "5.1 Exclusion criteria:", "2. Illustrative Inclusion Criteria", "Key Exclusion Criteria"
_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:[a-z]+\s+){0,3}?(inclusion|exclusion)\s+criteria\s*:?\s*$", re.IGNORECASE
)
# A numbered, title-cased section heading ("4. Required Data for Screening") ends a criteria section.
_SMALL_WORDS = {"and", "of", "for", "the", "to", "in", "on", "or", "a", "an", "with", "by", "at", "&", "/", "-"}
_NUMBERED_HEADING = re.compile(r"^\s*(\d+)(?:\.\d+)*\.?\s+(\S.{2,70})$")
# Upper-case criterion identifiers used in tables and lists: I-01, E-3, INC-01, EXC 2, IC1, EC12.
_ITEM_ID = re.compile(r"^\s*((?:INC|EXC|IC|EC|I|E)(?:-|\s)?\d{1,3}[a-z]?)(?:[.:)]\s*|\s+|$)(.*)$")
_END_HEADINGS = (
    "study design", "study procedures", "study treatment", "treatment plan", "statistical",
    "withdrawal", "concomitant", "assessments", "schedule of", "endpoints", "objectives",
    "references", "appendix", "randomization", "randomisation", "safety reporting", "discontinuation",
)
_ITEM = re.compile(r"^\s*(?:(\d{1,3})[.)]|[•▪●\-\*])\s+(\S.*)$")
_FOOTER = re.compile(
    r"^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*/\s*\d+|confidential.*)\s*$|\bpage\s+\d+\s+of\s+\d+\b",
    re.IGNORECASE,
)
_NUM = r"(-?\d+(?:\.\d+)?)"

_SEMANTIC_MARKERS = ("able to", "willing", "consent", "agree to", "comply", "understand")


@dataclass
class RawItem:
    category: str
    page: int
    text: str
    excerpt: str


@dataclass
class ParsedRule:
    rule: NormalizedRule | None
    required_attributes: list[str]
    confidence: float
    review_reasons: list[str] = field(default_factory=list)
    secondary: NormalizedRule | None = None
    combinator: str | None = None  # "and" | "or" when `secondary` is set


@dataclass
class ExtractionResult:
    criteria: list[Criterion]
    method: str
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- helpers


def normalize_ws(text: str) -> str:
    return normalize_text(text)


def excerpt_on_page(excerpt: str, page_text: str) -> bool:
    """Whitespace/case-normalized check that an excerpt literally appears on a page."""
    e = normalize_ws(excerpt)
    return bool(e) and e in normalize_ws(page_text)


def _is_end_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 70 or s.endswith((".", ",", ";")) or _ITEM.match(s):
        return False
    low = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", s.lower())
    return any(low.startswith(h) for h in _END_HEADINGS)


def _numbered_section_heading(line: str) -> int | None:
    """Section number if the line looks like a numbered, title-cased heading, else None."""
    m = _NUMBERED_HEADING.match(line)
    if not m:
        return None
    title = m.group(2).strip()
    if title.endswith((".", ",", ";", ":")) or re.search(r"\d", title):
        return None
    words = title.split()
    if len(words) < 2:
        return None
    if all(w[0].isupper() or w.lower() in _SMALL_WORDS for w in words):
        return int(m.group(1))
    return None


@dataclass
class _TableRow:
    text: str
    lines: list[str]  # every non-empty text line the row's cells contribute to the page text


_CRITERIA_COLUMN = re.compile(r"criteri|description|eligibility|requirement")


def _criteria_table_rows(page: PageText) -> dict[str, _TableRow]:
    """Rows of criteria tables on a page, keyed by the normalized first line of the criterion cell.

    A criteria table has a header row with a column named like "criterion"/"criteria"/
    "description"/"eligibility". Only the criterion column becomes criterion text; ID and
    commentary columns (e.g. "Prototype rule") are kept out of it.
    """
    rows: dict[str, _TableRow] = {}
    for table in page.tables:
        if len(table) < 2:
            continue
        header = [normalize_ws(c) for c in table[0]]
        col = next((i for i, h in enumerate(header) if _CRITERIA_COLUMN.search(h)), None)
        if col is None:
            continue
        for row in table[1:]:
            if col >= len(row) or not row[col].strip():
                continue
            cell_lines = [ln.strip() for c in row for ln in c.splitlines() if ln.strip()]
            first = row[col].strip().splitlines()[0].strip()
            rows[normalize_ws(first)] = _TableRow(text=re.sub(r"\s+", " ", row[col]).strip(), lines=cell_lines)
    return rows


def _boilerplate_lines(pages: list[PageText]) -> set[str]:
    """Running headers/footers: lines that repeat on several pages once digits are masked."""
    if len(pages) < 2:
        return set()
    seen: dict[str, set[int]] = {}
    for page in pages:
        for line in page.text.splitlines():
            key = re.sub(r"\d+", "#", line.strip().lower())
            if key and not _ITEM.match(line) and not _HEADING.match(line):
                seen.setdefault(key, set()).add(page.page)
    return {k for k, on in seen.items() if len(on) >= max(2, (len(pages) + 1) // 2)}


def find_criteria_items(pages: list[PageText]) -> list[RawItem]:
    """Walk pages line by line and collect items under inclusion/exclusion headings.

    Items are numbered or bulleted list entries, lines starting with a criterion ID (I-01, EXC-2),
    or rows of a criteria table detected on the page (criterion column only).
    """
    items: list[RawItem] = []
    boilerplate = _boilerplate_lines(pages)
    section: str | None = None
    current: RawItem | None = None
    last_number: int | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            current.text = re.sub(r"\s+", " ", current.text).strip()
            current.excerpt = re.sub(r"\s+", " ", current.excerpt).strip()
            if current.text:
                items.append(current)
        current = None

    for page in pages:
        table_rows = _criteria_table_rows(page)
        skip: list[str] = []  # lines already covered by an emitted table row (header cells too)
        for t in page.tables:
            if t and any(_CRITERIA_COLUMN.search(normalize_ws(c)) for c in t[0]):
                skip.extend(ln.strip() for c in t[0] for ln in c.splitlines() if ln.strip())
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line or _FOOTER.search(line) or re.sub(r"\d+", "#", line.lower()) in boilerplate:
                continue
            heading = _HEADING.match(line)
            if heading:
                flush()
                section = heading.group(1).lower()
                last_number = None
                continue
            if section and _is_end_heading(line):
                flush()
                section = None
                continue
            if not section:
                continue
            row = table_rows.pop(normalize_ws(line), None)
            if row is not None:
                flush()
                items.append(RawItem(category=section, page=page.page, text=row.text, excerpt=row.text))
                rest = list(row.lines)
                if line in rest:
                    rest.remove(line)
                skip.extend(rest)
                continue
            if line in skip:
                skip.remove(line)
                continue
            number = _numbered_section_heading(line)
            if number is not None and number != (last_number or 0) + 1:
                flush()
                section = None
                continue
            item = _ITEM.match(line)
            id_item = None if item else _ITEM_ID.match(line)
            if item or id_item:
                flush()
                if item and item.group(1):
                    last_number = int(item.group(1))
                body = (item.group(2) if item else id_item.group(2)).strip()  # type: ignore[union-attr]
                current = RawItem(category=section, page=page.page, text=body, excerpt=body)
            elif current is not None:
                current.text += " " + line
                if page.page == current.page:
                    current.excerpt = (current.excerpt + " " + line).strip()
    flush()
    return items


# --------------------------------------------------------------------------- rule parsing

_GTE = "|".join([
    "must not be below", "must not be less than", "not below", "not less than", "no less than", "at least",
    "greater than or equal to", "equal to or greater than", "minimum of", "≥", ">=",
])
_LTE = "|".join([
    "must not exceed", "not exceeding", "not exceed", "no more than", "not more than", "not greater than",
    "not above", "at most", "less than or equal to", "equal to or less than", "maximum of", "≤", "<=",
])
_LT = r"below|less than|lower than|under|<"
_GT = r"above|greater than|more than|higher than|exceeding|exceeds|exceed|>"
_OPS: list[tuple[str, str]] = [("gte", _GTE), ("lte", _LTE), ("lt", _LT), ("gt", _GT)]


def _unit_after(text: str, pos: int) -> str | None:
    m = UNIT_PATTERN.match(text, pos)
    if not m:
        m = UNIT_PATTERN.match(text, pos + 1) if pos < len(text) and text[pos] == " " else None
    return normalize_unit(m.group(0)) if m else None


_AGE_WORD = r"\bage[ds]?\b"


def _parse_age(t: str) -> ParsedRule | None:
    if not re.search(_AGE_WORD + r"|\byears?\b", t):
        return None
    m = re.search(
        _AGE_WORD + r"\s*(?:of\s*)?(?:between\s*)?" + _NUM + r"\s*(?:years?\s*)?(?:to|-|and)\s*" + _NUM
        + r"\s*(?:years?)?(?:\s*(?:of age|old))?\s*\(?(inclusive|exclusive)?",
        t,
    ) or re.search(
        r"(?:between\s*)?" + _NUM + r"\s*(?:to|-|and)\s*" + _NUM
        + r"\s*years?\s*(?:of age|old)?\s*\(?(inclusive|exclusive)?",
        t,
    )
    if m:
        lo, hi, incl = float(m.group(1)), float(m.group(2)), m.group(3)
        reasons = []
        inclusive: bool | None = {"inclusive": True, "exclusive": False}.get(incl or "")
        if inclusive is None:
            reasons.append("Age range does not state whether the bounds are inclusive.")
        rule = NormalizedRule(attribute="age", operator="between", value=lo, value_max=hi, unit="years",
                              inclusive=inclusive)
        return ParsedRule(rule, ["age"], 0.95 if inclusive is not None else 0.75, reasons)
    patterns = [
        ("gte", r"(?:≥|>=|at least)\s*" + _NUM + r"\s*years"),
        ("gte", _NUM + r"\s*years\s*(?:of age\s*)?(?:or|and)\s*(?:older|above|over)"),
        ("gte", _AGE_WORD + r"\s*(?:≥|>=)\s*" + _NUM),
        ("gt", r"(?:older than|over|>)\s*" + _NUM + r"\s*years"),
        ("lt", r"(?:younger than|under|<)\s*" + _NUM + r"\s*years"),
        ("lte", r"(?:≤|<=|at most|no older than)\s*" + _NUM + r"\s*years"),
    ]
    for op, pat in patterns:
        m = re.search(pat, t)
        if m:
            rule = NormalizedRule(attribute="age", operator=op, value=float(m.group(1)), unit="years")
            return ParsedRule(rule, ["age"], 0.9)
    return None


def _first_comparator(text: str, anchored: bool = False) -> tuple[int, str, re.Match] | None:
    """Earliest "<comparator> <number>" in text (or only at its start when anchored)."""
    best: tuple[int, str, re.Match] | None = None
    for op, phrases in _OPS:
        pattern = r"(?:" + phrases + r")\s*(?:a\s+value\s+of\s*)?" + _NUM
        m = re.match(r"\s*" + pattern, text) if anchored else re.search(pattern, text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), op, m)
    return best


# A connector right after a threshold, allowing up to two unit tokens: "1.5 mg/dl or ...", "30 and ...".
_CONNECTOR = re.compile(r"\s*(?:\S+\s+){0,2}?(and/or|or|and)\s+")


def _second_clause(attribute: str, rest: str) -> tuple[str, NormalizedRule | None, str] | None:
    """Parse a clause joined to a threshold by and/or, e.g. "... or creatinine clearance < 40 mL/min".

    Returns (combinator, rule, attribute of the second clause), with rule None when a second lab is
    named but its threshold cannot be parsed. Returns None when there is no second numeric clause.
    """
    conn = _CONNECTOR.match(rest)
    if not conn:
        return None
    combinator = "and" if conn.group(1) == "and" else "or"
    second = rest[conn.end():]
    found = find_lab_in_text(second)
    if found and second.find(found[1]) < 40:
        attr2, alias2 = found
        tail2 = second[second.find(alias2) + len(alias2):]
        cmp2 = _first_comparator(tail2)
        if cmp2 is None or cmp2[0] > 30:
            return combinator, None, attr2
    else:
        # Same attribute, second bound: the comparator must follow the connector directly ("and <= 90").
        attr2, tail2 = attribute, second
        cmp2 = _first_comparator(second, anchored=True)
        if cmp2 is None:
            return None
    _, op2, m2 = cmp2
    unit2 = _unit_after(tail2, m2.end())
    rule2 = NormalizedRule(attribute=attr2, operator=op2, value=float(m2.group(1)),  # type: ignore[arg-type]
                           unit=unit2 or CANONICAL_UNITS.get(attr2))
    return combinator, rule2, attr2


def _parse_lab(t: str) -> ParsedRule | None:
    found = find_lab_in_text(t)
    if not found:
        return None
    attribute, alias = found
    start = t.find(alias)
    tail = t[start + len(alias):]
    reasons: list[str] = []

    if re.search(r"\b\d+(?:\.\d+)?\s*(?:x|×|times)\s*(?:the\s*)?(?:uln|upper limit of normal)", tail):
        reasons.append("Threshold is relative to the upper limit of normal; patient reference range required.")
        return ParsedRule(None, [attribute], 0.5, reasons)

    window = re.search(r"(?:measured|obtained|collected|result|value)?\s*within\s*(?:the\s*)?(?:last\s*|past\s*)?"
                       + _NUM + r"\s*(days?|weeks?|months?)", tail)
    if window:
        days = float(window.group(1)) * {"d": 1, "w": 7, "m": 30}[window.group(2)[0]]
        stale_days = get_settings().stale_days
        if days != stale_days:
            reasons.append(
                f"Protocol requires a result from the last {days:g} days; "
                f"automatic staleness checks use {stale_days} days."
            )

    between = re.search(r"between\s*" + _NUM + r"\s*%?\s*(?:and|to|-)\s*" + _NUM, tail) or re.match(
        r"\s*(?:(?:of|level|value|concentration)\s*)?:?\s*" + _NUM + r"\s*%?\s*(?:-|to)\s*" + _NUM, tail
    )
    if between:
        unit = _unit_after(tail, between.end())
        bounds = re.match(r"\s*\S*\s*\(?(inclusive|exclusive)\b", tail[between.end():])
        inclusive: bool | None = {"inclusive": True, "exclusive": False}.get(bounds.group(1)) if bounds else None
        if inclusive is None:
            reasons.append("Range does not state whether the bounds are inclusive.")
        rule = NormalizedRule(
            attribute=attribute, operator="between", value=float(between.group(1)),
            value_max=float(between.group(2)), unit=unit or CANONICAL_UNITS.get(attribute),
            inclusive=inclusive,
        )
        return ParsedRule(rule, [attribute], 0.9 if inclusive is not None else 0.75, reasons)

    best = _first_comparator(tail)
    postfix = re.search(_NUM + r"\s*(\S+)?\s*or\s*(more|greater|higher|above|less|lower|below)", tail)
    if best is None and postfix:
        op = "gte" if postfix.group(3) in {"more", "greater", "higher", "above"} else "lte"
        value = float(postfix.group(1))
        unit = _unit_after(tail, postfix.start(1) + len(postfix.group(1)))
        start, end = postfix.start(), postfix.end()
    elif best is not None:
        _, op, m = best
        value = float(m.group(1))
        unit = _unit_after(tail, m.end())
        start, end = m.start(), m.end()
    else:
        reasons.append(f"{alias} is mentioned but no numeric threshold could be parsed.")
        return ParsedRule(None, [attribute], 0.4, reasons)

    # Compound criteria. (a) Shared threshold: "ALT or AST > 100 U/L". (b) A second clause after the
    # threshold: "eGFR >= 30 and <= 90", "creatinine > 1.5 mg/dL or creatinine clearance < 40 mL/min".
    secondary: NormalizedRule | None = None
    combinator: str | None = None
    shared = re.match(r"\s*(and/or|or|and)\s+(.*)$", tail[:start])
    shared_lab = find_lab_in_text(shared.group(2)) if shared else None
    if shared and shared_lab and shared_lab[0] != attribute:
        combinator = "and" if shared.group(1) == "and" else "or"
        secondary = NormalizedRule(attribute=shared_lab[0], operator=op, value=value,  # type: ignore[arg-type]
                                   unit=unit or CANONICAL_UNITS.get(shared_lab[0]))
    else:
        clause = _second_clause(attribute, tail[end:])
        if clause is not None:
            combinator, secondary, attr2 = clause
            if secondary is None:
                reasons.append("Compound criterion: the second clause could not be parsed into a rule; "
                               "requires review.")
                return ParsedRule(None, sorted({attribute, attr2}), 0.4, reasons)
            if unit is None and secondary.attribute == attribute and secondary.unit:
                unit = secondary.unit  # "30 and <= 90 mL/min/1.73m2": the unit is stated once, at the end

    confidence = 0.92 if secondary is None else 0.88
    if unit is None:
        unit = CANONICAL_UNITS.get(attribute)
        reasons.append(f"Unit not stated in protocol text; assumed {unit}.")
        confidence = 0.7
    rule = NormalizedRule(attribute=attribute, operator=op, value=value, unit=unit)  # type: ignore[arg-type]
    attrs = [attribute] + ([secondary.attribute] if secondary and secondary.attribute != attribute else [])
    return ParsedRule(rule, attrs, confidence, reasons, secondary, combinator)


_CONDITION_PREFIXES = re.compile(
    r"^(?:(?:a|any|known|documented|current|active|prior|previous|recent|confirmed|clinical)\s+)*"
    r"(?:history of|diagnosis of|presence of|evidence of|patients with|participants with|subjects with)?\s*",
)


# Digits that belong to a condition's name rather than to a threshold.
_NAMED_NUMBERS = re.compile(r"\btype\s*[12]\b|\bcovid-19\b|\bhiv-?[12]\b")


def _parse_condition(t: str) -> ParsedRule:
    body = t.rstrip(" .;")
    body = re.split(r",\s*(?:defined|as defined|including|e\.g\.|such as)\b", body)[0]
    body = _CONDITION_PREFIXES.sub("", body).strip()
    body = re.sub(r"\s+(?:diagnosis|diagnosed)$", "", body)
    # "... requiring urgent treatment" qualifies the condition; the concept is what precedes it.
    body = re.split(r"\s+(?:requiring|that requires?|which requires?|needing)\b", body)[0]
    terms = [p.strip(" .;") for p in re.split(r"\s+(?:and/or|or)\s+|,\s*", body) if p.strip(" .;")]
    reasons: list[str] = []
    for q in AMBIGUOUS_QUALIFIERS:
        if re.search(r"(?<![a-z])" + re.escape(q) + r"(?![a-z])", t):
            reasons.append(f"'{q}' is not defined numerically in the protocol; clinical interpretation required.")
            break
    confidence = 0.55 if reasons else 0.75
    rule = NormalizedRule(attribute="condition", operator="present", value=terms or [body])
    return ParsedRule(rule, ["condition:" + "|".join(terms or [body])], confidence, reasons)


def _parse_time_window(t: str) -> ParsedRule | None:
    m = re.search(r"within\s*(?:the\s*)?(?:last\s*|past\s*|previous\s*)?" + _NUM + r"\s*(days?|weeks?|months?)", t)
    if not m:
        return None
    n = float(m.group(1))
    days = n * {"d": 1, "w": 7, "m": 30}[m.group(2)[0]]
    subject = t[: m.start()].rstrip(" ,")
    subject = re.sub(r"^(?:received|receipt of|treatment with|use of|prior)\s+", "", subject).strip()
    reasons = []
    if m.group(2).startswith("month"):
        reasons.append("Month-based window converted to days using 30 days per month.")
    rule = NormalizedRule(attribute=f"event:{subject}", operator="within_days", value=days, unit="days")
    return ParsedRule(rule, [f"event:{subject}"], 0.7, reasons)


# "Missing or stale required laboratory result": a criterion about the data itself.
_DATA_COMPLETENESS = re.compile(
    r"\b(?:missing|stale|unavailable|incomplete|insufficient|outdated|undated)\b.*\b(?:laborator\w*|labs?|results?|data|values?|information)\b"
)


def parse_rule(text: str) -> ParsedRule:
    """Rule-based translation of one criterion's text into a NormalizedRule."""
    t = normalize_text(text)
    if any(marker in t for marker in _SEMANTIC_MARKERS):
        return ParsedRule(None, [], 0.4, ["Non-numeric criterion requires semantic evaluation."])
    if _DATA_COMPLETENESS.search(t) and not find_lab_in_text(t):
        # The labs it refers to are filled in from the protocol's other criteria (see extract_rule_based).
        rule = NormalizedRule(attribute="data_completeness", operator="present", value=[])
        return ParsedRule(rule, [], 0.8, [])
    for parser in (_parse_age, _parse_lab, _parse_time_window):
        parsed = parser(t)
        if parsed is not None:
            return parsed
    if re.search(r"\d", _NAMED_NUMBERS.sub("", t)):
        return ParsedRule(None, [], 0.4, ["Criterion contains numbers that could not be parsed into a rule."])
    return _parse_condition(t)


# --------------------------------------------------------------------------- builders


def _build_criterion(
    trial_id: str,
    category: str,
    index: int,
    text: str,
    page: int,
    excerpt: str,
    pages_by_no: dict[int, str],
    parsed: ParsedRule,
    method: str,
) -> Criterion:
    reasons = list(parsed.review_reasons)
    confidence = parsed.confidence
    page_text = pages_by_no.get(page)
    if page_text is None or not excerpt_on_page(excerpt, page_text):
        reasons.append(f"Source excerpt could not be verified on cited page {page}.")
        confidence = min(confidence, 0.3)
    if parsed.rule is None and not any("semantic" in r for r in reasons):
        reasons.append("No machine-readable rule; requires semantic evaluation or human review.")
    prefix = "INC" if category == "inclusion" else "EXC"
    return Criterion(
        criterion_id=f"{prefix}-{index:02d}",
        trial_id=trial_id,
        category=category,  # type: ignore[arg-type]
        original_text=text,
        normalized_rule=parsed.rule,
        secondary_rule=parsed.secondary if parsed.rule is not None else None,
        rule_combinator=parsed.combinator if parsed.rule is not None and parsed.secondary is not None else None,
        required_attributes=parsed.required_attributes,
        source_page=page,
        source_excerpt=excerpt,
        extraction_confidence=round(confidence, 2),
        requires_human_review=bool(reasons),
        review_reasons=reasons,
        extraction_method=method,  # type: ignore[arg-type]
    )


def _link_data_completeness(criteria: list[Criterion]) -> list[Criterion]:
    """Point data-completeness criteria at the lab values the protocol's other criteria require."""
    labs = sorted({
        c.normalized_rule.attribute for c in criteria
        if c.normalized_rule and c.normalized_rule.attribute in CANONICAL_UNITS and c.normalized_rule.attribute != "age"
    })
    out = []
    for c in criteria:
        if c.normalized_rule and c.normalized_rule.attribute == "data_completeness":
            rule = c.normalized_rule.model_copy(update={"value": labs})
            c = c.model_copy(update={"normalized_rule": rule, "required_attributes": labs})
        out.append(c)
    return out


def extract_rule_based(pages: list[PageText], trial_id: str) -> list[Criterion]:
    pages_by_no = {p.page: p.text for p in pages}
    counters = {"inclusion": 0, "exclusion": 0}
    criteria: list[Criterion] = []
    for item in find_criteria_items(pages):
        counters[item.category] += 1
        criteria.append(
            _build_criterion(
                trial_id, item.category, counters[item.category], item.text, item.page,
                item.excerpt, pages_by_no, parse_rule(item.text), "rule_based",
            )
        )
    return _link_data_completeness(criteria)


# --------------------------------------------------------------------------- LLM path

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_NUM = {"type": ["number", "null"]}

LLM_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criteria"],
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "category", "original_text", "source_page", "source_excerpt", "attribute", "operator",
                    "value", "value_terms", "value_max", "unit", "inclusive", "ambiguity_reason",
                ],
                "properties": {
                    "category": {"type": "string", "enum": ["inclusion", "exclusion"]},
                    "original_text": {"type": "string"},
                    "source_page": {"type": "integer"},
                    "source_excerpt": {"type": "string"},
                    "attribute": _NULLABLE_STR,
                    "operator": {
                        "type": ["string", "null"],
                        "enum": ["gt", "gte", "lt", "lte", "eq", "between", "present", "absent", "within_days", None],
                    },
                    "value": _NULLABLE_NUM,
                    "value_terms": {"type": ["array", "null"], "items": {"type": "string"}},
                    "value_max": _NULLABLE_NUM,
                    "unit": _NULLABLE_STR,
                    "inclusive": {"type": ["boolean", "null"]},
                    "ambiguity_reason": _NULLABLE_STR,
                },
            },
        }
    },
}

LLM_SYSTEM = (
    "You extract clinical trial eligibility criteria from protocol text. " + UNTRUSTED_DATA_RULE + " "
    "Return every inclusion and exclusion criterion in document order. original_text and source_excerpt "
    "must be copied verbatim from the page given as source_page. Use canonical attributes: age, egfr, "
    "creatinine, crcl, alt, ast, bilirubin, hemoglobin, platelets, anc, hba1c, lvef, qtc, bmi, weight, "
    "potassium, sodium; use attribute 'condition' with operator 'present' and value_terms for diagnoses. "
    "Set operator null when the rule cannot be expressed this way. Fill ambiguity_reason when wording is "
    "vague (e.g. 'severe', 'adequate') and no numeric definition is given. Never interpret vague wording."
)


def _required_attributes(rule: NormalizedRule | None) -> list[str]:
    """Patient attributes a model-proposed rule needs, named like the rule-based extractor names them.

    Condition rules use "condition:<terms>" so the Patient Profile Agent does not report a lab-style
    "condition" value as missing.
    """
    if rule is None:
        return []
    if rule.attribute == "condition":
        terms = rule.value if isinstance(rule.value, list) else [str(rule.value)]
        return ["condition:" + "|".join(terms)]
    return [rule.attribute]


def extract_with_llm(pages: list[PageText], trial_id: str, llm: LLMClient) -> list[Criterion]:
    doc = "\n".join(f'<document page="{p.page}">\n{p.text}\n</document>' for p in pages)
    data = llm.complete_json(LLM_SYSTEM, f"Extract the eligibility criteria.\n{doc}", LLM_SCHEMA)
    pages_by_no = {p.page: p.text for p in pages}
    counters = {"inclusion": 0, "exclusion": 0}
    criteria: list[Criterion] = []
    for raw in data.get("criteria", []):
        category = raw.get("category")
        if category not in counters:
            continue
        counters[category] += 1
        reasons: list[str] = []
        rule: NormalizedRule | None = None
        if raw.get("attribute") and raw.get("operator"):
            value = raw.get("value_terms") if raw.get("operator") in {"present", "absent"} else raw.get("value")
            try:
                rule = NormalizedRule(
                    attribute=raw["attribute"], operator=raw["operator"], value=value,
                    value_max=raw.get("value_max"), unit=normalize_unit(raw.get("unit")),
                    inclusive=raw.get("inclusive"),
                )
            except ValidationError as exc:
                reasons.append(f"Model-proposed rule failed validation: {exc.errors()[0]['msg']}")
        if raw.get("ambiguity_reason"):
            reasons.append(str(raw["ambiguity_reason"]))
        if rule and rule.operator == "between" and rule.inclusive is None:
            reasons.append("Range does not state whether the bounds are inclusive.")
        parsed = ParsedRule(rule, _required_attributes(rule), 0.85 if rule and not reasons else 0.6, reasons)
        criteria.append(
            _build_criterion(
                trial_id, category, counters[category], str(raw.get("original_text", "")).strip(),
                int(raw.get("source_page") or 0) or 1, str(raw.get("source_excerpt", "")).strip(),
                pages_by_no, parsed, "llm",
            )
        )
    return _link_data_completeness(criteria)


_ELIGIBILITY_HINT = re.compile(r"inclusion|exclusion|eligibility", re.IGNORECASE)
LLM_CHAR_BUDGET = 120_000


def select_llm_pages(pages: list[PageText], budget: int = LLM_CHAR_BUDGET) -> tuple[list[PageText], str | None]:
    """Pages worth sending to the LLM: those mentioning eligibility, plus one page either side.

    Keeps long protocols within the model's context window and cost. Returns the pages (in order)
    and a note when the selection or the character budget left pages out.
    """
    hits = {p.page for p in pages if _ELIGIBILITY_HINT.search(p.text)}
    wanted = {n for h in hits for n in (h - 1, h, h + 1)} if hits else {p.page for p in pages}
    selected, used = [], 0
    for p in pages:
        if p.page not in wanted:
            continue
        if used + len(p.text) > budget and selected:
            break
        selected.append(p)
        used += len(p.text)
    if len(selected) == len(pages):
        return selected, None
    sent = ", ".join(str(p.page) for p in selected)
    return selected, f"LLM extraction used pages {sent} of {len(pages)} (pages mentioning eligibility criteria)."


def extract_criteria(pages: list[PageText], trial_id: str, llm: LLMClient | None = None) -> ExtractionResult:
    warnings: list[str] = []
    if llm is not None:
        llm_pages, note = select_llm_pages(pages)
        if note:
            warnings.append(note)
        try:
            criteria = extract_with_llm(llm_pages, trial_id, llm)
            if criteria:
                return ExtractionResult(criteria, "llm", warnings)
            warnings.append("LLM returned no criteria; used rule-based extractor.")
        except (LLMError, ValidationError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning("LLM extraction failed, falling back to rule-based: %s", exc)
            warnings.append(f"LLM extraction failed ({type(exc).__name__}); used rule-based extractor.")
    return ExtractionResult(extract_rule_based(pages, trial_id), "rule_based", warnings)
