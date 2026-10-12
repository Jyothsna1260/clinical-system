"""Generate synthetic protocol PDFs with known page layout for tests and demos.

  page 1  title and synopsis
  page 2  Inclusion Criteria
  page 3  Exclusion Criteria

Writes the renal protocols used by the acceptance tests (protocol_renal.pdf,
protocol_renal_defined.pdf) plus two demo protocols (protocol_hepatic.pdf,
protocol_cardio.pdf), and a single-page protocol whose criteria are laid out as ruled
tables with criterion IDs (protocol_t2d_table.pdf). All content is synthetic.
Run from backend/:  python -m scripts.make_synthetic_protocol
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

TITLE = "SYN-RENAL-001: A Synthetic Phase II Study of Investigational Product XR-17"
SYNOPSIS = [
    "Protocol version 1.0 (synthetic document for software testing only).",
    "",
    "Synopsis",
    "This synthetic protocol describes a randomized, double-blind study of the",
    "investigational product XR-17 in adults with type 2 diabetes mellitus.",
    "XR-17 is cleared by the kidneys, so participant renal function is assessed",
    "at screening. No real patient data is contained in this document.",
    "",
    "Primary objective: change in HbA1c from baseline to week 24.",
]
INCLUSION = [
    "1. Age 18 to 70 years inclusive.",
    "2. Estimated glomerular filtration rate (eGFR) must not be below 30 mL/min/1.73m2.",
]


def exclusion(defined: bool) -> list[str]:
    first = (
        "1. Severe renal impairment, defined as eGFR below 30 mL/min/1.73m2."
        if defined
        else "1. Severe renal impairment."
    )
    return [first, "2. Pregnancy or breastfeeding."]


HEPATIC = {
    "code": "SYN-HEP-002",
    "title": "SYN-HEP-002: A Synthetic Phase II Study of Investigational Product HP-42",
    "synopsis": [
        "Protocol version 2.1 (synthetic document for software testing only).",
        "",
        "Synopsis",
        "This synthetic protocol describes an open-label study of the investigational",
        "product HP-42 in adults with metabolic dysfunction-associated steatotic liver",
        "disease. HP-42 is metabolised by the liver, so hepatic function and blood",
        "counts are assessed at screening. No real patient data is contained here.",
        "",
        "Primary objective: change in liver fat fraction from baseline to week 48.",
    ],
    "inclusion": [
        "1. Age 18 to 75 years inclusive.",
        "2. Platelet count must not be below 100 x10^9/L.",
        "3. Hemoglobin of at least 10 g/dL.",
    ],
    "exclusion": [
        "1. ALT above 120 U/L.",
        "2. Total bilirubin above 34 \u00b5mol/L.",
        "3. Decompensated cirrhosis.",
        "4. Pregnancy or breastfeeding.",
    ],
}

CARDIO = {
    "code": "SYN-CARDIO-003",
    "title": "SYN-CARDIO-003: A Synthetic Phase III Study of Investigational Product CV-9",
    "synopsis": [
        "Protocol version 1.3 (synthetic document for software testing only).",
        "",
        "Synopsis",
        "This synthetic protocol describes a randomized, placebo-controlled study of",
        "the investigational product CV-9 in adults with heart failure with reduced",
        "ejection fraction. CV-9 can prolong the QT interval and raise potassium, so",
        "cardiac and electrolyte safety is assessed at screening.",
        "",
        "Primary objective: time to first heart failure hospitalisation.",
    ],
    "inclusion": [
        "1. Age 40 years or older.",
        "2. Left ventricular ejection fraction (LVEF) must not exceed 40%.",
        "3. HbA1c below 10%.",
    ],
    "exclusion": [
        "1. Myocardial infarction within the last 90 days.",
        "2. QTc interval greater than 470 ms.",
        "3. Serum potassium above 5.5 mmol/L.",
        "4. Pregnancy or breastfeeding.",
    ],
}


def _page(c: canvas.Canvas, code: str, number: int, heading: str, lines: list[str], heading_size: int = 14) -> None:
    width, height = A4
    y = height - 2.5 * cm
    c.setFont("Helvetica-Bold", heading_size)
    c.drawString(2 * cm, y, heading)
    y -= 1.0 * cm
    c.setFont("Helvetica", 11)
    for line in lines:
        c.drawString(2 * cm, y, line)
        y -= 0.6 * cm
    c.setFont("Helvetica", 8)
    c.drawString(2 * cm, 1.5 * cm, f"{code} synthetic protocol - Page {number} of 3")
    c.showPage()


def write_protocol(
    path: Path, code: str, title: str, synopsis: list[str], inclusion: list[str], exclusion: list[str]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(title)
    first = [title[60:].strip(), *synopsis] if len(title) > 60 else synopsis
    _page(c, code, 1, title[:60], first, heading_size=12)
    _page(c, code, 2, "Inclusion Criteria", ["Participants must meet all of the following criteria:", "", *inclusion])
    _page(c, code, 3, "Exclusion Criteria", ["Participants meeting any of the following are excluded:", "", *exclusion])
    c.save()
    return path


def make_protocol(path: Path, defined: bool) -> Path:
    return write_protocol(path, "SYN-RENAL-001", TITLE, SYNOPSIS, INCLUSION, exclusion(defined))


def make_demo_protocol(path: Path, spec: dict) -> Path:
    return write_protocol(path, spec["code"], spec["title"], spec["synopsis"], spec["inclusion"], spec["exclusion"])


DEMO_PROTOCOLS = {"protocol_hepatic.pdf": HEPATIC, "protocol_cardio.pdf": CARDIO}

# Table layout: numbered sections with qualifier words in the headings, criteria in ruled
# tables (ID / Criterion / Notes), wrapped cells, en-dash ranges and a data-completeness item.
T2D_TABLE = {
    "code": "SYN-T2D-004",
    "title": "SYN-T2D-004: Synthetic Type 2 Diabetes Study (table layout)",
    "inclusion": [
        ("I-01", "Age 30–70 years inclusive", "Age within range on the assessment date"),
        ("I-02", "Documented diagnosis of type 2 diabetes", "Diagnosis recorded in the patient record"),
        ("I-03", "HbA1c 7.5%–10.5% inclusive, measured within 90 days before assessment", "Dated result required"),
        ("I-04", "eGFR at least 45 mL/min/1.73m2", "Dated result required"),
        ("I-05", "Potassium 3.5–5.0 mmol/L inclusive, measured within 30 days", "Dated result required"),
    ],
    "exclusion": [
        ("E-01", "Known type 1 diabetes diagnosis", "Exclude if documented"),
        ("E-02", "Pregnancy or breastfeeding", "Exclude if documented"),
        ("E-03", "Recent acute medical instability requiring urgent treatment", "Refer for clinician review"),
        ("E-04", "Missing or stale required laboratory result", "Report as insufficient information"),
    ],
}


def make_table_protocol(path: Path, spec: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    cell = styles["BodyText"]

    def table(rows: list[tuple[str, str, str]]) -> Table:
        data = [["ID", "Criterion", "Notes"]] + [[i, Paragraph(c, cell), Paragraph(n, cell)] for i, c, n in rows]
        t = Table(data, colWidths=[1.8 * cm, 9.2 * cm, 5.5 * cm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    story = [
        Paragraph(spec["title"], styles["Title"]),
        Paragraph("Synthetic document for software testing only. No real patient data.", cell),
        Paragraph("1. Study Overview", styles["Heading2"]),
        Paragraph("Adults with type 2 diabetes receiving a hypothetical oral therapy.", cell),
        Paragraph("2. Key Inclusion Criteria", styles["Heading2"]),
        table(spec["inclusion"]),
        Spacer(1, 0.4 * cm),
        Paragraph("3. Key Exclusion Criteria", styles["Heading2"]),
        table(spec["exclusion"]),
        Paragraph("4. Data Requirements for Screening", styles["Heading2"]),
        Paragraph("Lab values need units and observation dates. Missing values are reported as missing.", cell),
        Paragraph("5. Screening Outcomes", styles["Heading2"]),
        Paragraph("Eligible, not eligible, or more information required.", cell),
    ]
    SimpleDocTemplate(str(path), pagesize=A4, title=spec["title"]).build(story)
    return path


def main() -> None:
    for name, defined in (("protocol_renal.pdf", False), ("protocol_renal_defined.pdf", True)):
        print("wrote", make_protocol(FIXTURES / name, defined))
    for name, spec in DEMO_PROTOCOLS.items():
        print("wrote", make_demo_protocol(FIXTURES / name, spec))
    print("wrote", make_table_protocol(FIXTURES / "protocol_t2d_table.pdf", T2D_TABLE))


if __name__ == "__main__":
    main()
